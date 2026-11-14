from contextlib import asynccontextmanager

from fastapi import FastAPI

from core.db import init_db


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    yield


app = FastAPI(title="Claude管理塔", lifespan=lifespan)


@app.get("/health")
def health() -> dict:
    return {"status": "ok"}
