"""VideoJob: one attempt at generating one shot's clip through a VideoProvider.

A Shot can have multiple VideoJob rows over its lifetime (one per submission
attempt / regeneration) - this is the audit trail of "what did we actually
send to the provider, what did it cost, and what came back," which is exactly
what later cost-reporting and QA-regeneration features need.
"""
import enum
import uuid
from datetime import datetime, timezone

from sqlalchemy import JSON, DateTime, Enum, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base


def _new_id() -> str:
    return uuid.uuid4().hex


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class VideoJobStatus(str, enum.Enum):
    PENDING = "PENDING"        # created locally, not yet submitted to the provider
    PROCESSING = "PROCESSING"  # provider accepted it and is working on it
    COMPLETED = "COMPLETED"    # clip downloaded successfully
    FAILED = "FAILED"          # provider reported failure, or retries exhausted
    TIMED_OUT = "TIMED_OUT"    # gave up waiting after video_job_timeout_seconds


class VideoJob(Base):
    __tablename__ = "video_jobs"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_new_id)
    shot_id: Mapped[str] = mapped_column(ForeignKey("shots.id"), index=True)
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id"), index=True)

    provider_name: Mapped[str] = mapped_column(String(64))
    provider_job_id: Mapped[str | None] = mapped_column(String(128), nullable=True)

    prompt: Mapped[str] = mapped_column(Text)
    reference_image_path: Mapped[str | None] = mapped_column(String(512), nullable=True)

    status: Mapped[VideoJobStatus] = mapped_column(
        Enum(VideoJobStatus, native_enum=False, length=16), default=VideoJobStatus.PENDING
    )

    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    output_file_path: Mapped[str | None] = mapped_column(String(512), nullable=True)
    estimated_cost_usd: Mapped[float | None] = mapped_column(Float, nullable=True)
    actual_cost_usd: Mapped[float | None] = mapped_column(Float, nullable=True)

    retry_count: Mapped[int] = mapped_column(Integer, default=0)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Raw provider-specific metadata (job parameters echoed back, model version, etc.)
    meta: Mapped[dict | None] = mapped_column(JSON, nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, onupdate=_utcnow
    )

    shot: Mapped["Shot"] = relationship(back_populates="video_jobs")  # noqa: F821
