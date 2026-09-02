"""Business logic for generating one shot's video clip through a VideoProvider.

Mirrors project_service.py's shape: this is the only place that should create
VideoJob rows, move a Shot between GENERATING/GENERATED/FAILED, or write
CostRecords for video generation. Routers/scripts call these functions rather
than talking to providers or the database directly.

Flow: submit_shot_video_job() kicks a job off (checked against the pause flag
and the project's spend limit before any provider call happens), then
poll_shot_video_job() is called repeatedly (by a script, a background worker,
or a dashboard "refresh" button) until the job reaches a terminal state.
regenerate_shot_video() re-runs a failed shot as a brand new job, up to
max_regenerations_per_shot times.
"""
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy.orm import Session

from app.config import settings
from app.models.project import CostRecord, OperationType, Shot, ShotStatus
from app.models.video_job import VideoJob, VideoJobStatus
from app.providers.base import ProviderJobState, VideoGenerationRequest, VideoProvider, VideoProviderError
from app.services.errors import (
    FactoryPausedError,
    InvalidJobStateError,
    InvalidShotStateError,
    MaxRegenerationsExceededError,
    SpendLimitExceededError,
)

__all__ = [
    "FactoryPausedError",
    "InvalidJobStateError",
    "InvalidShotStateError",
    "MaxRegenerationsExceededError",
    "SpendLimitExceededError",
    "submit_shot_video_job",
    "poll_shot_video_job",
    "regenerate_shot_video",
]

_TERMINAL_JOB_STATUSES = {VideoJobStatus.COMPLETED, VideoJobStatus.FAILED, VideoJobStatus.TIMED_OUT}


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _as_utc(dt: datetime) -> datetime:
    """SQLite drops tzinfo on round-trip even for DateTime(timezone=True)
    columns, so a datetime read back from the database comes back naive. We
    only ever write UTC values (via _utcnow()), so it's safe to reattach the
    UTC tzinfo before doing arithmetic against a fresh timezone-aware value."""
    return dt if dt.tzinfo is not None else dt.replace(tzinfo=timezone.utc)


def _check_not_paused() -> None:
    if settings.factory_paused:
        raise FactoryPausedError("The factory is globally paused (FACTORY_PAUSED=true). No generation will run.")


def _output_path_for_shot(shot: Shot) -> Path:
    return settings.project_data_path / shot.project_id / "shots" / f"{shot.id}.mp4"


def _record_cost(db: Session, shot: Shot, job: VideoJob, cost_usd: float) -> CostRecord:
    record = CostRecord(
        project_id=shot.project_id,
        shot_id=shot.id,
        operation_type=OperationType.VIDEO,
        provider_name=job.provider_name,
        description=f"generate_video (job {job.id})",
        cost_usd=cost_usd,
        meta={"video_job_id": job.id},
    )
    db.add(record)
    return record


def submit_shot_video_job(
    db: Session,
    shot: Shot,
    video_provider: VideoProvider,
    reference_image_path: str | None = None,
    extra_params: dict | None = None,
) -> VideoJob:
    """Submit a new generation job for a shot that's ready to be rendered
    (status PROMPT_READY). Enforces the pause flag and the per-project spend
    limit BEFORE calling the provider, so a paused factory or an over-budget
    project never spends anything, real or simulated.

    If `reference_image_path` isn't given explicitly, falls back to the
    shot's own `reference_image_path` (set by image_job_service) if one was
    generated earlier - this is what turns generation into image-to-video
    automatically once a shot has a reference image, without every caller
    needing to know about it. Pass an explicit path (or one is generated
    fresh) to override; a shot with no reference image at all falls back to
    plain text-to-video.

    `extra_params` is passed straight through to the provider (e.g. the mock
    provider's `mock_behavior` switch for testing, or a real provider's
    vendor-specific knobs) - see VideoGenerationRequest.extra_params.
    """
    if shot.status != ShotStatus.PROMPT_READY:
        raise InvalidShotStateError(
            f"Shot {shot.id} is in status {shot.status}, expected {ShotStatus.PROMPT_READY}."
        )
    _check_not_paused()

    reference_image_path = reference_image_path or shot.reference_image_path

    request = VideoGenerationRequest(
        prompt=shot.prompt or shot.description,
        reference_image_path=reference_image_path,
        duration_seconds=shot.target_duration_seconds,
        extra_params=extra_params or {},
    )
    estimated_cost = video_provider.estimate_cost(request)

    projected_total = shot.project.total_cost_usd + estimated_cost
    if projected_total > settings.max_spend_per_project_usd:
        raise SpendLimitExceededError(
            f"Submitting this job would bring project {shot.project_id}'s total cost to "
            f"${projected_total:.2f}, exceeding its ${settings.max_spend_per_project_usd:.2f} limit."
        )

    job = VideoJob(
        shot_id=shot.id,
        project_id=shot.project_id,
        provider_name=video_provider.name,
        prompt=request.prompt,
        reference_image_path=reference_image_path,
        status=VideoJobStatus.PENDING,
        estimated_cost_usd=estimated_cost,
        started_at=_utcnow(),
    )
    db.add(job)

    try:
        submitted = video_provider.submit_video_job(request)
    except VideoProviderError as e:
        job.status = VideoJobStatus.FAILED
        job.error_message = str(e)
        job.completed_at = _utcnow()
        shot.status = ShotStatus.FAILED
        db.commit()
        db.refresh(job)
        return job

    job.provider_job_id = submitted.provider_job_id
    job.estimated_cost_usd = submitted.estimated_cost_usd
    job.status = VideoJobStatus.PROCESSING
    job.meta = submitted.meta
    shot.status = ShotStatus.GENERATING

    db.commit()
    db.refresh(job)
    return job


def poll_shot_video_job(db: Session, job: VideoJob, video_provider: VideoProvider) -> VideoJob:
    """Check on a previously submitted job and advance its state. Safe to call
    repeatedly - a job still in PROCESSING just comes back unchanged until the
    provider reports something new, times out, or exhausts its retry budget."""
    if job.status in _TERMINAL_JOB_STATUSES:
        raise InvalidJobStateError(f"Video job {job.id} is already in terminal status {job.status}.")

    shot = job.shot

    if job.started_at is not None:
        elapsed = (_utcnow() - _as_utc(job.started_at)).total_seconds()
        if elapsed > settings.video_job_timeout_seconds:
            job.status = VideoJobStatus.TIMED_OUT
            job.error_message = f"Timed out after {elapsed:.0f}s waiting for provider {job.provider_name}."
            job.completed_at = _utcnow()
            shot.status = ShotStatus.FAILED
            db.commit()
            db.refresh(job)
            return job

    try:
        result = video_provider.get_job_status(job.provider_job_id, meta=job.meta)
    except VideoProviderError as e:
        job.retry_count += 1
        if job.retry_count > settings.max_job_poll_retries:
            job.status = VideoJobStatus.FAILED
            job.error_message = f"Gave up after {job.retry_count} retries: {e}"
            job.completed_at = _utcnow()
            shot.status = ShotStatus.FAILED
        # else: leave status as-is (still PENDING/PROCESSING) so the caller polls again later.
        db.commit()
        db.refresh(job)
        return job

    if result.status == ProviderJobState.PROCESSING:
        job.status = VideoJobStatus.PROCESSING
        db.commit()
        db.refresh(job)
        return job

    if result.status == ProviderJobState.FAILED:
        job.status = VideoJobStatus.FAILED
        job.error_message = result.error_message or "Provider reported generation failure."
        job.completed_at = _utcnow()
        shot.status = ShotStatus.FAILED
        db.commit()
        db.refresh(job)
        return job

    # COMPLETED: download the clip and update the shot.
    destination = _output_path_for_shot(shot)
    try:
        local_path = video_provider.download_result(job.provider_job_id, result.output_url, str(destination))
    except VideoProviderError as e:
        job.status = VideoJobStatus.FAILED
        job.error_message = f"Download failed: {e}"
        job.completed_at = _utcnow()
        shot.status = ShotStatus.FAILED
        db.commit()
        db.refresh(job)
        return job

    actual_cost = result.actual_cost_usd if result.actual_cost_usd is not None else job.estimated_cost_usd

    job.status = VideoJobStatus.COMPLETED
    job.output_file_path = local_path
    job.actual_cost_usd = actual_cost
    job.completed_at = _utcnow()

    shot.video_provider = job.provider_name
    shot.video_file_path = local_path
    shot.status = ShotStatus.GENERATED

    _record_cost(db, shot, job, actual_cost or 0.0)

    db.commit()
    db.refresh(job)
    return job


def regenerate_shot_video(db: Session, shot: Shot, video_provider: VideoProvider) -> VideoJob:
    """Re-run a failed (or QA-rejected) shot as a brand new job. This is the
    'regenerate shot 8' path from the project spec: it does not touch any
    other shot, and it's capped by max_regenerations_per_shot so a stuck shot
    can't retry itself into unlimited spend."""
    if shot.status not in (ShotStatus.FAILED, ShotStatus.QA_FAILED):
        raise InvalidShotStateError(
            f"Shot {shot.id} is in status {shot.status}; only FAILED or QA_FAILED shots can be regenerated."
        )
    if shot.regeneration_count >= settings.max_regenerations_per_shot:
        raise MaxRegenerationsExceededError(
            f"Shot {shot.id} has already been regenerated "
            f"{shot.regeneration_count} times (max {settings.max_regenerations_per_shot})."
        )

    shot.regeneration_count += 1
    shot.status = ShotStatus.PROMPT_READY
    shot.error_message = None
    db.commit()
    db.refresh(shot)

    return submit_shot_video_job(db, shot, video_provider)
