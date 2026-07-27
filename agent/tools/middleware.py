from typing import Any, Callable

from langchain.agents.middleware import (
    AgentState,
    ModelRequest,
    Runtime,
    ToolCallRequest,
    before_model,
    dynamic_prompt,
    wrap_tool_call,
)

from utils.logger_handler import logger
from utils.prompt_loader import load_report_prompt, load_system_prompt


@before_model
def log_before_model(state: AgentState, runtime: Runtime) -> None:
    """在模型调用前记录消息数量和最后一条消息，方便调试Agent执行过程。"""
    messages = state.get("messages", [])
    logger.info(f"[log_before_model]即将调用模型，带有{len(messages)}条消息。")

    if messages:
        last_message = messages[-1]
        content = getattr(last_message, "content", "")
        logger.debug(f"[log_before_model]{type(last_message).__name__} | {content}")

    return None


@wrap_tool_call
def monitor_tool(
    request: ToolCallRequest,
    handler: Callable[[ToolCallRequest], Any],
) -> Any:
    """监听工具调用；当报告上下文工具被调用时，在runtime.context里标记report=True。"""
    tool_name = request.tool_call["name"]
    tool_args = request.tool_call.get("args", {})
    logger.info(f"[tool_monitor]执行工具: {tool_name}")
    logger.info(f"[tool_monitor]传入参数: {tool_args}")

    try:
        result = handler(request)
        logger.info(f"[tool_monitor]工具{tool_name}调用成功")

        if tool_name == "fill_context_for_report":
            context = request.runtime.context
            if isinstance(context, dict):
                context["report"] = True
                logger.info("[tool_monitor]已标记报告生成上下文: report=True")
            else:
                logger.warning("[tool_monitor]runtime.context不是dict，无法标记report=True")

        return result
    except Exception as e:
        logger.error(f"[tool_monitor]工具{tool_name}调用失败，原因: {str(e)}", exc_info=True)
        raise


@dynamic_prompt
def report_prompt_switch(request: ModelRequest) -> str:
    """根据runtime.context中的report标记，在主提示词和报告提示词之间动态切换。"""
    context = request.runtime.context
    is_report = isinstance(context, dict) and context.get("report", False)

    if is_report:
        return load_report_prompt()

    return load_system_prompt()
