from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.config import settings
from app.db import init_db
from app.routers import projects
from app.studio import router as studio
from app.studio.jobs import get_runner


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    get_runner().recover_stale_jobs()
    yield


app = FastAPI(title="AI Video Factory", version="0.1.0", lifespan=lifespan)


@app.get("/health")
def health():
    return {"status": "ok", "factory_paused": settings.factory_paused}


app.include_router(projects.router)
app.include_router(studio.router)
