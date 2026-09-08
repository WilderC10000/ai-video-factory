"""Tests for the real (not-yet-invoked) fal.ai adapters.

These never touch the network. `httpx.MockTransport` lets us verify the
adapters' request construction and response parsing against fake responses
shaped like fal.ai's documented API (queue submit/status/result for video,
synchronous inference for images) - this is how we "test everything
locally" even for code that talks to a real HTTP API, so the very first
live call is as low-risk as we can make it without actually spending money.
"""
import json

import httpx
import pytest

from app.providers.base import ImageGenerationRequest, ImageProviderError, VideoGenerationRequest, VideoProviderError
from app.providers.image.fal import FLUX_PRO, FLUX_SCHNELL, FalImageProvider
from app.providers.video.fal import KLING_2_6_PRO, VEO_3_1_FAST, WAN_STANDARD, WAN_TURBO, FalVideoProvider


def _refuse_any_request(request: httpx.Request) -> httpx.Response:
    raise AssertionError(f"No network call should have been made, but got: {request.method} {request.url}")


# ---------------------------------------------------------------------------
# Cost estimation - pure logic, no network involved either way.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "resolution,expected",
    [("480p", 0.05), ("580p", 0.075), ("720p", 0.10)],
)
def test_turbo_pricing_is_flat_per_video(resolution, expected):
    provider = FalVideoProvider(WAN_TURBO, api_key="fake-key")
    request = VideoGenerationRequest(prompt="p", extra_params={"resolution": resolution})
    assert provider.estimate_cost(request) == pytest.approx(expected)


def test_standard_pricing_scales_with_duration():
    provider = FalVideoProvider(WAN_STANDARD, api_key="fake-key")
    request = VideoGenerationRequest(prompt="p", duration_seconds=5.0, extra_params={"resolution": "480p"})
    assert provider.estimate_cost(request) == pytest.approx(0.20)


def test_image_pricing_matches_flux_schnell():
    provider = FalImageProvider(FLUX_SCHNELL, api_key="fake-key")
    request = ImageGenerationRequest(prompt="p", width=576, height=1024)  # 0.59MP -> rounds up to 1MP
    assert provider.estimate_cost(request) == pytest.approx(0.003)


# ---------------------------------------------------------------------------
# Missing API key fails fast, before any network call is attempted.
# ---------------------------------------------------------------------------


def test_video_submit_without_api_key_makes_no_network_call():
    client = httpx.Client(transport=httpx.MockTransport(_refuse_any_request))
    provider = FalVideoProvider(WAN_TURBO, api_key=None, client=client)
    request = VideoGenerationRequest(prompt="p", reference_image_path="/tmp/does-not-matter.jpg")

    with pytest.raises(VideoProviderError, match="FAL_API_KEY"):
        provider.submit_video_job(request)


def test_image_generate_without_api_key_makes_no_network_call(tmp_path):
    client = httpx.Client(transport=httpx.MockTransport(_refuse_any_request))
    provider = FalImageProvider(FLUX_SCHNELL, api_key=None, client=client)
    request = ImageGenerationRequest(prompt="p")

    with pytest.raises(ImageProviderError, match="FAL_API_KEY"):
        provider.generate_image(request, str(tmp_path / "out.jpg"))


# ---------------------------------------------------------------------------
# Full request/response cycles against fake responses shaped like fal.ai's
# documented schemas.
# ---------------------------------------------------------------------------


def test_full_video_submit_poll_download_cycle(tmp_path):
    status_calls = {"count": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path

        if path == "/storage/upload/initiate":
            body = json.loads(request.content)
            assert body["content_type"] == "image/jpeg"
            return httpx.Response(
                200, json={"upload_url": "https://fake-upload.example/put-me", "file_url": "https://fake-cdn.example/ref.jpg"}
            )

        if str(request.url) == "https://fake-upload.example/put-me":
            assert request.method == "PUT"
            return httpx.Response(200)

        # Submission uses the full path WITH the "turbo" subpath...
        if path == "/fal-ai/wan/v2.2-a14b/image-to-video/turbo" and request.method == "POST":
            body = json.loads(request.content)
            assert body["image_url"] == "https://fake-cdn.example/ref.jpg"
            assert body["resolution"] == "480p"
            assert body["prompt"] == "a pink submarine backyard bunker"
            return httpx.Response(
                200,
                json={
                    "request_id": "req-123",
                    "status_url": "https://queue.fal.run/fal-ai/wan/requests/req-123/status",
                    "response_url": "https://queue.fal.run/fal-ai/wan/requests/req-123",
                },
            )

        # ...but status/result routing must use ONLY owner/alias ("fal-ai/wan"),
        # not "turbo" and not "v2.2-a14b/image-to-video" either. Verified
        # against fal.ai's own official Python client source
        # (fal_client.client.AppId.from_endpoint_id): only the first two
        # path segments matter for the queue's request tracking. Two real
        # bugs produced a live HTTP 405 before this was right - these paths
        # are the regression guard.
        if path == "/fal-ai/wan/requests/req-123/status":
            status_calls["count"] += 1
            if status_calls["count"] == 1:
                return httpx.Response(200, json={"status": "IN_PROGRESS"})
            return httpx.Response(200, json={"status": "COMPLETED"})

        if path == "/fal-ai/wan/requests/req-123" and request.method == "GET":
            return httpx.Response(200, json={"video": {"url": "https://fake-cdn.example/clip.mp4"}})

        if str(request.url) == "https://fake-cdn.example/clip.mp4":
            return httpx.Response(200, content=b"fake mp4 bytes")

        raise AssertionError(f"Unexpected request: {request.method} {request.url}")

    client = httpx.Client(transport=httpx.MockTransport(handler))
    provider = FalVideoProvider(WAN_TURBO, api_key="fake-key", client=client)

    ref_image = tmp_path / "ref.jpg"
    ref_image.write_bytes(b"fake jpeg bytes")

    request = VideoGenerationRequest(
        prompt="a pink submarine backyard bunker",
        reference_image_path=str(ref_image),
        extra_params={"resolution": "480p"},
    )

    submitted = provider.submit_video_job(request)
    assert submitted.provider_job_id == "req-123"
    assert submitted.estimated_cost_usd == pytest.approx(0.05)

    # No meta passed here - this exercises the FALLBACK (queue_app_id)
    # path, not the preferred server-provided-URL path (see the dedicated
    # test below for that one).
    status1 = provider.get_job_status("req-123")
    assert status1.status.value == "PROCESSING"

    status2 = provider.get_job_status("req-123")
    assert status2.status.value == "COMPLETED"
    assert status2.output_url == "https://fake-cdn.example/clip.mp4"

    dest = tmp_path / "downloaded.mp4"
    local_path = provider.download_result("req-123", status2.output_url, str(dest))
    assert local_path == str(dest)
    assert dest.read_bytes() == b"fake mp4 bytes"


def test_get_job_status_prefers_server_provided_urls_over_reconstruction():
    """This is the more important, more robust path - the same approach
    fal.ai's own official client uses (store and reuse status_url/
    response_url from the submission response, don't reconstruct). The
    handler here ONLY recognizes an oddball URL shape that no formula
    would derive from the model id, proving the provider used exactly the
    URL handed to it in `meta` rather than building one itself."""

    def handler(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        if url == "https://queue.fal.run/totally/custom/status/path":
            return httpx.Response(200, json={"status": "COMPLETED"})
        if url == "https://queue.fal.run/totally/custom/result/path":
            return httpx.Response(200, json={"video": {"url": "https://fake-cdn.example/clip.mp4"}})
        raise AssertionError(f"Unexpected request (meta URLs were not used): {request.method} {url}")

    client = httpx.Client(transport=httpx.MockTransport(handler))
    provider = FalVideoProvider(WAN_TURBO, api_key="fake-key", client=client)

    meta = {
        "status_url": "https://queue.fal.run/totally/custom/status/path",
        "response_url": "https://queue.fal.run/totally/custom/result/path",
    }
    result = provider.get_job_status("req-999", meta=meta)
    assert result.status.value == "COMPLETED"
    assert result.output_url == "https://fake-cdn.example/clip.mp4"


def test_video_job_reported_as_failed_by_provider():
    def handler(request: httpx.Request) -> httpx.Response:
        # owner/alias only ("fal-ai/wan") - see the regression note in
        # test_full_video_submit_poll_download_cycle.
        if request.url.path == "/fal-ai/wan/requests/req-456/status":
            return httpx.Response(200, json={"status": "ERROR", "error": "content policy violation"})
        raise AssertionError(f"Unexpected request: {request.method} {request.url}")

    client = httpx.Client(transport=httpx.MockTransport(handler))
    provider = FalVideoProvider(WAN_TURBO, api_key="fake-key", client=client)

    result = provider.get_job_status("req-456")
    assert result.status.value == "FAILED"
    assert "ERROR" in result.error_message


def test_queue_app_id_strips_everything_but_owner_and_alias():
    assert WAN_TURBO.queue_app_id == "fal-ai/wan"
    assert WAN_STANDARD.queue_app_id == "fal-ai/wan"
    assert WAN_TURBO.submit_path == "fal-ai/wan/v2.2-a14b/image-to-video/turbo"


def test_submit_passes_through_whitelisted_generation_controls(tmp_path):
    """enable_prompt_expansion=False (and seed) are how a multi-stage
    continuity chain reduces fal.ai's own prompt rewriting from being an
    extra source of drift between stages - confirms these reach the actual
    request body."""

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/storage/upload/initiate":
            return httpx.Response(
                200, json={"upload_url": "https://fake-upload.example/put", "file_url": "https://fake-cdn.example/ref.jpg"}
            )
        if str(request.url) == "https://fake-upload.example/put":
            return httpx.Response(200)
        if request.url.path == "/fal-ai/wan/v2.2-a14b/image-to-video/turbo":
            body = json.loads(request.content)
            assert body["enable_prompt_expansion"] is False
            assert body["seed"] == 42
            assert "resolution" not in body or body["resolution"] == "480p"  # not double-set
            return httpx.Response(200, json={"request_id": "req-1"})
        raise AssertionError(f"Unexpected request: {request.method} {request.url}")

    client = httpx.Client(transport=httpx.MockTransport(handler))
    provider = FalVideoProvider(WAN_TURBO, api_key="fake-key", client=client)

    ref_image = tmp_path / "ref.jpg"
    ref_image.write_bytes(b"fake jpeg bytes")

    request = VideoGenerationRequest(
        prompt="p",
        reference_image_path=str(ref_image),
        extra_params={"resolution": "480p", "enable_prompt_expansion": False, "seed": 42},
    )
    provider.submit_video_job(request)


def test_full_image_generation_cycle(tmp_path):
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/fal-ai/flux/schnell" and request.method == "POST":
            body = json.loads(request.content)
            assert body["prompt"] == "a pink submarine, reference frame"
            assert body["image_size"] == {"width": 576, "height": 1024}
            return httpx.Response(
                200,
                json={
                    "images": [{"url": "https://fake-cdn.example/gen.jpg", "width": 576, "height": 1024}],
                    "seed": 42,
                },
            )
        if str(request.url) == "https://fake-cdn.example/gen.jpg":
            return httpx.Response(200, content=b"fake jpeg bytes")
        raise AssertionError(f"Unexpected request: {request.method} {request.url}")

    client = httpx.Client(transport=httpx.MockTransport(handler))
    provider = FalImageProvider(FLUX_SCHNELL, api_key="fake-key", client=client)

    request = ImageGenerationRequest(prompt="a pink submarine, reference frame")
    dest = tmp_path / "ref.jpg"

    result = provider.generate_image(request, str(dest))

    assert result.cost_usd == pytest.approx(0.003)
    assert dest.read_bytes() == b"fake jpeg bytes"
    assert result.meta["seed"] == 42


# ---------------------------------------------------------------------------
# Quality bake-off candidates: Kling 2.6 Pro and Veo 3.1 Fast. Each has real,
# verified differences from Wan's request shape (image field name, whether
# resolution is even selectable, duration format) - these tests exist
# specifically to catch getting any of those wrong before a real call.
# ---------------------------------------------------------------------------


def test_flux_pro_pricing_uses_higher_rate_than_schnell():
    provider = FalImageProvider(FLUX_PRO, api_key="fake-key")
    request = ImageGenerationRequest(prompt="p", width=576, height=1024)  # 0.59MP -> rounds up to 1MP
    assert provider.estimate_cost(request) == pytest.approx(0.04)


def test_kling_pricing_is_per_second_with_no_resolution_tiers():
    provider = FalVideoProvider(KLING_2_6_PRO, api_key="fake-key")
    request = VideoGenerationRequest(prompt="p", duration_seconds=5.0)
    assert provider.estimate_cost(request) == pytest.approx(0.35)


def test_veo_pricing_identical_at_720p_and_1080p():
    provider = FalVideoProvider(VEO_3_1_FAST, api_key="fake-key")
    request_720 = VideoGenerationRequest(prompt="p", duration_seconds=6.0, extra_params={"resolution": "720p"})
    request_1080 = VideoGenerationRequest(prompt="p", duration_seconds=6.0, extra_params={"resolution": "1080p"})
    assert provider.estimate_cost(request_720) == pytest.approx(0.60)
    assert provider.estimate_cost(request_1080) == pytest.approx(0.60)


def test_kling_submit_uses_start_image_url_and_omits_resolution(tmp_path):
    """Kling's image field is named differently from Wan's, and it has no
    selectable resolution param at all - both are genuine differences this
    test exists to lock in, not assumptions carried over from Wan."""

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/storage/upload/initiate":
            return httpx.Response(
                200, json={"upload_url": "https://fake-upload.example/put", "file_url": "https://fake-cdn.example/ref.jpg"}
            )
        if str(request.url) == "https://fake-upload.example/put":
            return httpx.Response(200)
        if request.url.path == "/fal-ai/kling-video/v2.6/pro/image-to-video" and request.method == "POST":
            body = json.loads(request.content)
            assert body["start_image_url"] == "https://fake-cdn.example/ref.jpg"
            assert "image_url" not in body
            assert "resolution" not in body
            assert body["duration"] == "5"
            assert body["generate_audio"] is False
            assert body["negative_prompt"] == "blur, distort, low quality"
            assert "cfg_scale" not in body  # documented default (0.5) applies; we don't override it
            return httpx.Response(200, json={"request_id": "kling-req-1"})
        raise AssertionError(f"Unexpected request: {request.method} {request.url}")

    client = httpx.Client(transport=httpx.MockTransport(handler))
    provider = FalVideoProvider(KLING_2_6_PRO, api_key="fake-key", client=client)

    ref_image = tmp_path / "ref.jpg"
    ref_image.write_bytes(b"fake jpeg bytes")
    request = VideoGenerationRequest(
        prompt="p", reference_image_path=str(ref_image), aspect_ratio="9:16", duration_seconds=5.0
    )
    submitted = provider.submit_video_job(request)
    assert submitted.provider_job_id == "kling-req-1"
    assert submitted.estimated_cost_usd == pytest.approx(0.35)


def test_veo_submit_uses_image_url_and_duration_with_s_suffix(tmp_path):
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/storage/upload/initiate":
            return httpx.Response(
                200, json={"upload_url": "https://fake-upload.example/put", "file_url": "https://fake-cdn.example/ref.jpg"}
            )
        if str(request.url) == "https://fake-upload.example/put":
            return httpx.Response(200)
        if request.url.path == "/fal-ai/veo3.1/fast/image-to-video" and request.method == "POST":
            body = json.loads(request.content)
            assert body["image_url"] == "https://fake-cdn.example/ref.jpg"
            assert body["resolution"] == "1080p"
            assert body["duration"] == "6s"
            assert body["generate_audio"] is False
            assert body["aspect_ratio"] == "9:16"
            return httpx.Response(200, json={"request_id": "veo-req-1"})
        raise AssertionError(f"Unexpected request: {request.method} {request.url}")

    client = httpx.Client(transport=httpx.MockTransport(handler))
    provider = FalVideoProvider(VEO_3_1_FAST, api_key="fake-key", client=client)

    ref_image = tmp_path / "ref.jpg"
    ref_image.write_bytes(b"fake jpeg bytes")
    request = VideoGenerationRequest(
        prompt="p", reference_image_path=str(ref_image), aspect_ratio="9:16", duration_seconds=6.0
    )
    submitted = provider.submit_video_job(request)
    assert submitted.provider_job_id == "veo-req-1"
    assert submitted.estimated_cost_usd == pytest.approx(0.60)


@pytest.mark.parametrize(
    "config,expected_queue_app_id",
    [(KLING_2_6_PRO, "fal-ai/kling-video"), (VEO_3_1_FAST, "fal-ai/veo3.1")],
)
def test_new_candidates_queue_routing_is_owner_alias_only(config, expected_queue_app_id):
    """Same owner/alias-only rule already verified against fal.ai's official
    client source for Wan - confirms it's applied consistently to the new
    candidates too, not re-guessed per model."""
    assert config.queue_app_id == expected_queue_app_id
    assert config.submit_path == config.base_model_id  # neither candidate uses a subpath
