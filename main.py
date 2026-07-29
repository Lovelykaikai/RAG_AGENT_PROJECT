from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from api.routers import router as api_router
from utils.path_tool import get_abs_path


app = FastAPI(title="Tourism Guide Agent", version="0.1.0")

app.include_router(api_router)
app.mount("/static", StaticFiles(directory=get_abs_path("static")), name="static")


@app.get("/")
def index() -> FileResponse:
    return FileResponse(get_abs_path("static/index.html"))
