"""A free video provider used until a real paid provider (Veo/Kling/Runway/...)
is wired in and explicitly approved. It never makes a network call and never
costs real money - `estimate_cost`/`actual_cost_usd` return a small SIMULATED
number purely so the spend-limit and cost-tracking logic has something real
to exercise and test.

Its behavior is controllable per-request via `extra_params["mock_behavior"]`
so the whole async submit -> poll -> complete/fail/timeout/retry flow can be
tested deterministically, without sleeping or hitting a real API:

    "success"            (default) PROCESSING for a couple of polls, then COMPLETED
    "fail"                the provider reports the generation itself failed
    "timeout"             always PROCESSING - never completes (exercises our timeout logic)
    "flaky_then_success"  raises VideoProviderError a couple of times, then COMPLETED
    "submit_fail"         raises VideoProviderError immediately on submit
"""
import uuid
from pathlib import Path

from app.providers.base import (
    ProviderJobState,
    SubmittedVideoJob,
    VideoGenerationRequest,
    VideoJobStatusResult,
    VideoProvider,
    VideoProviderError,
)

_FIXTURE_CLIP = Path(__file__).resolve().parent / "fixtures" / "mock_clip.mp4"


class MockVideoProvider(VideoProvider):
    name = "mock-video"

    def __init__(self, cost_per_second: float = 0.04) -> None:
        # Default mirrors fal.ai's Wan 2.2 A14B image-to-video at 480p
        # ($0.04/video-second) - our current cheapest-credible real candidate -
        # so cost estimates shown locally are a realistic preview, not a
        # placeholder number.
        self.cost_per_second = cost_per_second
        # In-memory job store. A real provider doesn't need this - the vendor's
        # API is the source of truth - but the mock has to remember what it
        # promised to do across separate submit()/get_job_status() calls.
        self._jobs: dict[str, dict] = {}

    def estimate_cost(self, request: VideoGenerationRequest) -> float:
        return round(self.cost_per_second * request.duration_seconds, 4)

    def submit_video_job(self, request: VideoGenerationRequest) -> SubmittedVideoJob:
        behavior = request.extra_params.get("mock_behavior", "success")
        if behavior == "submit_fail":
            raise VideoProviderError("Mock provider: rejected the request (simulated submission failure).")

        job_id = uuid.uuid4().hex
        estimated_cost = self.estimate_cost(request)
        self._jobs[job_id] = {
            "behavior": behavior,
            "poll_count": 0,
            "polls_until_complete": request.extra_params.get("polls_until_complete", 2),
            "flaky_remaining": request.extra_params.get("flaky_failures", 2),
            "estimated_cost": estimated_cost,
        }
        return SubmittedVideoJob(
            provider_name=self.name,
            provider_job_id=job_id,
            estimated_cost_usd=estimated_cost,
            meta={"mock": True, "mock_behavior": behavior},
        )

    def get_job_status(self, provider_job_id: str) -> VideoJobStatusResult:
        entry = self._jobs.get(provider_job_id)
        if entry is None:
            raise VideoProviderError(f"Mock provider: unknown job id {provider_job_id!r}")

        behavior = entry["behavior"]

        if behavior == "timeout":
            return VideoJobStatusResult(status=ProviderJobState.PROCESSING)

        if behavior == "fail":
            return VideoJobStatusResult(
                status=ProviderJobState.FAILED,
                error_message="Mock provider: generation failed (simulated).",
            )

        if behavior == "flaky_then_success" and entry["flaky_remaining"] > 0:
            entry["flaky_remaining"] -= 1
            raise VideoProviderError("Mock provider: transient error, please retry.")

        entry["poll_count"] += 1
        if entry["poll_count"] < entry["polls_until_complete"]:
            return VideoJobStatusResult(status=ProviderJobState.PROCESSING)

        return VideoJobStatusResult(
            status=ProviderJobState.COMPLETED,
            output_url=f"mock://{provider_job_id}",
            actual_cost_usd=entry["estimated_cost"],
            meta={"mock": True},
        )

    def download_result(self, provider_job_id: str, output_url: str, destination_path: str) -> str:
        if provider_job_id not in self._jobs:
            raise VideoProviderError(f"Mock provider: unknown job id {provider_job_id!r}")

        dest = Path(destination_path)
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(_FIXTURE_CLIP.read_bytes())
        return str(dest)
