"""/studio/* endpoints.

Reads mirror the pipeline manifests; writes go to studio_* tables only, except
launches, which run the real pipeline stage (mock sandbox or live, per
STUDIO_EXECUTION_MODE) behind explicit confirmation and budget checks.
"""
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import get_session
from app.studio import control
from app.studio.execution import execution_info
from app.studio.importers.manifest_importer import default_data_dir, import_all
from app.studio.jobs import JobRunner, get_runner
from app.studio.models import StudioJob, StudioProject
from app.studio.service import build_snapshot, job_out

router = APIRouter(prefix="/studio", tags=["studio"])

_MEDIA_TYPES = {".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".png": "image/png", ".mp4": "video/mp4"}


class DecisionIn(BaseModel):
    decision: str  # "approve" | "reject"
    note: str | None = None


class LaunchIn(BaseModel):
    mode: str  # "continue" | "retry"
    request_id: str
    confirmed: bool = False
    approve_first: bool = False
    note: str | None = None


def _error(e: control.ControlError) -> JSONResponse:
    return JSONResponse(status_code=e.status_code, content={"detail": e.message, "problems": e.problems})


@router.get("/snapshot")
def snapshot(project: str | None = None, db: Session = Depends(get_session)):
    return build_snapshot(db, project)


@router.get("/execution")
def execution():
    return execution_info()


@router.post("/import")
def reimport(db: Session = Depends(get_session)):
    results = import_all(db)
    return [{"slug": r.slug, "found": r.found, "error": r.error, "events_created": r.events_created}
            for r in results]


@router.post("/projects/{slug}/activate")
def activate(slug: str, db: Session = Depends(get_session)):
    projects = db.scalars(select(StudioProject)).all()
    if slug not in {p.slug for p in projects}:
        raise HTTPException(status_code=404, detail=f"Studio project {slug} not found")
    for p in projects:
        p.is_active = p.slug == slug
    db.commit()
    return {"active": slug}


@router.post("/projects/{slug}/stages/{key}/decision")
def decide(slug: str, key: str, body: DecisionIn, db: Session = Depends(get_session)):
    """Approve Only / Reject. Records the decision; never launches or spends anything."""
    try:
        approval = control.record_decision(db, slug, key, body.decision, body.note)
    except control.ControlError as e:
        return _error(e)
    return {"stage_key": key, "status": approval.status.value, "note": approval.note}


@router.get("/projects/{slug}/stages/{key}/launch-preview")
def launch_preview(slug: str, key: str, mode: str = Query(...), db: Session = Depends(get_session)):
    try:
        return control.launch_plan(db, slug, key, mode)
    except control.ControlError as e:
        return _error(e)


@router.post("/projects/{slug}/stages/{key}/launch", status_code=202)
def launch(slug: str, key: str, body: LaunchIn, db: Session = Depends(get_session),
           runner: JobRunner = Depends(get_runner)):
    try:
        job = control.launch(db, runner, slug, key, mode=body.mode, request_id=body.request_id,
                             confirmed=body.confirmed, approve_first=body.approve_first, note=body.note)
    except control.ControlError as e:
        return _error(e)
    return job_out(job)


@router.get("/jobs/{job_id}")
def get_job(job_id: str, db: Session = Depends(get_session)):
    job = db.get(StudioJob, job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found")
    return job_out(job, full_log=True)


@router.get("/media")
def media(path: str = Query(...)):
    """Serve a generated file - only from inside the studio data directory, only known media types."""
    data_root = default_data_dir().resolve()
    target = Path(path).resolve()
    if not target.is_relative_to(data_root) or target.suffix.lower() not in _MEDIA_TYPES:
        raise HTTPException(status_code=403, detail="Not a studio media file")
    if not target.is_file():
        raise HTTPException(status_code=404, detail="File not found")
    return FileResponse(target, media_type=_MEDIA_TYPES[target.suffix.lower()])
