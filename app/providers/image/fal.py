"""Real fal.ai-backed ImageProvider for FLUX.1 [schnell].

Same caveat as providers/video/fal.py: written from fal.ai's documentation
and model page (synchronous inference at https://fal.run/{model_id}, not
the async queue - schnell is fast enough that fal.ai serves it directly),
not yet executed against the live API from this sandbox.

Configurable via `FalImageModelConfig` the same way the video adapter is,
so a different fal.ai image model can be swapped in later without touching
this class.
"""
import math
from dataclasses import dataclass
from pathlib import Path

import httpx

from app.config import settings
from app.providers.base import ImageGenerationRequest, ImageProvider, ImageProviderError, ImageResult

FAL_SYNC_BASE = "https://fal.run"


@dataclass
class FalImageModelConfig:
    model_id: str
    price_per_megapixel: float


# Cheapest credible text-to-image on fal.ai; supports 9:16 via width/height.
FLUX_SCHNELL = FalImageModelConfig(model_id="fal-ai/flux/schnell", price_per_megapixel=0.003)


class FalImageProvider(ImageProvider):
    """`client` exists so tests can inject a fake-transport httpx.Client
    instead of hitting the network - see tests/test_fal_providers.py."""

    def __init__(
        self,
        model_config: FalImageModelConfig = FLUX_SCHNELL,
        api_key: str | None = None,
        client: httpx.Client | None = None,
    ) -> None:
        self.model_config = model_config
        self.name = f"fal:{model_config.model_id}"
        self.api_key = api_key or settings.fal_api_key
        self._client = client or httpx.Client(timeout=60.0)

    def _headers(self) -> dict:
        if not self.api_key:
            raise ImageProviderError(
                "FAL_API_KEY is not configured. Set it in .env before using a real fal.ai provider."
            )
        return {"Authorization": f"Key {self.api_key}"}

    def estimate_cost(self, request: ImageGenerationRequest) -> float:
        megapixels = (request.width * request.height) / 1_000_000
        billed_megapixels = max(1, math.ceil(megapixels))
        return round(billed_megapixels * self.model_config.price_per_megapixel, 4)

    def generate_image(self, request: ImageGenerationRequest, destination_path: str) -> ImageResult:
        payload = {
            "prompt": request.prompt,
            "image_size": {"width": request.width, "height": request.height},
            "num_images": 1,
        }
        resp = self._client.post(
            f"{FAL_SYNC_BASE}/{self.model_config.model_id}", headers=self._headers(), json=payload
        )
        if resp.status_code >= 400:
            raise ImageProviderError(f"fal.ai image generation failed: {resp.status_code} {resp.text}")
        data = resp.json()
        images = data.get("images") or []
        if not images:
            raise ImageProviderError(f"fal.ai returned no images: {data}")
        image_url = images[0]["url"]

        download = self._client.get(image_url)
        if download.status_code >= 400:
            raise ImageProviderError(f"fal.ai image download failed: {download.status_code}")

        dest = Path(destination_path)
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(download.content)

        return ImageResult(
            provider_name=self.name,
            file_path=str(dest),
            cost_usd=self.estimate_cost(request),
            meta={"seed": data.get("seed")},
        )
