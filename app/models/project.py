"""Database tables for the video factory.

Project      - one video-in-progress, with its concept/script/continuity bible and status.
Shot         - one individual generated clip belonging to a project; has its own status
               so a single failed shot can be regenerated without restarting the project.
CostRecord   - one line item every time a provider (LLM/image/video/voice) does work,
               even if the cost is $0.00 (mock providers). This is how per-project and
               daily spend get tracked and, later, enforced.
"""
import enum
import uuid
from datetime import datetime, timezone

from sqlalchemy import JSON, DateTime, Enum, Float, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base


def _new_id() -> str:
    return uuid.uuid4().hex


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class ProjectStatus(str, enum.Enum):
    IDEA = "IDEA"
    CONCEPT_APPROVED = "CONCEPT_APPROVED"
    SCRIPT_READY = "SCRIPT_READY"
    STORYBOARD_READY = "STORYBOARD_READY"
    KEYFRAMES_READY = "KEYFRAMES_READY"
    VIDEO_RENDERING = "VIDEO_RENDERING"
    VIDEO_QA = "VIDEO_QA"
    VOICE_READY = "VOICE_READY"
    EDITING = "EDITING"
    FINAL_QA = "FINAL_QA"
    READY_FOR_REVIEW = "READY_FOR_REVIEW"
    APPROVED = "APPROVED"
    PUBLISHED = "PUBLISHED"
    FAILED = "FAILED"


class ShotStatus(str, enum.Enum):
    PENDING = "PENDING"          # planned, prompt not built yet
    PROMPT_READY = "PROMPT_READY"  # prompt built, ready to send to a video provider
    GENERATING = "GENERATING"     # sent to provider, awaiting result
    GENERATED = "GENERATED"       # clip file exists, not yet QA'd
    QA_PASSED = "QA_PASSED"
    QA_FAILED = "QA_FAILED"
    FAILED = "FAILED"             # provider error / exhausted retries


class OperationType(str, enum.Enum):
    LLM = "LLM"
    IMAGE = "IMAGE"
    VIDEO = "VIDEO"
    VOICE = "VOICE"


class Project(Base):
    __tablename__ = "projects"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_new_id)
    idea_text: Mapped[str] = mapped_column(Text)
    title: Mapped[str | None] = mapped_column(String(255), nullable=True)
    concept: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Structured script, e.g. {"hook": "...", "beats": [{"narration": "...", "shot_ref": 1}, ...]}
    script: Mapped[dict | None] = mapped_column(JSON, nullable=True)

    # The continuity bible: everything that must stay visually consistent across shots.
    # e.g. main_subject, location, characters, materials_and_colors, time_of_day,
    # weather, camera_style, current_state
    continuity_bible: Mapped[dict | None] = mapped_column(JSON, nullable=True)

    status: Mapped[ProjectStatus] = mapped_column(
        Enum(ProjectStatus, native_enum=False, length=32), default=ProjectStatus.IDEA
    )
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, onupdate=_utcnow
    )

    shots: Mapped[list["Shot"]] = relationship(
        back_populates="project", cascade="all, delete-orphan", order_by="Shot.shot_number"
    )
    cost_records: Mapped[list["CostRecord"]] = relationship(
        back_populates="project", cascade="all, delete-orphan"
    )

    @property
    def total_cost_usd(self) -> float:
        return round(sum(c.cost_usd for c in self.cost_records), 4)


class Shot(Base):
    __tablename__ = "shots"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_new_id)
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id"), index=True)
    shot_number: Mapped[int] = mapped_column()

    # Short beat description from the storyboard, e.g. "Excavator digs a large pit
    # in the backyard, jet fuselage visible nearby waiting to be lowered in."
    description: Mapped[str] = mapped_column(Text)

    # Full generation prompt = continuity bible + this shot's description, built by
    # the service layer so every shot inherits the same subject/location/style.
    prompt: Mapped[str | None] = mapped_column(Text, nullable=True)

    target_duration_seconds: Mapped[float] = mapped_column(Float, default=5.0)

    status: Mapped[ShotStatus] = mapped_column(
        Enum(ShotStatus, native_enum=False, length=32), default=ShotStatus.PENDING
    )
    video_provider: Mapped[str | None] = mapped_column(String(64), nullable=True)
    video_file_path: Mapped[str | None] = mapped_column(String(512), nullable=True)
    qa_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    regeneration_count: Mapped[int] = mapped_column(default=0)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, onupdate=_utcnow
    )

    project: Mapped[Project] = relationship(back_populates="shots")
    video_jobs: Mapped[list["VideoJob"]] = relationship(  # noqa: F821
        back_populates="shot", cascade="all, delete-orphan", order_by="VideoJob.created_at"
    )


class CostRecord(Base):
    __tablename__ = "cost_records"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_new_id)
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id"), index=True)
    shot_id: Mapped[str | None] = mapped_column(ForeignKey("shots.id"), nullable=True)

    operation_type: Mapped[OperationType] = mapped_column(
        Enum(OperationType, native_enum=False, length=16)
    )
    provider_name: Mapped[str] = mapped_column(String(64))
    description: Mapped[str | None] = mapped_column(String(255), nullable=True)
    cost_usd: Mapped[float] = mapped_column(Float, default=0.0)
    meta: Mapped[dict | None] = mapped_column(JSON, nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)

    project: Mapped[Project] = relationship(back_populates="cost_records")
