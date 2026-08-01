from collections.abc import Iterator
from typing import Any

from langchain.agents import create_agent
from langgraph.checkpoint.base import BaseCheckpointSaver

from agent.tools.agent_tools import TOOLS
from agent.tools.middleware import log_before_model, monitor_tool, report_prompt_switch
from memory.mysql_checkpointer import MySQLCheckpointer
from model.factory import chat_model
from utils.config_handler import chroma_conf
from utils.logger_handler import logger
from utils.path_tool import get_abs_path
from utils.prompt_loader import load_system_prompt


class ReactAgent:
    def __init__(self, checkpointer: BaseCheckpointSaver | None = None):
        self._checkpointer_manager: MySQLCheckpointer | None = None
        if checkpointer is None:
            self._checkpointer_manager = MySQLCheckpointer()
            checkpointer = self._checkpointer_manager.start()

        self.checkpointer = checkpointer
        self.agent = create_agent(
            model=chat_model,
            system_prompt=load_system_prompt(),
            tools=TOOLS,
            middleware=[
                monitor_tool,
                log_before_model,
                report_prompt_switch,
            ],
            context_schema=dict,
            checkpointer=self.checkpointer,
        )

    def close(self) -> None:
        """Release an internally managed MySQL checkpointer."""
        if self._checkpointer_manager is not None:
            self._checkpointer_manager.close()

    def get_history(self, thread_id: str) -> list[dict[str, Any]]:
        """Read the latest persisted message state for one conversation."""
        state = self.agent.get_state({"configurable": {"thread_id": thread_id}})
        messages = state.values.get("messages", []) if state else []
        return [
            self._serialize_message(message)
            for message in messages
            if self._is_displayable_message(message)
        ]

    def reset_thread(self, thread_id: str) -> None:
        """Delete all checkpoint state for one conversation."""
        self.checkpointer.delete_thread(thread_id)

    @staticmethod
    def _serialize_message(message: Any) -> dict[str, Any]:
        message_type = getattr(message, "type", "assistant")
        role = {
            "human": "user",
            "ai": "assistant",
            "tool": "tool",
            "system": "system",
        }.get(message_type, "assistant")
        content = getattr(message, "content", "")
        if isinstance(content, list):
            content = "\n".join(
                item.get("text", "") if isinstance(item, dict) else str(item)
                for item in content
            )
        return {
            "id": getattr(message, "id", None),
            "role": role,
            "content": str(content),
            "tool": getattr(message, "name", "") or "",
        }

    @staticmethod
    def _is_displayable_message(message: Any) -> bool:
        """Keep user messages and final AI messages in the conversation view."""
        message_type = getattr(message, "type", "")
        if message_type == "human":
            return True
        return message_type == "ai" and not getattr(message, "tool_calls", None)

    def execute_stream(self, query: str, thread_id: str) -> Iterator[dict[str, Any]]:
        """返回结构化事件流，方便前端区分模型消息、工具调用和错误。"""
        input_dict = {
            "messages": [
                {"role": "user", "content": query},
            ]
        }
        config = {
            "configurable": {
                "thread_id": thread_id,
            }
        }
        seen_message_ids: set[str] = set()

        try:
            for chunk in self.agent.stream(
                input_dict,
                config=config,
                stream_mode="values",
                context={"report": False},
            ):
                messages = chunk.get("messages", [])
                if not messages:
                    continue

                latest_message = messages[-1]
                message_id = getattr(latest_message, "id", None)
                if message_id and message_id in seen_message_ids:
                    continue
                if message_id:
                    seen_message_ids.add(message_id)

                message_type = getattr(latest_message, "type", "")
                if message_type == "human" or message_type == "system":
                    continue

                tool_calls = getattr(latest_message, "tool_calls", None)
                if message_type == "ai" and tool_calls:
                    for tool_call in tool_calls:
                        yield {
                            "type": "tool_call",
                            "tool": tool_call.get("name"),
                            "args": tool_call.get("args", {}),
                            "tool_call_id": tool_call.get("id"),
                        }
                    continue

                if message_type == "tool":
                    yield {
                        "type": "tool_done",
                        "tool": getattr(latest_message, "name", "") or "旅行工具",
                        "tool_call_id": getattr(latest_message, "tool_call_id", None),
                    }
                    continue

                content = getattr(latest_message, "content", None)
                if message_type == "ai" and content:
                    yield {
                        "type": "message",
                        "content": content.strip(),
                    }
        except Exception as e:
            logger.error(f"[ReactAgent]执行失败: {str(e)}", exc_info=True)
            yield {
                "type": "error",
                "content": f"Agent执行失败: {str(e)}",
            }

    def execute_text_stream(self, query: str, thread_id: str) -> Iterator[str]:
        """返回文本流，方便命令行或简单控制台测试。"""
        for event in self.execute_stream(query, thread_id):
            event_type = event.get("type")
            if event_type == "message":
                yield event["content"] + "\n"
            elif event_type == "tool_call":
                yield f"[调用工具] {event.get('tool')} {event.get('args', {})}\n"
            elif event_type == "error":
                yield f"[错误] {event.get('content')}\n"


if __name__ == "__main__":
    print(get_abs_path(chroma_conf["persist_directory"]))
    agent = ReactAgent()

    query = "帮我生成一份上海三日游旅游攻略报告，出发地是上海虹桥站，日期是2026-08-01。"

    for text in agent.execute_text_stream(query, "cli_demo"):
        print(text, end="")
