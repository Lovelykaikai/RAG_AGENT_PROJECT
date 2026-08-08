import json
from collections.abc import Iterator
from uuid import uuid4

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import StreamingResponse

from agent.react_agent import ReactAgent
from api.schemas import (
    ChatRequest,
    HistoryMessage,
    SessionRenameRequest,
    SessionResponse,
)
from memory.session_store import DEFAULT_SESSION_TITLE, MySQLSessionStore
from utils.logger_handler import logger


router = APIRouter(prefix="/api", tags=["chat"])


def get_agent(request: Request) -> ReactAgent:
    """从 FastAPI 全局状态中获取 Agent 实例，供聊天和历史消息接口调用。"""
    return request.app.state.agent


def get_session_store(request: Request) -> MySQLSessionStore:
    """从 FastAPI 全局状态中获取会话存储实例，供会话接口读写 MySQL 元数据。"""
    return request.app.state.session_store


def make_session_title(message: str) -> str:
    """根据用户首次发送的消息生成会话标题，供前端左侧会话列表显示。"""
    title = " ".join(message.split())
    return title[:24] + ("..." if len(title) > 24 else "")


def stream_agent_answer(message: str, thread_id: str, agent: ReactAgent) -> Iterator[str]:
    """将 Agent 内部事件转换为前端可读取的 NDJSON 流式响应。"""
    try:
        for event in agent.execute_stream(message, thread_id):
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
                yield json.dumps(
                    {
                        "type": "tool_call",
                        "tool": event.get("tool"),
                        "args": event.get("args", {}),
                        "tool_call_id": event.get("tool_call_id"),
                    },
                    ensure_ascii=False,
                ) + "\n"
            elif event_type == "tool_done":
                yield json.dumps(
                    {
                        "type": "tool_done",
                        "tool": event.get("tool"),
                        "tool_call_id": event.get("tool_call_id"),
                    },
                    ensure_ascii=False,
                ) + "\n"
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


@router.post("/sessions", response_model=SessionResponse)
def create_session(request: Request) -> dict:
    """创建一个新的会话，并返回前端需要保存的 thread_id 和会话元数据。"""
    thread_id = f"thread_{uuid4().hex}"
    return get_session_store(request).create(thread_id)


@router.get("/sessions", response_model=list[SessionResponse])
def list_sessions(request: Request) -> list[dict]:
    """查询所有会话，供前端初始化和刷新左侧会话列表。"""
    return get_session_store(request).list()


@router.get("/sessions/{thread_id}/messages", response_model=list[HistoryMessage])
def get_session_messages(thread_id: str, request: Request) -> list[dict]:
    """读取指定会话的历史消息，供前端切换会话时恢复聊天内容。"""
    session_store = get_session_store(request)
    if session_store.get(thread_id) is None:
        raise HTTPException(status_code=404, detail="会话不存在")
    return get_agent(request).get_history(thread_id)


@router.post("/sessions/{thread_id}/reset", response_model=SessionResponse)
def reset_session(thread_id: str, request: Request) -> dict:
    """清除指定会话的 Agent 状态并重置会话元数据，供前端执行清空会话操作。"""
    session_store = get_session_store(request)
    if session_store.get(thread_id) is None:
        raise HTTPException(status_code=404, detail="会话不存在")
    get_agent(request).reset_thread(thread_id)
    return session_store.reset(thread_id)  # type: ignore[return-value]


@router.patch("/sessions/{thread_id}", response_model=SessionResponse)
def rename_session(
    thread_id: str,
    payload: SessionRenameRequest,
    request: Request,
) -> dict:
    """修改会话标题，并将更新后的会话信息返回给前端。"""
    session = get_session_store(request).rename(thread_id, payload.title.strip())
    if session is None:
        raise HTTPException(status_code=404, detail="会话不存在")
    return session


@router.post("/chat")
def chat(payload: ChatRequest, http_request: Request) -> StreamingResponse:
    """接收前端聊天请求，更新会话元数据，并将 Agent 输出以 NDJSON 流返回前端。"""
    message = payload.message.strip()
    thread_id = payload.thread_id.strip()
    if not message:
        raise HTTPException(status_code=400, detail="message不能为空")
    if not thread_id:
        raise HTTPException(status_code=400, detail="thread_id不能为空")

    session_store = get_session_store(http_request)
    session = session_store.get(thread_id)
    if session is None:
        session_store.create(thread_id, make_session_title(message))
    elif session["title"] == DEFAULT_SESSION_TITLE:
        session_store.rename(thread_id, make_session_title(message))
    else:
        session_store.touch(thread_id)

    return StreamingResponse(
        stream_agent_answer(message, thread_id, get_agent(http_request)),
        media_type="application/x-ndjson; charset=utf-8",
    )
