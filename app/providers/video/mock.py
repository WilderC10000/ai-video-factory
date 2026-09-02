"""A free video provider used until a real paid provider is wired in and
explicitly approved. It never makes a network call and never costs real
money - `estimate_cost`/`actual_cost_usd` return a small SIMULATED number
purely so the spend-limit and cost-tracking logic has something real to
exercise and test.

Real video providers bill in different ways - some per second of output
(e.g. Wan 2.2 A14B standard), some a flat price per video regardless of
exact length (e.g. Wan 2.2 A14B Turbo, priced by resolution tier only).
`VideoPricingConfig` models both so our cost estimates match whichever
billing model the active provider actually uses; see providers/video/fal.py
for the real (not yet invoked) adapter that shares these same configs.

Its behavior is controllable per-request via `extra_params["mock_behavior"]`
so the whole async submit -> poll -> complete/fail/timeout/retry flow can be
tested deterministically, without sleeping or hitting a real API:

    "success"            (default) PROCESSING for a couple of polls, then COMPLETED
    "fail"                the provider reports the generation itself failed
    "timeout"             always PROCESSING - never completes (exercises our timeout logic)
    "flaky_then_success"  raises VideoProviderError a couple of times, then COMPLETED
    "submit_fail"         raises VideoProviderError immediately on submit

Pass `extra_params["resolution"]` ("480p"/"580p"/"720p") to pick a pricing
tier; defaults to the pricing config's own default_resolution (480p).
"""
import uuid
from dataclasses import dataclass, field
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


@dataclass
class VideoPricingConfig:
    """One provider/model's billing shape. `billing` is `"flat"` (look up
    `price_by_resolution`, ignore duration) or `"per_second"` (look up
    `price_per_second_by_resolution`, multiply by requested duration)."""

    billing: str
    price_by_resolution: dict[str, float] = field(default_factory=dict)
    price_per_second_by_resolution: dict[str, float] = field(default_factory=dict)
    default_resolution: str = "480p"


# Wan 2.2 A14B Turbo, per fal.ai's official pricing: flat per-video by
# resolution tier, NOT per-second. Our current cheapest-credible candidate
# and the mock's default, so local cost estimates match what we'd actually
# be quoted.
WAN_TURBO_PRICING = VideoPricingConfig(
    billing="flat",
    price_by_resolution={"480p": 0.05, "580p": 0.075, "720p": 0.10},
    default_resolution="480p",
)

# Wan 2.2 A14B standard (non-turbo), per fal.ai's official pricing:
# per-second by resolution tier. Higher quality, kept available so an
# individual important shot can be upgraded later - see FalVideoModelConfig
# for how this plugs into the real adapter.
WAN_STANDARD_PRICING = VideoPricingConfig(
    billing="per_second",
    price_per_second_by_resolution={"480p": 0.04, "580p": 0.06, "720p": 0.08},
    default_resolution="480p",
)


class MockVideoProvider(VideoProvider):
    name = "mock-video"

    def __init__(self, pricing: VideoPricingConfig = WAN_TURBO_PRICING) -> None:
        self.pricing = pricing
        # In-memory job store. A real provider doesn't need this - the vendor's
        # API is the source of truth - but the mock has to remember what it
        # promised to do across separate submit()/get_job_status() calls.
        self._jobs: dict[str, dict] = {}

    def _resolution(self, request: VideoGenerationRequest) -> str:
        return request.extra_params.get("resolution", self.pricing.default_resolution)

    def estimate_cost(self, request: VideoGenerationRequest) -> float:
        resolution = self._resolution(request)
        if self.pricing.billing == "flat":
            price = self.pricing.price_by_resolution.get(resolution)
        else:
            per_second = self.pricing.price_per_second_by_resolution.get(resolution)
            price = per_second * request.duration_seconds if per_second is not None else None
        if price is None:
            raise VideoProviderError(f"Mock provider: no pricing configured for resolution {resolution!r}")
        return round(price, 4)

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

    def get_job_status(self, provider_job_id: str, meta: dict | None = None) -> VideoJobStatusResult:
        # The mock's in-memory _jobs store already has everything it needs
        # keyed by provider_job_id; meta (real providers' status/result
        # URLs) doesn't apply here.
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
