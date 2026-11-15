from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from app.routes import jobs, projects, subtasks, workers
from core.db import ensure_default_project, init_db


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    ensure_default_project()
    yield


app = FastAPI(title="Claude管理塔", lifespan=lifespan)

app.include_router(projects.router)
app.include_router(subtasks.router)
app.include_router(jobs.router)
app.include_router(workers.router)
app.mount("/static", StaticFiles(directory="app/static"), name="static")


@app.middleware("http")
async def no_cache_static(request, call_next):
    response = await call_next(request)
    if request.url.path.startswith("/static/") or request.url.path == "/":
        response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate"
    return response


@app.get("/health")
def health() -> dict:
    return {"status": "ok"}


@app.get("/")
def index() -> FileResponse:
    return FileResponse("app/static/index.html")
