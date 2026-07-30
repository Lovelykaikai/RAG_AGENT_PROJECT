from pydantic import BaseModel, Field
from datetime import datetime


class ChatRequest(BaseModel):
    message: str = Field(..., min_length=1, description="用户输入的问题")
    thread_id: str = Field(..., min_length=1, max_length=128, description="会话 thread_id")


class SessionResponse(BaseModel):
    thread_id: str
    title: str
    created_at: datetime
    updated_at: datetime


class HistoryMessage(BaseModel):
    id: str | None = None
    role: str
    content: str
    tool: str = ""


class SessionRenameRequest(BaseModel):
    title: str = Field(..., min_length=1, max_length=255)
