from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.db import get_session
from app.models.project import Project
from app.providers.llm.mock import MockLLMProvider
from app.schemas.project import ProjectCreateRequest, ProjectDetailOut, ProjectSummaryOut
from app.services import project_service
from app.services.project_service import FactoryPausedError, InvalidTransitionError

router = APIRouter(prefix="/projects", tags=["projects"])

# Milestone 1: only a mock provider exists. Later this will be chosen by config
# (e.g. which LLM provider is active) instead of hard-coded here.
_llm_provider = MockLLMProvider()


def _get_project_or_404(db: Session, project_id: str) -> Project:
    project = db.get(Project, project_id)
    if project is None:
        raise HTTPException(status_code=404, detail=f"Project {project_id} not found")
    return project


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
