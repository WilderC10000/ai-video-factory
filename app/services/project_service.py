"""Business logic for moving a project through its pipeline. This is the ONLY
place that should mutate Project/Shot state or write CostRecords - the API
routers and CLI scripts are thin wrappers around these functions.

Each function does one state transition (IDEA -> CONCEPT_APPROVED -> ...).
That mirrors how this will work later: a human or an automated queue will
trigger these one at a time, and any of them can be re-run on failure without
restarting the whole project.
"""
from sqlalchemy.orm import Session

from app.config import settings
from app.models.project import CostRecord, OperationType, Project, ProjectStatus, Shot, ShotStatus
from app.providers.base import LLMProvider


class FactoryPausedError(Exception):
    """Raised when generation is attempted while the global pause flag is on."""


class InvalidTransitionError(Exception):
    """Raised when a project isn't in the right status for the requested step."""


def _require_status(project: Project, expected: ProjectStatus) -> None:
    if project.status != expected:
        raise InvalidTransitionError(
            f"Project {project.id} is in status {project.status}, expected {expected}."
        )


def _check_not_paused() -> None:
    if settings.factory_paused:
        raise FactoryPausedError("The factory is globally paused (FACTORY_PAUSED=true). No generation will run.")


def _record_cost(
    db: Session,
    project: Project,
    operation_type: OperationType,
    provider_name: str,
    cost_usd: float,
    description: str | None = None,
    shot_id: str | None = None,
    meta: dict | None = None,
) -> CostRecord:
    record = CostRecord(
        project_id=project.id,
        shot_id=shot_id,
        operation_type=operation_type,
        provider_name=provider_name,
        description=description,
        cost_usd=cost_usd,
        meta=meta or {},
    )
    db.add(record)
    return record


def build_shot_prompt(continuity_bible: dict, shot_description: str) -> str:
    """Combine the continuity bible with a shot's own beat description into the
    full text prompt that would be sent to a video generation provider. Keeping
    this in one function means every shot - now and after regeneration - inherits
    the same subject/location/style, instead of continuity logic being duplicated
    across the codebase."""
    lines = [
        f"Subject: {continuity_bible.get('main_subject', '')}",
        f"Location: {continuity_bible.get('location', '')}",
        f"Characters: {continuity_bible.get('characters', '')}",
        f"Materials/colors: {continuity_bible.get('materials_and_colors', '')}",
        f"Time of day: {continuity_bible.get('time_of_day', '')}",
        f"Weather: {continuity_bible.get('weather', '')}",
        f"Camera style: {continuity_bible.get('camera_style', '')}",
        f"Architecture style: {continuity_bible.get('architecture_style', '')}",
        f"Current construction state: {continuity_bible.get('current_construction_state', '')}",
        "",
        f"Shot: {shot_description}",
    ]
    return "\n".join(lines)


def create_project(db: Session, idea_text: str) -> Project:
    project = Project(idea_text=idea_text.strip(), status=ProjectStatus.IDEA)
    db.add(project)
    db.commit()
    db.refresh(project)
    return project


def advance_to_concept(db: Session, project: Project, llm: LLMProvider) -> Project:
    _require_status(project, ProjectStatus.IDEA)
    _check_not_paused()

    result = llm.generate_concept(project.idea_text)

    project.title = result.title
    project.concept = result.concept
    project.continuity_bible = result.continuity_bible
    project.status = ProjectStatus.CONCEPT_APPROVED

    _record_cost(
        db, project, OperationType.LLM, result.provider_name, result.cost_usd,
        description="generate_concept", meta=result.meta,
    )
    db.commit()
    db.refresh(project)
    return project


def advance_to_script(db: Session, project: Project, llm: LLMProvider) -> Project:
    _require_status(project, ProjectStatus.CONCEPT_APPROVED)
    _check_not_paused()

    result = llm.generate_script(project.concept, project.continuity_bible or {})

    project.script = result.script
    project.status = ProjectStatus.SCRIPT_READY

    _record_cost(
        db, project, OperationType.LLM, result.provider_name, result.cost_usd,
        description="generate_script", meta=result.meta,
    )
    db.commit()
    db.refresh(project)
    return project


def advance_to_storyboard(db: Session, project: Project, llm: LLMProvider) -> Project:
    _require_status(project, ProjectStatus.SCRIPT_READY)
    _check_not_paused()

    result = llm.generate_storyboard(project.concept, project.script or {}, project.continuity_bible or {})

    continuity_bible = project.continuity_bible or {}
    for shot_plan in result.shots:
        shot = Shot(
            project_id=project.id,
            shot_number=shot_plan.shot_number,
            description=shot_plan.description,
            prompt=build_shot_prompt(continuity_bible, shot_plan.description),
            target_duration_seconds=shot_plan.target_duration_seconds,
            status=ShotStatus.PROMPT_READY,
        )
        db.add(shot)

    project.status = ProjectStatus.STORYBOARD_READY

    _record_cost(
        db, project, OperationType.LLM, result.provider_name, result.cost_usd,
        description="generate_storyboard", meta=result.meta,
    )
    db.commit()
    db.refresh(project)
    return project
