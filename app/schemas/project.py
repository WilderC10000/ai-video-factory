"""Pydantic models = the shape of data going in/out of the HTTP API. Kept separate
from the SQLAlchemy models so the API contract can evolve independently of storage."""
from datetime import datetime

from pydantic import BaseModel, ConfigDict

from app.models.project import OperationType, ProjectStatus, ShotStatus


class ProjectCreateRequest(BaseModel):
    idea_text: str


class ShotOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    shot_number: int
    description: str
    prompt: str | None
    target_duration_seconds: float
    status: ShotStatus
    video_provider: str | None
    video_file_path: str | None
    qa_score: float | None
    error_message: str | None
    regeneration_count: int


class CostRecordOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    shot_id: str | None
    operation_type: OperationType
    provider_name: str
    description: str | None
    cost_usd: float
    created_at: datetime


class ProjectSummaryOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    title: str | None
    idea_text: str
    status: ProjectStatus
    created_at: datetime
    updated_at: datetime


class ProjectDetailOut(ProjectSummaryOut):
    concept: str | None
    script: dict | None
    continuity_bible: dict | None
    error_message: str | None
    shots: list[ShotOut]
    cost_records: list[CostRecordOut]
    total_cost_usd: float
