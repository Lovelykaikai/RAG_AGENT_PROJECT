from collections.abc import Iterator
from typing import Any

from langchain.agents import create_agent

from agent.tools.agent_tools import TOOLS
from agent.tools.middleware import log_before_model, monitor_tool, report_prompt_switch
from model.factory import chat_model
from utils.config_handler import chroma_conf
from utils.logger_handler import logger
from utils.path_tool import get_abs_path
from utils.prompt_loader import load_system_prompt


class ReactAgent:
    def __init__(self):
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
        )

    def execute_stream(self, query: str) -> Iterator[dict[str, Any]]:
        """返回结构化事件流，方便前端区分模型消息、工具调用和错误。"""
        input_dict = {
            "messages": [
                {"role": "user", "content": query},
            ]
        }
        seen_message_ids: set[str] = set()

        try:
            for chunk in self.agent.stream(
                input_dict,
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

                tool_calls = getattr(latest_message, "tool_calls", None)
                if tool_calls:
                    for tool_call in tool_calls:
                        yield {
                            "type": "tool_call",
                            "tool": tool_call.get("name"),
                            "args": tool_call.get("args", {}),
                        }

                content = getattr(latest_message, "content", None)
                if content:
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

    def execute_text_stream(self, query: str) -> Iterator[str]:
        """返回文本流，方便命令行或简单控制台测试。"""
        for event in self.execute_stream(query):
            event_type = event.get("type")
            if event_type == "message":
                yield event["content"] + "\n"
            elif event_type == "tool_call":
                yield f"[调用工具] {event.get('tool')} {event.get('args', {})}\n"
            elif event_type == "error":
                yield f"[错误] {event.get('content')}\n"


if __name__ == "__main__":
    print(get_abs_path(chroma_conf["persist_directory"]))