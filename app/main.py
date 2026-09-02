from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.config import settings
from app.db import init_db
from app.routers import projects


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    yield


app = FastAPI(title="AI Video Factory", version="0.1.0", lifespan=lifespan)


@app.get("/health")
def health():
    return {"status": "ok", "factory_paused": settings.factory_paused}


app.include_router(projects.router)
