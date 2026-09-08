"""Real fal.ai-backed ImageProvider for the FLUX.1 family.

Same caveat as providers/video/fal.py: written from fal.ai's documentation
and model pages (synchronous inference at https://fal.run/{model_id}, not
the async queue - FLUX images are fast enough that fal.ai serves them
directly), verified against multiple sources but not yet executed against
the live API from this sandbox.

Configurable via `FalImageModelConfig` the same way the video adapter is,
so a different fal.ai image model can be swapped in later without touching
this class. FLUX_PRO (not "ultra") was deliberately chosen over FLUX pro
Ultra for the quality bake-off's reference image: Ultra's billing was
ambiguous between two conflicting figures across sources ($0.06/image vs.
$0.05/megapixel), and Ultra sizes its output via `aspect_ratio` rather than
explicit width/height, which would make the megapixel count - and so the
exact cost - impossible to know before the call. FLUX_PRO takes the same
explicit width/height as FLUX_SCHNELL, so its cost is exactly
pre-computable, consistent with every other provider in this codebase.

NANO_BANANA_PRO_EDIT is a different capability from the two FLUX configs:
prompt-guided EDITING of an existing image (e.g. correcting a hand/tool
pose) rather than text-to-image generation. It bills a flat $0.15/image at
standard resolution regardless of input/output size (verified via fal.ai's
own docs/pricing pages), not per-megapixel like FLUX - hence
`price_per_image` as a separate, optional config field that overrides the
per-megapixel calculation when set. Because it edits an existing image, it
needs that image hosted at a URL first - `_upload_image()` implements
fal.ai's documented 2-step upload (signed URL, then PUT the bytes), the
same mechanism `FalVideoProvider._upload_reference_image` already uses for
video reference images; FLUX text-to-image never needed this since it has
no input image at all.

NANO_BANANA_PRO_GENERATE is Nano Banana Pro's separate text-to-image
endpoint (`fal-ai/nano-banana-pro`, no `/edit` suffix) - same $0.15/image
flat billing, but a genuinely different request shape from FLUX: it takes
`aspect_ratio` (an enum like "9:16") and `resolution` ("1K"/"2K"/"4K")
instead of explicit `image_size: {width, height}` - verified against
fal.ai's own documented example request. `FalImageModelConfig.
uses_aspect_ratio` selects which payload shape `generate_image()` builds,
the same per-model-differences pattern already used for video (Kling's
`image_param_name`, `supports_resolution_param`). We only ever request
"1K" resolution here, which keeps the flat rate at $0.15 (4K is $0.30).
"""
import math
from dataclasses import dataclass
from pathlib import Path

import httpx

from app.config import settings
from app.providers.base import (
    ImageEditRequest,
    ImageGenerationRequest,
    ImageProvider,
    ImageProviderError,
    ImageResult,
)

FAL_SYNC_BASE = "https://fal.run"
FAL_STORAGE_BASE = "https://rest.alpha.fal.ai"


@dataclass
class FalImageModelConfig:
    model_id: str
    price_per_megapixel: float = 0.0
    # Flat per-call price (e.g. Nano Banana Pro's $0.15/image regardless of
    # size) - overrides the megapixel calculation in estimate_cost()/
    # estimate_edit_cost() when set. None for the FLUX configs below, which
    # bill per-megapixel.
    price_per_image: float | None = None
    # True for models whose text-to-image endpoint takes aspect_ratio +
    # resolution instead of explicit image_size: {width, height} (e.g. Nano
    # Banana Pro's generation endpoint). Selects the payload shape
    # generate_image() builds - see module docstring.
    uses_aspect_ratio: bool = False


# Cheapest credible text-to-image on fal.ai; supports 9:16 via width/height.
FLUX_SCHNELL = FalImageModelConfig(model_id="fal-ai/flux/schnell", price_per_megapixel=0.003)

# Higher-fidelity tier for when the reference image is worth spending more
# on (e.g. it seeds an entire propagated shot chain, so its quality matters
# more than any single downstream shot's). $0.04/MP vs schnell's $0.003/MP -
# still a rounding error next to any video generation cost.
FLUX_PRO = FalImageModelConfig(model_id="fal-ai/flux-pro/v1.1", price_per_megapixel=0.04)

# Prompt-guided editing of an existing image, not text-to-image generation -
# used to correct hand/tool pose mechanics in an already-generated reference
# image (see scripts/run_v2a_keyframes_test.py). $0.15/image at standard
# (1K/2K) resolution; $0.30/image at 4K (not used here - we never request
# 4K, so num_images/resolution defaults keep this at the $0.15 rate).
NANO_BANANA_PRO_EDIT = FalImageModelConfig(model_id="fal-ai/nano-banana-pro/edit", price_per_image=0.15)

# Nano Banana Pro's text-to-image endpoint (not /edit) - used when the
# composition itself needs to be generated fresh rather than repaired via
# a local edit (see scripts/run_composition_test.py). Same $0.15/image
# flat rate as the edit endpoint; different request shape (aspect_ratio,
# not width/height) - see module docstring.
NANO_BANANA_PRO_GENERATE = FalImageModelConfig(
    model_id="fal-ai/nano-banana-pro", price_per_image=0.15, uses_aspect_ratio=True
)


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
        if self.model_config.price_per_image is not None:
            return round(self.model_config.price_per_image, 4)
        megapixels = (request.width * request.height) / 1_000_000
        billed_megapixels = max(1, math.ceil(megapixels))
        return round(billed_megapixels * self.model_config.price_per_megapixel, 4)

    def generate_image(self, request: ImageGenerationRequest, destination_path: str) -> ImageResult:
        if self.model_config.uses_aspect_ratio:
            payload = {
                "prompt": request.prompt,
                "aspect_ratio": request.extra_params.get("aspect_ratio", "9:16"),
                "resolution": request.extra_params.get("resolution", "1K"),
                "num_images": 1,
                "limit_generations": True,  # defensive: never let prompt text imply >1 image
            }
        else:
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

    def estimate_edit_cost(self) -> float:
        """Edit calls (e.g. NANO_BANANA_PRO_EDIT) bill a flat price per image,
        not per-megapixel - there's no width/height on ImageEditRequest to
        compute a megapixel count from, since output size inherits from the
        input image rather than being requested explicitly."""
        if self.model_config.price_per_image is None:
            raise ImageProviderError(
                f"{self.model_config.model_id} has no flat price_per_image configured - "
                "estimate_edit_cost() only works for edit-capable configs like NANO_BANANA_PRO_EDIT."
            )
        return round(self.model_config.price_per_image, 4)

    def _upload_image(self, local_path: str) -> str:
        """fal.ai's documented 2-step upload (same mechanism
        FalVideoProvider._upload_reference_image uses): request a signed
        upload URL, PUT the file bytes to it, then use the returned public
        file URL as one of edit_image()'s image_urls."""
        path = Path(local_path)
        content_type = "image/jpeg" if path.suffix.lower() in (".jpg", ".jpeg") else "image/png"

        initiate_url = f"{FAL_STORAGE_BASE}/storage/upload/initiate"
        initiate = self._client.post(
            initiate_url, headers=self._headers(), json={"content_type": content_type, "file_name": path.name}
        )
        if initiate.status_code >= 400:
            raise ImageProviderError(f"fal.ai upload initiate failed: {initiate.status_code} {initiate.text}")
        data = initiate.json()
        upload_url, file_url = data["upload_url"], data["file_url"]

        put_resp = self._client.put(upload_url, content=path.read_bytes(), headers={"Content-Type": content_type})
        if put_resp.status_code >= 400:
            raise ImageProviderError(f"fal.ai image upload failed: {put_resp.status_code}")
        return file_url

    def edit_image(self, request: ImageEditRequest, destination_path: str) -> ImageResult:
        image_urls = [self._upload_image(p) for p in request.reference_image_paths]
        payload = {"prompt": request.prompt, "image_urls": image_urls, "num_images": 1}
        payload.update(request.extra_params)

        resp = self._client.post(
            f"{FAL_SYNC_BASE}/{self.model_config.model_id}", headers=self._headers(), json=payload
        )
        if resp.status_code >= 400:
            raise ImageProviderError(f"fal.ai image edit failed: {resp.status_code} {resp.text}")
        data = resp.json()
        images = data.get("images") or []
        if not images:
            raise ImageProviderError(f"fal.ai edit returned no images: {data}")
        image_url = images[0]["url"]

        download = self._client.get(image_url)
        if download.status_code >= 400:
            raise ImageProviderError(f"fal.ai edited image download failed: {download.status_code}")

        dest = Path(destination_path)
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(download.content)

        return ImageResult(
            provider_name=self.name,
            file_path=str(dest),
            cost_usd=self.estimate_edit_cost(),
            meta={"description": data.get("description")},
        )
