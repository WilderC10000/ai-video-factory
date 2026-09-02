"""Real fal.ai-backed VideoProvider for Alibaba's Wan 2.2 A14B family.

IMPORTANT - not yet executed against the live API: outbound network access
to fal.ai is blocked from this development sandbox, so this adapter is
implemented from fal.ai's documented queue API (submit/status/result,
`Authorization: Key $FAL_API_KEY`) and model pages, cross-checked via
several sources, but has never actually been called. Treat the first real
invocation as a live integration test - watch the response shapes closely,
and don't be surprised if a field name needs a small fix.

Configurable between named model presets via `FalVideoModelConfig` - swap
which one is active by passing a different config to FalVideoProvider,
without touching any other code. Two are defined below (Turbo and
standard); adding a third fal.ai model (or a different provider entirely,
e.g. Kling/Veo later) means adding one more config/class, not editing this
one.
"""
from dataclasses import dataclass, field
from pathlib import Path

import httpx

from app.config import settings
from app.providers.base import (
    ProviderJobState,
    SubmittedVideoJob,
    VideoGenerationRequest,
    VideoJobStatusResult,
    VideoProvider,
    VideoProviderError,
)

FAL_QUEUE_BASE = "https://queue.fal.run"
FAL_STORAGE_BASE = "https://rest.alpha.fal.ai"


@dataclass
class FalVideoModelConfig:
    """One named, swappable fal.ai video model configuration."""

    model_id: str
    billing: str  # "flat" (price_by_resolution) or "per_second" (price_per_second_by_resolution)
    price_by_resolution: dict[str, float] = field(default_factory=dict)
    price_per_second_by_resolution: dict[str, float] = field(default_factory=dict)
    default_resolution: str = "480p"


# Cheapest-first candidate: flat per-video pricing, not per-second. Fixed
# ~4s output (65 frames @ 16fps); duration is not configurable on this
# endpoint - resolution is the only cost lever.
WAN_TURBO = FalVideoModelConfig(
    model_id="fal-ai/wan/v2.2-a14b/image-to-video/turbo",
    billing="flat",
    price_by_resolution={"480p": 0.05, "580p": 0.075, "720p": 0.10},
    default_resolution="480p",
)

# Higher-quality, non-turbo alternative, billed per second of output
# instead of a flat rate. Kept available so an individual important shot
# can be upgraded later just by passing this config instead of WAN_TURBO.
WAN_STANDARD = FalVideoModelConfig(
    model_id="fal-ai/wan/v2.2-a14b/image-to-video",
    billing="per_second",
    price_per_second_by_resolution={"480p": 0.04, "580p": 0.06, "720p": 0.08},
    default_resolution="480p",
)


class FalVideoProvider(VideoProvider):
    """Talks to fal.ai's queue API for Wan 2.2 A14B (Turbo or standard).

    The `client` param exists so tests can inject an `httpx.Client` backed by
    a fake transport (see tests/test_fal_providers.py) instead of hitting
    the network - that's how this adapter's request/response handling is
    verified without any real call or cost.
    """

    def __init__(
        self,
        model_config: FalVideoModelConfig = WAN_TURBO,
        api_key: str | None = None,
        client: httpx.Client | None = None,
    ) -> None:
        self.model_config = model_config
        self.name = f"fal:{model_config.model_id}"
        self.api_key = api_key or settings.fal_api_key
        self._client = client or httpx.Client(timeout=60.0)

    def _headers(self) -> dict:
        if not self.api_key:
            raise VideoProviderError(
                "FAL_API_KEY is not configured. Set it in .env before using a real fal.ai provider."
            )
        return {"Authorization": f"Key {self.api_key}"}

    def _resolution(self, request: VideoGenerationRequest) -> str:
        return request.extra_params.get("resolution", self.model_config.default_resolution)

    def estimate_cost(self, request: VideoGenerationRequest) -> float:
        resolution = self._resolution(request)
        if self.model_config.billing == "flat":
            price = self.model_config.price_by_resolution.get(resolution)
        else:
            per_second = self.model_config.price_per_second_by_resolution.get(resolution)
            price = per_second * request.duration_seconds if per_second is not None else None
        if price is None:
            raise VideoProviderError(
                f"No pricing configured for resolution {resolution!r} on {self.model_config.model_id}"
            )
        return round(price, 4)

    def _upload_reference_image(self, local_path: str) -> str:
        """fal.ai's documented 2-step upload: request a signed upload URL,
        PUT the file bytes to it, then use the returned public file URL as
        `image_url` in the generation request."""
        path = Path(local_path)
        content_type = "image/jpeg" if path.suffix.lower() in (".jpg", ".jpeg") else "image/png"

        initiate = self._client.post(
            f"{FAL_STORAGE_BASE}/storage/upload/initiate",
            headers=self._headers(),
            json={"content_type": content_type, "file_name": path.name},
        )
        if initiate.status_code >= 400:
            raise VideoProviderError(f"fal.ai upload initiate failed: {initiate.status_code} {initiate.text}")
        data = initiate.json()
        upload_url, file_url = data["upload_url"], data["file_url"]

        put_resp = self._client.put(upload_url, content=path.read_bytes(), headers={"Content-Type": content_type})
        if put_resp.status_code >= 400:
            raise VideoProviderError(f"fal.ai image upload failed: {put_resp.status_code}")
        return file_url

    def submit_video_job(self, request: VideoGenerationRequest) -> SubmittedVideoJob:
        if not request.reference_image_path:
            raise VideoProviderError("Wan image-to-video requires a reference image; none was provided.")

        image_url = self._upload_reference_image(request.reference_image_path)
        payload = {
            "image_url": image_url,
            "prompt": request.prompt,
            "resolution": self._resolution(request),
            "aspect_ratio": request.aspect_ratio,
        }
        resp = self._client.post(
            f"{FAL_QUEUE_BASE}/{self.model_config.model_id}", headers=self._headers(), json=payload
        )
        if resp.status_code >= 400:
            raise VideoProviderError(f"fal.ai submit failed: {resp.status_code} {resp.text}")
        data = resp.json()

        return SubmittedVideoJob(
            provider_name=self.name,
            provider_job_id=data["request_id"],
            estimated_cost_usd=self.estimate_cost(request),
            meta={"status_url": data.get("status_url"), "response_url": data.get("response_url")},
        )

    def get_job_status(self, provider_job_id: str) -> VideoJobStatusResult:
        status_url = f"{FAL_QUEUE_BASE}/{self.model_config.model_id}/requests/{provider_job_id}/status"
        resp = self._client.get(status_url, headers=self._headers())
        if resp.status_code >= 400:
            raise VideoProviderError(f"fal.ai status check failed: {resp.status_code} {resp.text}")
        data = resp.json()
        status = data.get("status")

        if status in ("IN_QUEUE", "IN_PROGRESS"):
            return VideoJobStatusResult(status=ProviderJobState.PROCESSING)

        if status == "COMPLETED":
            result_url = f"{FAL_QUEUE_BASE}/{self.model_config.model_id}/requests/{provider_job_id}"
            result_resp = self._client.get(result_url, headers=self._headers())
            if result_resp.status_code >= 400:
                raise VideoProviderError(
                    f"fal.ai result fetch failed: {result_resp.status_code} {result_resp.text}"
                )
            result = result_resp.json()
            video_url = (result.get("video") or {}).get("url")
            if not video_url:
                raise VideoProviderError(f"fal.ai result had no video URL: {result}")
            return VideoJobStatusResult(status=ProviderJobState.COMPLETED, output_url=video_url)

        return VideoJobStatusResult(
            status=ProviderJobState.FAILED, error_message=f"fal.ai reported status {status!r}: {data}"
        )

    def download_result(self, provider_job_id: str, output_url: str, destination_path: str) -> str:
        resp = self._client.get(output_url)
        if resp.status_code >= 400:
            raise VideoProviderError(f"fal.ai clip download failed: {resp.status_code}")

        dest = Path(destination_path)
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(resp.content)
        return str(dest)
