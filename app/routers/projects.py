from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.db import get_session
from app.models.project import Project, Shot
from app.models.video_job import VideoJob
from app.providers.llm.mock import MockLLMProvider
from app.providers.video.mock import MockVideoProvider
from app.schemas.project import ProjectCreateRequest, ProjectDetailOut, ProjectSummaryOut, VideoJobOut
from app.services import project_service, video_job_service
from app.services.errors import (
    FactoryPausedError,
    InvalidJobStateError,
    InvalidShotStateError,
    InvalidTransitionError,
    MaxRegenerationsExceededError,
    SpendLimitExceededError,
)

router = APIRouter(prefix="/projects", tags=["projects"])

# Milestone 1/2: only mock providers exist. Later these will be chosen by
# config (which LLM/video provider is active) instead of hard-coded here.
_llm_provider = MockLLMProvider()
_video_provider = MockVideoProvider()


def _get_project_or_404(db: Session, project_id: str) -> Project:
    project = db.get(Project, project_id)
    if project is None:
        raise HTTPException(status_code=404, detail=f"Project {project_id} not found")
    return project


def _get_shot_or_404(db: Session, project_id: str, shot_id: str) -> Shot:
    shot = db.get(Shot, shot_id)
    if shot is None or shot.project_id != project_id:
        raise HTTPException(status_code=404, detail=f"Shot {shot_id} not found in project {project_id}")
    return shot


def _get_job_or_404(db: Session, project_id: str, shot_id: str, job_id: str) -> VideoJob:
    job = db.get(VideoJob, job_id)
    if job is None or job.shot_id != shot_id or job.project_id != project_id:
        raise HTTPException(status_code=404, detail=f"Video job {job_id} not found")
    return job


@router.post("", response_model=ProjectSummaryOut, status_code=201)
def create_project(payload: ProjectCreateRequest, db: Session = Depends(get_session)):
    if not payload.idea_text.strip():
        raise HTTPException(status_code=422, detail="idea_text must not be empty")
    return project_service.create_project(db, payload.idea_text)


@router.get("", response_model=list[ProjectSummaryOut])
def list_projects(db: Session = Depends(get_session)):
    return db.query(Project).order_by(Project.created_at.desc()).all()


@router.get("/{project_id}", response_model=ProjectDetailOut)
def get_project(project_id: str, db: Session = Depends(get_session)):
    return _get_project_or_404(db, project_id)


def _run_transition(db: Session, project_id: str, step):
    project = _get_project_or_404(db, project_id)
    try:
        return step(db, project, _llm_provider)
    except InvalidTransitionError as e:
        raise HTTPException(status_code=409, detail=str(e))
    except FactoryPausedError as e:
        raise HTTPException(status_code=423, detail=str(e))


@router.post("/{project_id}/concept", response_model=ProjectDetailOut)
def advance_to_concept(project_id: str, db: Session = Depends(get_session)):
    return _run_transition(db, project_id, project_service.advance_to_concept)


@router.post("/{project_id}/script", response_model=ProjectDetailOut)
def advance_to_script(project_id: str, db: Session = Depends(get_session)):
    return _run_transition(db, project_id, project_service.advance_to_script)


@router.post("/{project_id}/storyboard", response_model=ProjectDetailOut)
def advance_to_storyboard(project_id: str, db: Session = Depends(get_session)):
    return _run_transition(db, project_id, project_service.advance_to_storyboard)


@router.post("/{project_id}/shots/{shot_id}/generate", response_model=VideoJobOut)
def generate_shot(project_id: str, shot_id: str, db: Session = Depends(get_session)):
    shot = _get_shot_or_404(db, project_id, shot_id)
    try:
        return video_job_service.submit_shot_video_job(db, shot, _video_provider)
    except InvalidShotStateError as e:
        raise HTTPException(status_code=409, detail=str(e))
    except FactoryPausedError as e:
        raise HTTPException(status_code=423, detail=str(e))
    except SpendLimitExceededError as e:
        raise HTTPException(status_code=402, detail=str(e))


@router.post("/{project_id}/shots/{shot_id}/jobs/{job_id}/poll", response_model=VideoJobOut)
def poll_shot_job(project_id: str, shot_id: str, job_id: str, db: Session = Depends(get_session)):
    job = _get_job_or_404(db, project_id, shot_id, job_id)
    try:
        return video_job_service.poll_shot_video_job(db, job, _video_provider)
    except InvalidJobStateError as e:
        raise HTTPException(status_code=409, detail=str(e))


@router.post("/{project_id}/shots/{shot_id}/regenerate", response_model=VideoJobOut)
def regenerate_shot(project_id: str, shot_id: str, db: Session = Depends(get_session)):
    shot = _get_shot_or_404(db, project_id, shot_id)
    try:
        return video_job_service.regenerate_shot_video(db, shot, _video_provider)
    except InvalidShotStateError as e:
        raise HTTPException(status_code=409, detail=str(e))
    except MaxRegenerationsExceededError as e:
        raise HTTPException(status_code=429, detail=str(e))
    except FactoryPausedError as e:
        raise HTTPException(status_code=423, detail=str(e))
    except SpendLimitExceededError as e:
        raise HTTPException(status_code=402, detail=str(e))
