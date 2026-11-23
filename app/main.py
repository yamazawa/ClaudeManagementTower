import uuid
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from app.routes import cli, deploy, ideas, jobs, merges, mr_statuses, projects, subtasks, system, workers
from core.cli_session import recover_interrupted_sessions
from core.claude_usage import start_refresh_loop as start_usage_refresh_loop
from core.config import settings
from core.db import ensure_default_project, init_db
from core.idea_approval import recover_interrupted_claims
from core.merge_queue import start_merge_loop
from core.pr_sync import start_sync_loop

# サーバー再起動の完了を画面側で判定するための起動ごとの識別子
BOOT_ID = uuid.uuid4().hex


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    ensure_default_project()
    recover_interrupted_sessions()
    recover_interrupted_claims()
    stop_pr_sync = start_sync_loop(settings.pr_sync_interval_seconds)
    stop_merge_loop = start_merge_loop()
    stop_usage_refresh = start_usage_refresh_loop(settings.claude_usage_refresh_interval_seconds)
    yield
    stop_pr_sync.set()
    stop_merge_loop.set()
    stop_usage_refresh.set()


app = FastAPI(title="Claude管理塔", lifespan=lifespan)

app.include_router(projects.router)
app.include_router(deploy.router)
app.include_router(subtasks.router)
app.include_router(jobs.router)
app.include_router(workers.router)
app.include_router(merges.router)
app.include_router(mr_statuses.router)
app.include_router(system.router)
app.include_router(cli.router)
app.include_router(ideas.router)
app.mount("/static", StaticFiles(directory="app/static"), name="static")


@app.middleware("http")
async def no_cache(request, call_next):
    response = await call_next(request)
    response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate"
    return response


@app.get("/health")
def health() -> dict:
    return {"status": "ok", "boot_id": BOOT_ID}


@app.get("/")
def index() -> FileResponse:
    return FileResponse("app/static/index.html")
