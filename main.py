# 终端运行：uvicorn main:app --reload

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from agent.react_agent import ReactAgent
from agent.tools.agent_tools import warmup_services
from api.routers import router as api_router
from memory.session_store import MySQLSessionStore
from utils.path_tool import get_abs_path


@asynccontextmanager
async def lifespan(app: FastAPI):
    session_store = MySQLSessionStore()
    session_store.setup()
    app.state.session_store = session_store
    app.state.agent = ReactAgent()
    warmup_services()
    try:
        yield
    finally:
        app.state.agent.close()


app = FastAPI(title="Tourism Guide Agent", version="0.1.0", lifespan=lifespan)

app.include_router(api_router)
app.mount("/static", StaticFiles(directory=get_abs_path("static")), name="static")


@app.get("/")
def index() -> FileResponse:
    return FileResponse(get_abs_path("static/index.html"))

# 测试回答：我想去杭州旅游三天，帮我找一段天气好的时间给我做一份旅游攻略。
