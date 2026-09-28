"""/studio/* endpoints.

Reads mirror the pipeline manifests; writes go to studio_* tables only, except
launches, which run the real pipeline stage (mock sandbox or live, per
STUDIO_EXECUTION_MODE) behind explicit confirmation and budget checks.
"""
import json
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import get_session
from app.studio import control
from app.studio.attempt_status import (
    AttemptCheckError,
    attempt_phase,
    check_attempt,
    heartbeat_fresh,
    is_unfinished,
)
from app.studio.execution import execution_info
from app.forma.production import budget as production_budget
from app.forma.production import stills as still_store
from app.forma.production import submit as production_submit
from app.forma.production.spec import SpecError, load_spec
from app.studio import manual_stills
from app.studio.importers.manifest_importer import default_data_dir, import_all, import_project
from app.studio.importers.stage_maps import PROJECTS_BY_SLUG, refresh_spec_projects
from app.studio.jobs import JobRunner, get_runner
from app.studio.models import StudioJob, StudioProject
from app.studio.service import build_snapshot, job_out, media_url

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


def _manifest_path(db: Session, slug: str) -> Path:
    project = db.scalars(select(StudioProject).where(StudioProject.slug == slug)).first()
    if project is None or not project.source_path:
        raise HTTPException(status_code=404, detail=f"Studio project {slug} has no manifest")
    return Path(project.source_path)


def _resync(db: Session, slug: str) -> None:
    refresh_spec_projects()
    if slug in PROJECTS_BY_SLUG:
        import_project(db, PROJECTS_BY_SLUG[slug])
        db.commit()


# --- manual stills (local only: no provider calls, nothing generated) --------------------------------

class NoteIn(BaseModel):
    note: str


@router.get("/projects/{slug}/stills")
def list_stills(slug: str, db: Session = Depends(get_session)):
    manifest_path = _manifest_path(db, slug)
    return list(manual_stills.infos(slug, manifest_path, media_url=lambda p: media_url(p, True)).values())


@router.post("/projects/{slug}/stills/{key}/upload")
async def upload_still(slug: str, key: str, request: Request, filename: str = Query(...), replace: bool = False,
                       db: Session = Depends(get_session)):
    """Save the request body (the image bytes) as <key>.<ext> in the project's stills folder. Never approves."""
    manifest_path = _manifest_path(db, slug)
    if key not in manual_stills.catalog(slug, manifest_path):
        raise HTTPException(status_code=404, detail=f"{key} is not a manual still of {slug}")
    try:
        result = still_store.upload(manifest_path, key, filename, await request.body(), replace=replace)
    except still_store.StillError as e:
        raise HTTPException(status_code=e.status, detail=str(e))
    _resync(db, slug)
    return result


@router.post("/projects/{slug}/stills/{key}/approve")
def approve_still(slug: str, key: str, body: NoteIn, db: Session = Depends(get_session)):
    """A person looked at the still: record its exact hash as approved (local, free)."""
    manifest_path = _manifest_path(db, slug)
    if key not in manual_stills.catalog(slug, manifest_path):
        raise HTTPException(status_code=404, detail=f"{key} is not a manual still of {slug}")
    try:
        result = still_store.approve(manifest_path, key, body.note)
    except still_store.StillError as e:
        raise HTTPException(status_code=e.status, detail=str(e))
    _resync(db, slug)
    return result


# --- spec-driven clips (Project #3 on) -------------------------------------------------------------

class BudgetIn(BaseModel):
    max_usd: float
    note: str


class SubmitIn(BaseModel):
    confirmed: bool = False


class ReviewIn(BaseModel):
    verdict: str  # accept | reject
    note: str = ""


def _spec(db: Session, slug: str):
    manifest_path = _manifest_path(db, slug)
    pdef = PROJECTS_BY_SLUG.get(slug)
    if pdef is None or not pdef.spec_driven:
        raise HTTPException(status_code=400, detail=f"{slug} is not a spec-driven project")
    try:
        return load_spec(manifest_path.parent / "project.json"), manifest_path
    except SpecError as e:
        raise HTTPException(status_code=409, detail=str(e))


@router.get("/projects/{slug}/clips/{key}")
def clip_plan(slug: str, key: str, db: Session = Depends(get_session)):
    spec, manifest_path = _spec(db, slug)
    return production_submit.plan(spec, manifest_path, key)


@router.post("/projects/{slug}/clips/{key}/budget")
def approve_clip_budget(slug: str, key: str, body: BudgetIn, db: Session = Depends(get_session)):
    """A person approves spending up to max_usd on ONE submission of this clip (no spend happens here)."""
    spec, manifest_path = _spec(db, slug)
    try:
        return production_budget.approve(manifest_path, spec, key, body.max_usd, body.note)
    except production_budget.BudgetError as e:
        raise HTTPException(status_code=e.status, detail=str(e))


@router.post("/projects/{slug}/clips/{key}/submit", status_code=202)
def submit_clip(slug: str, key: str, body: SubmitIn, db: Session = Depends(get_session)):
    """PAID (live mode only): one fal job for this clip, within its approval. Never retried automatically."""
    spec, manifest_path = _spec(db, slug)
    if not body.confirmed:
        return JSONResponse(status_code=400, content={"detail": "Confirm the paid submission.", "problems": []})
    try:
        entry = production_submit.submit(spec, manifest_path, key, execution_mode=execution_info()["mode"])
    except production_submit.SubmitError as e:
        return JSONResponse(status_code=e.status, content={"detail": str(e), "problems": e.problems})
    _resync(db, slug)
    return entry


@router.post("/projects/{slug}/clips/{key}/attempts/{attempt}/review")
def review_clip(slug: str, key: str, attempt: str, body: ReviewIn, db: Session = Depends(get_session)):
    spec, manifest_path = _spec(db, slug)
    try:
        result = production_submit.review(spec, manifest_path, key, attempt, body.verdict, body.note)
    except production_submit.SubmitError as e:
        raise HTTPException(status_code=e.status, detail=str(e))
    _resync(db, slug)
    return result


@router.post("/projects/{slug}/attempts/{key}/check")
def check_attempt_status(slug: str, key: str, db: Session = Depends(get_session)):
    """FREE: one status read of an already-submitted provider attempt, persisted to the manifest.

    Never submits, resubmits or retries a generation. Skipped while a runner is actively polling
    the same job (fresh heartbeat), and for attempts that already finished."""
    project = db.scalars(select(StudioProject).where(StudioProject.slug == slug)).first()
    if project is None or not project.source_path:
        raise HTTPException(status_code=404, detail=f"Studio project {slug} has no manifest")
    if "__attempt" not in key:
        raise HTTPException(status_code=400, detail="Only provider attempts (<stage>__attemptN) are checked here")
    manifest_path = Path(project.source_path)
    try:
        before = json.loads(manifest_path.read_text()).get(key) or {}
        skipped = not is_unfinished(before) or heartbeat_fresh(before)
        entry = check_attempt(manifest_path, key)
    except AttemptCheckError as e:
        raise HTTPException(status_code=409, detail=str(e))
    output = entry.get("raw_video_path")
    return {"key": key, "checked": not skipped, "phase": attempt_phase(entry, bool(output) and Path(output).is_file()),
            "provider_status": entry.get("provider_status"), "status_checked_at": entry.get("status_checked_at")}


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
