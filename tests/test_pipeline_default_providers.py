"""The REAL default providers used by live runs must be constructible - offline.

Mock-mode tests inject mock providers, so they never exercise the live defaults.
These tests build each default (no network: provider constructors make no calls)
and check it targets the same model the proven scripts use.
"""
import json

import httpx
import pytest

from app.providers.base import ImageGenerationRequest
from app.providers.image.fal import NANO_BANANA_PRO_EDIT, NANO_BANANA_PRO_GENERATE
from scripts import run_alpine_video_2_common as pipeline
from scripts import run_alpine_video_2_site_reference as site_reference
from scripts import run_train_car_video_2_stage as train_car


def test_default_generate_provider_matches_the_proven_site_reference_script():
    provider = pipeline.default_generate_provider()
    assert provider.model_config is NANO_BANANA_PRO_GENERATE
    assert "NANO_BANANA_PRO_GENERATE" in site_reference.__dict__  # the constant that script ran live with
    spec = train_car.SPECS["cp01_still"]
    request = ImageGenerationRequest(prompt=spec.prompt,
                                     extra_params={"aspect_ratio": spec.aspect_ratio, "resolution": spec.resolution})
    cost = provider.estimate_cost(request)
    assert cost == pytest.approx(0.15) and cost <= spec.max_spend_usd


def test_default_edit_and_video_providers_build_offline():
    assert pipeline.default_image_provider().model_config is NANO_BANANA_PRO_EDIT
    clip = train_car.SPECS["clip03"]
    video = pipeline.default_video_provider(clip)
    assert video.model_config.submit_path == "alibaba/wan-3.0/image-to-video"
    assert video.model_config.extra_payload["duration"] == 6
    assert video.model_config.end_image_param_name == "end_image_url"


def test_generate_request_shape_sent_to_fal(tmp_path):
    """cp01_still's live request, captured by a fake transport: aspect_ratio + resolution, no width/height."""
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/fal-ai/nano-banana-pro" and request.method == "POST":
            seen.update(json.loads(request.content))
            return httpx.Response(200, json={"images": [{"url": "https://fake-cdn.example/cp01.png"}]})
        if str(request.url) == "https://fake-cdn.example/cp01.png":
            return httpx.Response(200, content=b"png bytes")
        raise AssertionError(f"Unexpected request: {request.method} {request.url}")

    from app.providers.image.fal import FalImageProvider

    provider = FalImageProvider(NANO_BANANA_PRO_GENERATE, api_key="fake-key",
                                client=httpx.Client(transport=httpx.MockTransport(handler)))
    manifest = tmp_path / "manifest.json"
    manifest.write_text(json.dumps({"budget_cap_usd": 15.0}))
    spec = train_car.SPECS["cp01_still"]
    import dataclasses

    spec = dataclasses.replace(spec, output_image_path=tmp_path / "cp01_still.jpg")
    result = pipeline.execute_generate(spec, image_provider=provider, manifest_path=manifest, log=lambda *_: None)

    assert seen["aspect_ratio"] == "9:16" and seen["resolution"] == "1K"
    assert "SKIP REPETITION, NOT EXPLANATION" in seen["prompt"]
    assert result["actual_cost_usd"] == pytest.approx(0.15)
    assert json.loads(manifest.read_text())["cp01_still"]["image_model"] == "fal-ai/nano-banana-pro"
