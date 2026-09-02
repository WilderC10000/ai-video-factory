from datetime import timedelta

import pytest

from app.config import settings
from app.models.project import ShotStatus
from app.models.video_job import VideoJobStatus
from app.providers.video.mock import WAN_STANDARD_PRICING, MockVideoProvider
from app.services import video_job_service
from app.services.errors import (
    FactoryPausedError,
    InvalidJobStateError,
    InvalidShotStateError,
    MaxRegenerationsExceededError,
    SpendLimitExceededError,
)
from app.services.video_job_service import _utcnow


@pytest.fixture()
def video(tmp_path, monkeypatch):
    # Default pricing (Wan Turbo, flat $0.05/video @480p) - our current
    # cheapest-credible real candidate, so most tests exercise real numbers.
    return MockVideoProvider()


def _poll_until_terminal(db_session, job, video_provider, max_polls=10):
    polls = 0
    terminal = {VideoJobStatus.COMPLETED, VideoJobStatus.FAILED, VideoJobStatus.TIMED_OUT}
    while job.status not in terminal and polls < max_polls:
        job = video_job_service.poll_shot_video_job(db_session, job, video_provider)
        polls += 1
    return job


# ---------------------------------------------------------------------------
# Successful generation
# ---------------------------------------------------------------------------


def test_successful_generation(db_session, ready_shot, video):
    job = video_job_service.submit_shot_video_job(db_session, ready_shot, video)
    assert job.status == VideoJobStatus.PROCESSING
    assert job.provider_job_id is not None
    assert job.estimated_cost_usd == pytest.approx(0.05)  # Wan Turbo flat price @480p
    assert ready_shot.status == ShotStatus.GENERATING

    job = _poll_until_terminal(db_session, job, video)

    assert job.status == VideoJobStatus.COMPLETED
    assert job.actual_cost_usd == pytest.approx(0.05)
    assert job.output_file_path is not None
    assert job.completed_at is not None

    assert ready_shot.status == ShotStatus.GENERATED
    assert ready_shot.video_provider == "mock-video"
    assert ready_shot.video_file_path == job.output_file_path

    from pathlib import Path

    clip = Path(job.output_file_path)
    assert clip.exists()
    assert clip.stat().st_size > 0

    project = ready_shot.project
    db_session.refresh(project)
    assert project.total_cost_usd == pytest.approx(0.05)
    video_costs = [c for c in project.cost_records if c.shot_id == ready_shot.id]
    assert len(video_costs) == 1
    assert video_costs[0].cost_usd == pytest.approx(0.05)


def test_standard_pricing_scales_with_duration(db_session, ready_shot):
    # Confirms the per-second billing path (kept available for a premium
    # upgrade later) still works alongside Turbo's flat pricing.
    standard = MockVideoProvider(pricing=WAN_STANDARD_PRICING)
    job = video_job_service.submit_shot_video_job(db_session, ready_shot, standard)
    assert job.estimated_cost_usd == pytest.approx(0.20)  # 5s * $0.04/s @480p


# ---------------------------------------------------------------------------
# Failed generation
# ---------------------------------------------------------------------------


def test_failed_generation_reported_by_provider(db_session, ready_shot, video):
    job = video_job_service.submit_shot_video_job(
        db_session, ready_shot, video, extra_params={"mock_behavior": "fail"}
    )
    job = video_job_service.poll_shot_video_job(db_session, job, video)

    assert job.status == VideoJobStatus.FAILED
    assert job.error_message
    assert ready_shot.status == ShotStatus.FAILED
    assert ready_shot.video_file_path is None


def test_failed_generation_rejected_at_submission(db_session, ready_shot, video):
    job = video_job_service.submit_shot_video_job(
        db_session, ready_shot, video, extra_params={"mock_behavior": "submit_fail"}
    )

    assert job.status == VideoJobStatus.FAILED
    assert job.provider_job_id is None
    assert job.error_message
    assert ready_shot.status == ShotStatus.FAILED


# ---------------------------------------------------------------------------
# Timeout
# ---------------------------------------------------------------------------


def test_job_times_out_if_stuck_processing_too_long(db_session, ready_shot, video):
    job = video_job_service.submit_shot_video_job(
        db_session, ready_shot, video, extra_params={"mock_behavior": "timeout"}
    )
    assert job.status == VideoJobStatus.PROCESSING

    # Simulate a lot of wall-clock time having passed without needing to sleep.
    job.started_at = _utcnow() - timedelta(seconds=settings.video_job_timeout_seconds + 10)
    db_session.commit()

    job = video_job_service.poll_shot_video_job(db_session, job, video)

    assert job.status == VideoJobStatus.TIMED_OUT
    assert "Timed out" in job.error_message
    assert ready_shot.status == ShotStatus.FAILED


# ---------------------------------------------------------------------------
# Retry (transient provider errors during polling)
# ---------------------------------------------------------------------------


def test_transient_errors_are_retried_then_succeed(db_session, ready_shot, video):
    job = video_job_service.submit_shot_video_job(
        db_session,
        ready_shot,
        video,
        extra_params={"mock_behavior": "flaky_then_success", "flaky_failures": 2, "polls_until_complete": 1},
    )

    job = video_job_service.poll_shot_video_job(db_session, job, video)
    assert job.status == VideoJobStatus.PROCESSING
    assert job.retry_count == 1

    job = video_job_service.poll_shot_video_job(db_session, job, video)
    assert job.status == VideoJobStatus.PROCESSING
    assert job.retry_count == 2

    job = video_job_service.poll_shot_video_job(db_session, job, video)
    assert job.status == VideoJobStatus.COMPLETED
    assert ready_shot.status == ShotStatus.GENERATED


def test_transient_errors_exceeding_max_retries_fail_the_job(db_session, ready_shot, video):
    job = video_job_service.submit_shot_video_job(
        db_session,
        ready_shot,
        video,
        extra_params={"mock_behavior": "flaky_then_success", "flaky_failures": 99},
    )

    for _ in range(settings.max_job_poll_retries):
        job = video_job_service.poll_shot_video_job(db_session, job, video)
        assert job.status == VideoJobStatus.PROCESSING

    job = video_job_service.poll_shot_video_job(db_session, job, video)
    assert job.status == VideoJobStatus.FAILED
    assert job.retry_count == settings.max_job_poll_retries + 1
    assert ready_shot.status == ShotStatus.FAILED


# ---------------------------------------------------------------------------
# Invalid state
# ---------------------------------------------------------------------------


def test_cannot_submit_job_for_shot_not_prompt_ready(db_session, ready_shot, video):
    video_job_service.submit_shot_video_job(db_session, ready_shot, video)  # -> GENERATING

    with pytest.raises(InvalidShotStateError):
        video_job_service.submit_shot_video_job(db_session, ready_shot, video)


def test_cannot_poll_a_job_already_in_terminal_state(db_session, ready_shot, video):
    job = video_job_service.submit_shot_video_job(db_session, ready_shot, video)
    job = _poll_until_terminal(db_session, job, video)
    assert job.status == VideoJobStatus.COMPLETED

    with pytest.raises(InvalidJobStateError):
        video_job_service.poll_shot_video_job(db_session, job, video)


def test_regenerate_requires_a_failed_shot(db_session, ready_shot, video):
    with pytest.raises(InvalidShotStateError):
        video_job_service.regenerate_shot_video(db_session, ready_shot, video)


def test_regenerate_respects_max_regenerations(db_session, ready_shot, video, monkeypatch):
    monkeypatch.setattr(settings, "max_regenerations_per_shot", 1)

    job = video_job_service.submit_shot_video_job(
        db_session, ready_shot, video, extra_params={"mock_behavior": "fail"}
    )
    video_job_service.poll_shot_video_job(db_session, job, video)
    assert ready_shot.status == ShotStatus.FAILED

    video_job_service.regenerate_shot_video(db_session, ready_shot, video)
    assert ready_shot.regeneration_count == 1

    # Force it back to FAILED so we can try to regenerate past the limit.
    ready_shot.status = ShotStatus.FAILED
    db_session.commit()

    with pytest.raises(MaxRegenerationsExceededError):
        video_job_service.regenerate_shot_video(db_session, ready_shot, video)


# ---------------------------------------------------------------------------
# Paused factory
# ---------------------------------------------------------------------------


def test_paused_factory_blocks_submission(db_session, ready_shot, video, monkeypatch):
    monkeypatch.setattr(settings, "factory_paused", True)

    with pytest.raises(FactoryPausedError):
        video_job_service.submit_shot_video_job(db_session, ready_shot, video)

    assert ready_shot.status == ShotStatus.PROMPT_READY
    assert len(ready_shot.video_jobs) == 0


# ---------------------------------------------------------------------------
# Project spending limit exceeded
# ---------------------------------------------------------------------------


def test_spend_limit_blocks_submission_before_any_provider_call(db_session, ready_shot, video, monkeypatch):
    monkeypatch.setattr(settings, "max_spend_per_project_usd", 0.01)

    with pytest.raises(SpendLimitExceededError):
        video_job_service.submit_shot_video_job(db_session, ready_shot, video)

    # No job should have been created and the shot should be untouched -
    # the check happens before any provider call or DB write.
    assert ready_shot.status == ShotStatus.PROMPT_READY
    assert len(ready_shot.video_jobs) == 0


def test_spend_limit_allows_submission_within_budget(db_session, ready_shot, video, monkeypatch):
    monkeypatch.setattr(settings, "max_spend_per_project_usd", 1.00)

    job = video_job_service.submit_shot_video_job(db_session, ready_shot, video)
    assert job.status == VideoJobStatus.PROCESSING
