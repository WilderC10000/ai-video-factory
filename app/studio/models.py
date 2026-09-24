"""Studio tables (all prefixed studio_ so they never collide with the pipeline's own).

StudioProject   - one real FORMA production, mirrored from data/<slug>/manifest.json.
StudioStage     - one pipeline step (reference image, video shot, checkpoint edit, assembly).
StudioAgent     - one room's agent. v0.1 agents only report status; they never execute.
StudioEvent     - activity/warning log line, deduplicated by dedupe_key so re-imports are idempotent.
StudioApproval  - a human gate (the pipeline scripts' "have you reviewed X?" prompts), mirrored.
StudioBudget    - cap / spent / remaining per project, always recomputed from stage costs.
StudioJob       - one execution of a pipeline stage launched from the studio (job history).

Studio approval state (approvals, decisions, jobs) lives only here. Generated
outputs and their costs stay authoritative in the pipeline manifests, which the
importer mirrors in and never writes.
"""
import enum
import uuid
from datetime import datetime, timezone

from sqlalchemy import JSON, Boolean, DateTime, Enum, Float, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base


def _new_id() -> str:
    return uuid.uuid4().hex


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _enum(cls, length: int = 32):
    return Enum(cls, native_enum=False, length=length, values_callable=lambda e: [m.value for m in e])


class ProjectSource(str, enum.Enum):
    MANIFEST = "manifest"          # real FORMA production - the only kind shown by default
    DEV_FIXTURE = "dev_fixture"    # development/test data only, hidden unless explicitly requested


class StageKind(str, enum.Enum):
    IMAGE_GENERATE = "image_generate"
    VIDEO = "video"
    IMAGE_EDIT = "image_edit"      # construction checkpoint / jump-cut still
    ASSEMBLY = "assembly"          # local FFmpeg, no spend


class StageStatus(str, enum.Enum):
    PENDING = "pending"            # no manifest entry yet
    STARTED = "started"            # entry written but never completed: in flight or interrupted
    COMPLETE = "complete"
    FAILED = "failed"


class AgentStatus(str, enum.Enum):
    IDLE = "idle"
    WORKING = "working"
    WAITING_FOR_APPROVAL = "waiting_for_approval"
    BLOCKED = "blocked"
    FAILED = "failed"
    COMPLETE = "complete"


class Severity(str, enum.Enum):
    INFO = "info"
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class ApprovalStatus(str, enum.Enum):
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"


class StudioProject(Base):
    __tablename__ = "studio_projects"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_new_id)
    slug: Mapped[str] = mapped_column(String(64), unique=True)
    name: Mapped[str] = mapped_column(String(255))
    source: Mapped[ProjectSource] = mapped_column(_enum(ProjectSource), default=ProjectSource.MANIFEST)
    source_path: Mapped[str] = mapped_column(String(512))

    current_stage_key: Mapped[str | None] = mapped_column(String(64), nullable=True)
    production_stage: Mapped[str] = mapped_column(String(255), default="")
    is_active: Mapped[bool] = mapped_column(Boolean, default=False)

    manifest_sha256: Mapped[str | None] = mapped_column(String(64), nullable=True)
    last_imported_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, onupdate=_utcnow)

    stages: Mapped[list["StudioStage"]] = relationship(
        back_populates="project", cascade="all, delete-orphan", order_by="StudioStage.order"
    )
    budget: Mapped["StudioBudget | None"] = relationship(
        back_populates="project", cascade="all, delete-orphan", uselist=False
    )


class StudioStage(Base):
    __tablename__ = "studio_stages"
    __table_args__ = (UniqueConstraint("project_id", "key"),)

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_new_id)
    project_id: Mapped[str] = mapped_column(ForeignKey("studio_projects.id"), index=True)
    key: Mapped[str] = mapped_column(String(64))          # manifest key, e.g. "shot4"
    label: Mapped[str] = mapped_column(String(255))
    order: Mapped[int] = mapped_column(Integer)
    kind: Mapped[StageKind] = mapped_column(_enum(StageKind))
    room_id: Mapped[str] = mapped_column(String(64))
    script_path: Mapped[str | None] = mapped_column(String(255), nullable=True)
    status: Mapped[StageStatus] = mapped_column(_enum(StageStatus), default=StageStatus.PENDING)

    model: Mapped[str | None] = mapped_column(String(128), nullable=True)
    duration_seconds: Mapped[float | None] = mapped_column(Float, nullable=True)
    planned_cost_usd: Mapped[float | None] = mapped_column(Float, nullable=True)   # the script's hard cap
    estimated_cost_usd: Mapped[float | None] = mapped_column(Float, nullable=True)
    actual_cost_usd: Mapped[float | None] = mapped_column(Float, nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    provider_job_id: Mapped[str | None] = mapped_column(String(128), nullable=True)

    # The five references every stage can carry. All nullable: v0.1 fills what
    # the manifests actually record; real agents will fill the rest later.
    storyboard_checkpoint_path: Mapped[str | None] = mapped_column(String(512), nullable=True)
    previous_frame_path: Mapped[str | None] = mapped_column(String(512), nullable=True)
    previous_frame_exists: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    latest_output_path: Mapped[str | None] = mapped_column(String(512), nullable=True)
    latest_output_exists: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    approval_state: Mapped[ApprovalStatus | None] = mapped_column(_enum(ApprovalStatus), nullable=True)
    continuity_severity: Mapped[Severity | None] = mapped_column(_enum(Severity), nullable=True)
    continuity_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    build_logic_severity: Mapped[Severity | None] = mapped_column(_enum(Severity), nullable=True)
    build_logic_note: Mapped[str | None] = mapped_column(Text, nullable=True)

    requires_human_review: Mapped[bool] = mapped_column(Boolean, default=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, onupdate=_utcnow)

    project: Mapped[StudioProject] = relationship(back_populates="stages")


class StudioAgent(Base):
    __tablename__ = "studio_agents"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)  # == room_id; one agent per room in v0.1
    room_id: Mapped[str] = mapped_column(String(64), unique=True)
    name: Mapped[str] = mapped_column(String(128))
    role: Mapped[str] = mapped_column(String(255))
    status: Mapped[AgentStatus] = mapped_column(_enum(AgentStatus), default=AgentStatus.IDLE)
    status_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    current_task: Mapped[str | None] = mapped_column(Text, nullable=True)
    next_action: Mapped[str | None] = mapped_column(Text, nullable=True)
    requires_human_review: Mapped[bool] = mapped_column(Boolean, default=False)
    project_id: Mapped[str | None] = mapped_column(ForeignKey("studio_projects.id"), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, onupdate=_utcnow)


class StudioEvent(Base):
    __tablename__ = "studio_events"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_new_id)
    dedupe_key: Mapped[str] = mapped_column(String(255), unique=True)
    project_id: Mapped[str | None] = mapped_column(ForeignKey("studio_projects.id"), index=True, nullable=True)
    stage_id: Mapped[str | None] = mapped_column(ForeignKey("studio_stages.id"), nullable=True)
    room_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    agent_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    type: Mapped[str] = mapped_column(String(64))  # stage_completed, spend, warning, approval_requested, ...
    severity: Mapped[Severity] = mapped_column(_enum(Severity), default=Severity.INFO)
    message: Mapped[str] = mapped_column(Text)
    payload: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    requires_human_review: Mapped[bool] = mapped_column(Boolean, default=False)
    occurred_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)  # real pipeline time
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)


class StudioApproval(Base):
    __tablename__ = "studio_approvals"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_new_id)
    dedupe_key: Mapped[str] = mapped_column(String(255), unique=True)
    project_id: Mapped[str] = mapped_column(ForeignKey("studio_projects.id"), index=True)
    stage_id: Mapped[str | None] = mapped_column(ForeignKey("studio_stages.id"), nullable=True)
    room_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    title: Mapped[str] = mapped_column(String(255))
    detail: Mapped[str | None] = mapped_column(Text, nullable=True)
    estimated_cost_usd: Mapped[float | None] = mapped_column(Float, nullable=True)
    status: Mapped[ApprovalStatus] = mapped_column(_enum(ApprovalStatus), default=ApprovalStatus.PENDING)
    requires_human_review: Mapped[bool] = mapped_column(Boolean, default=True)
    # "pipeline" = inferred from manifest state; "studio" = decided in the studio UI.
    # The importer never overwrites a "studio" decision.
    decided_via: Mapped[str | None] = mapped_column(String(32), nullable=True)
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    # completed_at of the stage attempt this decision was about. A newer attempt
    # (e.g. after a retry) resets the gate to pending for the new output.
    output_completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, onupdate=_utcnow)


class StudioBudget(Base):
    __tablename__ = "studio_budgets"

    project_id: Mapped[str] = mapped_column(ForeignKey("studio_projects.id"), primary_key=True)
    cap_usd: Mapped[float | None] = mapped_column(Float, nullable=True)
    cap_source: Mapped[str | None] = mapped_column(String(255), nullable=True)
    spent_usd: Mapped[float] = mapped_column(Float, default=0.0)
    remaining_usd: Mapped[float | None] = mapped_column(Float, nullable=True)
    planned_remaining_spend_usd: Mapped[float] = mapped_column(Float, default=0.0)  # caps of stages not yet run
    over_cap: Mapped[bool] = mapped_column(Boolean, default=False)
    plan_exceeds_cap: Mapped[bool] = mapped_column(Boolean, default=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, onupdate=_utcnow)

    project: Mapped[StudioProject] = relationship(back_populates="budget")


class JobStatus(str, enum.Enum):
    QUEUED = "queued"                    # accepted by the studio, not started yet
    SUBMITTING = "submitting"            # sending the request to the provider
    PROVIDER_QUEUED = "provider_queued"  # provider accepted it and reports it queued
    GENERATING = "generating"            # provider reports it in progress
    DOWNLOADING = "downloading"          # fetching the finished output
    SYNCING = "syncing"                  # re-importing the manifest
    SUCCEEDED = "succeeded"
    FAILED = "failed"


ACTIVE_JOB_STATUSES = {JobStatus.QUEUED, JobStatus.SUBMITTING, JobStatus.PROVIDER_QUEUED,
                       JobStatus.GENERATING, JobStatus.DOWNLOADING, JobStatus.SYNCING}


class StudioJob(Base):
    __tablename__ = "studio_jobs"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_new_id)
    project_id: Mapped[str] = mapped_column(ForeignKey("studio_projects.id"), index=True)
    stage_key: Mapped[str] = mapped_column(String(64))
    mode: Mapped[str] = mapped_column(String(16))          # "continue" | "retry"
    action: Mapped[str] = mapped_column(String(32))        # "video" | "image_edit" | "assembly"
    script_path: Mapped[str | None] = mapped_column(String(255), nullable=True)
    execution_mode: Mapped[str] = mapped_column(String(16))  # "mock" | "live"
    is_paid: Mapped[bool] = mapped_column(Boolean, default=False)
    status: Mapped[JobStatus] = mapped_column(_enum(JobStatus), default=JobStatus.QUEUED)
    # Unique while the job is active (= project_id), NULL once finished: the database
    # itself refuses a second concurrent job for the same project.
    active_lock: Mapped[str | None] = mapped_column(String(64), unique=True, nullable=True)
    request_id: Mapped[str] = mapped_column(String(64), unique=True)  # client idempotency key

    expected_cost_usd: Mapped[float | None] = mapped_column(Float, nullable=True)
    actual_cost_usd: Mapped[float | None] = mapped_column(Float, nullable=True)
    provider_job_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    output_paths: Mapped[list | None] = mapped_column(JSON, nullable=True)
    log: Mapped[str] = mapped_column(Text, default="")
    error: Mapped[str | None] = mapped_column(Text, nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    phase_changed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
