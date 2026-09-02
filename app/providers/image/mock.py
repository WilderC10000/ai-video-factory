"""A free image provider used until a real paid provider is wired in and
approved. Never makes a network call. `estimate_cost` mirrors fal.ai's
FLUX.1 [schnell] pricing ($0.003/megapixel, billed rounded up to the next
whole megapixel) purely so our cost estimates and spend-limit tests reflect
real-world numbers - no real money changes hands here.

`extra_params["mock_behavior"] = "fail"` simulates a provider-side failure
for testing, mirroring the mock video provider's controllability.
"""
import math
from pathlib import Path

from app.providers.base import ImageGenerationRequest, ImageProvider, ImageProviderError, ImageResult

_FIXTURE_IMAGE = Path(__file__).resolve().parent / "fixtures" / "mock_reference.jpg"


class MockImageProvider(ImageProvider):
    name = "mock-image"

    def __init__(self, cost_per_megapixel: float = 0.003) -> None:
        self.cost_per_megapixel = cost_per_megapixel

    def estimate_cost(self, request: ImageGenerationRequest) -> float:
        megapixels = (request.width * request.height) / 1_000_000
        billed_megapixels = max(1, math.ceil(megapixels))
        return round(billed_megapixels * self.cost_per_megapixel, 4)

    def generate_image(self, request: ImageGenerationRequest, destination_path: str) -> ImageResult:
        if request.extra_params.get("mock_behavior") == "fail":
            raise ImageProviderError("Mock provider: image generation failed (simulated).")

        dest = Path(destination_path)
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(_FIXTURE_IMAGE.read_bytes())

        return ImageResult(
            provider_name=self.name,
            file_path=str(dest),
            cost_usd=self.estimate_cost(request),
            meta={"mock": True},
        )
