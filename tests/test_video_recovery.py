"""Recovering an already-submitted provider job must never submit a new generation."""
import dataclasses
import json

import pytest

from app.config import settings
from app.providers.base import ProviderJobState, VideoJobStatusResult
from scripts import run_alpine_video_2_common as pipeline
from scripts import run_train_car_video_2_stage as train_car

JOB_ID = "01a0d5a2-723b-7091-adb9-7afb0316d086"


class ExistingJobOnlyProvider:
    """Answers status/download for one existing job; any submission is a test failure."""

    def __init__(self, statuses):
        self.statuses = list(statuses)
        self.status_calls = []

    def submit_video_job(self, _request):  # pragma: no cover - must never run
        raise AssertionError("recovery attempted a NEW paid submission")

    def get_job_status(self, provider_job_id, meta=None):
        self.status_calls.append((provider_job_id, meta))
        status = self.statuses.pop(0)
        if status == "done":
            return VideoJobStatusResult(status=ProviderJobState.COMPLETED, output_url="https://fake/clip03.mp4")
        if status == "fail":
            return VideoJobStatusResult(status=ProviderJobState.FAILED, error_message="boom")
        return VideoJobStatusResult(status=ProviderJobState.PROCESSING, meta={"provider_status": status})

    def download_result(self, provider_job_id, output_url, destination_path):
        with open(destination_path, "wb") as f:
            f.write(b"video")
        return destination_path


@pytest.fixture()
def started_clip(tmp_path):
    spec = dataclasses.replace(
        train_car.SPECS["clip03"],
        raw_output_path=tmp_path / "clips" / "clip03_raw.mp4",
        job_state_path=tmp_path / "clips" / "clip03_last_job.json",
    )
    spec.job_state_path.parent.mkdir()
    meta = {"status_url": f"https://queue.fal.run/alibaba/wan-3.0/requests/{JOB_ID}/status",
            "response_url": f"https://queue.fal.run/alibaba/wan-3.0/requests/{JOB_ID}"}
    spec.job_state_path.write_text(json.dumps({"provider_job_id": JOB_ID, "meta": meta}))
    manifest = tmp_path / "manifest.json"
    manifest.write_text(json.dumps({
        "budget_cap_usd": 15.0,
        "clip03": {"estimated_cost_usd": 0.30, "raw_video_path": None, "actual_cost_usd": None, "completed_at": None},
    }))
    return spec, manifest, meta


def test_single_check_reports_queue_and_changes_nothing(started_clip):
    spec, manifest, meta = started_clip
    provider = ExistingJobOnlyProvider(["IN_QUEUE"])
    result = pipeline.recover_video_shot(spec, video_provider=provider, manifest_path=manifest, wait=False,
                                         log=lambda *_: None)
    assert result == {"status": "queued", "provider_job_id": JOB_ID, "provider_status": "IN_QUEUE"}
    assert provider.status_calls == [(JOB_ID, meta)]  # the saved Wan 3.0 status/response URLs are used
    assert json.loads(manifest.read_text())["clip03"]["completed_at"] is None


def test_waits_then_downloads_into_the_existing_stage_preserving_job_and_cost(started_clip):
    spec, manifest, _ = started_clip
    provider = ExistingJobOnlyProvider(["IN_QUEUE", "IN_PROGRESS", "done"])
    phases = []
    result = pipeline.recover_video_shot(spec, video_provider=provider, manifest_path=manifest, wait=True,
                                         poll_interval_seconds=0, on_phase=lambda p, _d: phases.append(p),
                                         log=lambda *_: None)
    entry = json.loads(manifest.read_text())["clip03"]
    assert result["status"] == "completed" and spec.raw_output_path.read_bytes() == b"video"
    assert entry["provider_job_id"] == JOB_ID and entry["actual_cost_usd"] == 0.30
    assert entry["raw_video_path"].endswith("clip03_raw.mp4") and entry["completed_at"] and entry["recovered_at"]
    assert phases == ["provider_queued", "generating", "downloading"]
    assert "proof_gate" not in json.loads(manifest.read_text())  # recovery never passes the gate


def test_provider_failure_and_missing_state_are_reported_not_resubmitted(started_clip, tmp_path):
    spec, manifest, _ = started_clip
    with pytest.raises(pipeline.PipelineStepError, match="Provider reported failure"):
        pipeline.recover_video_shot(spec, video_provider=ExistingJobOnlyProvider(["fail"]), manifest_path=manifest,
                                    log=lambda *_: None)
    spec.job_state_path.unlink()
    with pytest.raises(pipeline.PipelineStepError, match="No saved job state"):
        pipeline.recover_video_shot(spec, video_provider=ExistingJobOnlyProvider([]), manifest_path=manifest,
                                    log=lambda *_: None)


def test_live_wait_timeout_is_45_minutes():
    assert settings.studio_live_wait_timeout_seconds == 45 * 60


def test_provider_job_id_is_recorded_at_submission_not_only_on_completion(started_clip):
    spec, manifest, _ = started_clip
    spec.job_state_path.unlink()

    class DiesAfterSubmit:
        def estimate_cost(self, _request):
            return 0.30

        def submit_video_job(self, _request):
            from app.providers.base import SubmittedVideoJob

            return SubmittedVideoJob(provider_name="fake", provider_job_id="job-xyz", estimated_cost_usd=0.30, meta={})

        def get_job_status(self, *_args, **_kwargs):
            from app.providers.base import VideoProviderError

            raise VideoProviderError("connection lost")

    for still in (spec.start_frame_path, spec.end_frame_path):
        still.parent.mkdir(parents=True, exist_ok=True)
    start = dataclasses.replace(spec, start_frame_path=spec.job_state_path.parent / "s.jpg",
                                upstream_path=spec.job_state_path.parent / "s.jpg",
                                end_frame_path=spec.job_state_path.parent / "e.jpg")
    start.start_frame_path.write_bytes(b"s")
    start.end_frame_path.write_bytes(b"e")
    with pytest.raises(pipeline.PipelineStepError, match="Status check failed"):
        pipeline.execute_video_shot(start, video_provider=DiesAfterSubmit(), manifest_path=manifest,
                                    log=lambda *_: None)
    assert json.loads(manifest.read_text())["clip03"]["provider_job_id"] == "job-xyz"
