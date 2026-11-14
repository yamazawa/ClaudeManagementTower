from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from app.routes import projects
from core.db import ensure_default_project, init_db


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    ensure_default_project()
    yield


app = FastAPI(title="Claude管理塔", lifespan=lifespan)

app.include_router(projects.router)
app.mount("/static", StaticFiles(directory="app/static"), name="static")


@app.get("/health")
def health() -> dict:
    return {"status": "ok"}


@app.get("/")
def index() -> FileResponse:
    return FileResponse("app/static/index.html")
