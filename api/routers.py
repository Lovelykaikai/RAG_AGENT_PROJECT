import json
from functools import lru_cache
from collections.abc import Iterator

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse

from agent.react_agent import ReactAgent
from api.schemas import ChatRequest
from utils.logger_handler import logger


router = APIRouter(prefix="/api", tags=["chat"])


@lru_cache(maxsize=1)
def get_agent() -> ReactAgent:
    return ReactAgent()


def stream_agent_answer(message: str) -> Iterator[str]:
    try:
        for event in get_agent().execute_stream(message):
            event_type = event.get("type")
            if event_type == "message":
                yield json.dumps(
                    {
                        "type": "chunk",
                        "content": event.get("content", ""),
                    },
                    ensure_ascii=False,
                ) + "\n"
            elif event_type == "tool_call":
                logger.info(
                    f"[api_chat]Agent调用工具: {event.get('tool')} {event.get('args', {})}"
                )
            elif event_type == "error":
                logger.error(f"[api_chat]Agent返回错误事件: {event.get('content')}")
                yield json.dumps(
                    {
                        "type": "error",
                        "content": "Agent执行失败，请查看后端日志。",
                    },
                    ensure_ascii=False,
                ) + "\n"
                return

        yield json.dumps({"type": "done"}, ensure_ascii=False) + "\n"
    except Exception as exc:
        logger.error(f"[api_chat]调用Agent失败: {str(exc)}", exc_info=True)
        yield json.dumps(
            {
                "type": "error",
                "content": "Agent调用失败",
            },
            ensure_ascii=False,
        ) + "\n"


@router.post("/chat")
def chat(request: ChatRequest) -> StreamingResponse:
    message = request.message.strip()
    if not message:
        raise HTTPException(status_code=400, detail="message不能为空")

    return StreamingResponse(
        stream_agent_answer(message),
        media_type="application/x-ndjson; charset=utf-8",
    )
