from functools import lru_cache

from fastapi import APIRouter, HTTPException

from agent.react_agent import ReactAgent
from api.schemas import ChatRequest, ChatResponse
from utils.logger_handler import logger


router = APIRouter(prefix="/api", tags=["chat"])


@lru_cache(maxsize=1)
def get_agent() -> ReactAgent:
    return ReactAgent()


@router.post("/chat", response_model=ChatResponse)
def chat(request: ChatRequest) -> ChatResponse:
    message = request.message.strip()
    if not message:
        raise HTTPException(status_code=400, detail="message不能为空")

    try:
        answer = "".join(get_agent().execute_text_stream(message)).strip()
        return ChatResponse(answer=answer)
    except Exception as exc:
        logger.error(f"[api_chat]调用Agent失败: {str(exc)}", exc_info=True)
        raise HTTPException(status_code=500, detail="Agent调用失败") from exc

