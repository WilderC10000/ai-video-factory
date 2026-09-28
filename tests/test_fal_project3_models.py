"""Project #3 fal video configs + shot-class routing - fake transport only, no network, no cost."""
import json

import httpx
import pytest

from app.forma import routing
from app.forma.doctrine import SHOT_CLASSES
from app.providers.base import VideoGenerationRequest, VideoProviderError
from app.providers.video.fal import (
    FAL_VIDEO_MODELS,
    KLING_3_PRO,
    KLING_3_STANDARD,
    SEEDANCE_2_0,
    SEEDANCE_2_5,
    VEO_3_1_FAST_FIRST_LAST,
    WAN_3_0_STANDARD,
    FalVideoProvider,
)

# Input properties from fal's queue OpenAPI schema for each endpoint (fetched 2026-09-28 from
# https://fal.ai/api/openapi/queue/openapi.json?endpoint_id=<endpoint>). A payload may only use these.
SCHEMA_FIELDS = {
    KLING_3_STANDARD.submit_path: {"prompt", "multi_prompt", "start_image_url", "duration", "generate_audio", "end_image_url",
                       "elements", "shot_type", "negative_prompt", "cfg_scale"},
    VEO_3_1_FAST_FIRST_LAST.submit_path: {"prompt", "first_frame_url", "last_frame_url", "aspect_ratio", "duration",
                              "negative_prompt", "resolution", "generate_audio", "seed", "auto_fix",
                              "safety_tolerance"},
    SEEDANCE_2_0.submit_path: {"prompt", "image_url", "end_image_url", "resolution", "duration", "aspect_ratio",
                   "generate_audio", "end_user_id", "bitrate_mode", "codec"},
    SEEDANCE_2_5.submit_path: {"prompt", "image_url", "end_image_url", "resolution", "duration", "aspect_ratio",
                   "generate_audio", "end_user_id", "bitrate_mode", "codec", "draft"},
}
SCHEMA_FIELDS[KLING_3_PRO.submit_path] = SCHEMA_FIELDS[KLING_3_STANDARD.submit_path]

NEW = (KLING_3_STANDARD, KLING_3_PRO, VEO_3_1_FAST_FIRST_LAST, SEEDANCE_2_0, SEEDANCE_2_5)
SHOTS = [{"prompt": "shot one", "duration": 2}, {"prompt": "shot two", "duration": 2},
         {"prompt": "shot three", "duration": 2}]


def _req(tmp_path, **kw):
    a, b = tmp_path / "a.jpg", tmp_path / "b.jpg"
    a.write_bytes(b"start")
    b.write_bytes(b"end")
    base = dict(prompt="p", reference_image_path=str(a), end_image_path=str(b), duration_seconds=6.0)
    return VideoGenerationRequest(**(base | kw))


def _provider(config, handler=None):
    def refuse(request):
        raise AssertionError(f"no network expected: {request.method} {request.url}")
    return FalVideoProvider(config, api_key="fake-key", client=httpx.Client(transport=httpx.MockTransport(handler or refuse)))


@pytest.mark.parametrize("config", NEW, ids=lambda c: c.submit_path)
def test_payload_uses_only_schema_fields_and_audio_is_always_off(config, tmp_path):
    payload = _provider(config).build_payload(
        _req(tmp_path, extra_params={"generate_audio": True, "sound": True}), "https://f/a.jpg", "https://f/b.jpg")
    fields = SCHEMA_FIELDS[config.submit_path]
    assert set(payload) <= fields, set(payload) - fields
    assert payload["generate_audio"] is False
    assert payload[config.image_param_name] == "https://f/a.jpg"
    assert payload[config.end_image_param_name] == "https://f/b.jpg"


@pytest.mark.parametrize("config,expected", [
    (KLING_3_STANDARD, 0.504), (KLING_3_PRO, 0.672), (VEO_3_1_FAST_FIRST_LAST, 0.60),
    (SEEDANCE_2_0, 0.8165), (SEEDANCE_2_5, 1.248)], ids=lambda v: getattr(v, "submit_path", v))
def test_six_second_prices(config, expected, tmp_path):
    assert _provider(config).estimate_cost(_req(tmp_path)) == pytest.approx(expected, abs=1e-4)


def test_seedance_2_5_matches_the_higgsfield_charge_and_refuses_unpriced_1080p(tmp_path):
    provider = _provider(SEEDANCE_2_5)
    assert provider.estimate_cost(_req(tmp_path)) == 1.248  # clip03__attempt3 actual_cost_usd
    assert provider.estimate_cost(_req(tmp_path, extra_params={"resolution": "720p"})) == pytest.approx(2.7734, abs=1e-4)
    with pytest.raises(VideoProviderError, match="No pricing"):
        provider.estimate_cost(_req(tmp_path, extra_params={"resolution": "1080p"}))


def test_kling_multi_prompt_replaces_prompt_and_keeps_the_end_frame(tmp_path):
    payload = _provider(KLING_3_STANDARD).build_payload(
        _req(tmp_path, extra_params={"multi_prompt": SHOTS, "shot_type": "customize"}),
        "https://f/a.jpg", "https://f/b.jpg")
    assert payload == {
        "start_image_url": "https://f/a.jpg",
        "multi_prompt": [{"prompt": "shot one", "duration": "2"}, {"prompt": "shot two", "duration": "2"},
                         {"prompt": "shot three", "duration": "2"}],
        "end_image_url": "https://f/b.jpg", "duration": "6", "shot_type": "customize", "generate_audio": False}


@pytest.mark.parametrize("config,kw,match", [
    (KLING_3_STANDARD, {"extra_params": {"multi_prompt": SHOTS[:2]}}, "add up to 4 s"),
    (KLING_3_STANDARD, {"extra_params": {"multi_prompt": [{"prompt": " ", "duration": 6}]}}, "each with a prompt"),
    (SEEDANCE_2_5, {"extra_params": {"multi_prompt": SHOTS}}, "no multi_prompt"),
    (KLING_3_STANDARD, {"duration_seconds": 16.0}, "takes durations"),
    (VEO_3_1_FAST_FIRST_LAST, {"duration_seconds": 5.0}, "takes durations"),
    (VEO_3_1_FAST_FIRST_LAST, {"end_image_path": None}, "both a first and a last frame"),
    (SEEDANCE_2_0, {"duration_seconds": 6.5}, "takes durations"),
], ids=str)
def test_invalid_requests_are_refused_not_altered(config, kw, match, tmp_path):
    with pytest.raises(VideoProviderError, match=match):
        _provider(config).build_payload(_req(tmp_path, **kw), "https://f/a.jpg", "https://f/b.jpg")


def test_veo_and_seedance_request_shapes(tmp_path):
    veo = _provider(VEO_3_1_FAST_FIRST_LAST).build_payload(_req(tmp_path), "https://f/a.jpg", "https://f/b.jpg")
    assert veo == {"first_frame_url": "https://f/a.jpg", "prompt": "p", "aspect_ratio": "9:16",
                   "last_frame_url": "https://f/b.jpg", "resolution": "720p", "duration": "6s",
                   "generate_audio": False}
    s25 = _provider(SEEDANCE_2_5).build_payload(_req(tmp_path), "https://f/a.jpg", "https://f/b.jpg")
    assert "aspect_ratio" not in s25 and s25["duration"] == "6" and s25["resolution"] == "480p"
    s20 = _provider(SEEDANCE_2_0).build_payload(_req(tmp_path), "https://f/a.jpg", None)
    assert s20["aspect_ratio"] == "9:16" and "end_image_url" not in s20


def test_queue_routing_is_owner_alias_only():
    assert KLING_3_STANDARD.queue_app_id == KLING_3_PRO.queue_app_id == "fal-ai/kling-video"
    assert VEO_3_1_FAST_FIRST_LAST.queue_app_id == "fal-ai/veo3.1"
    assert SEEDANCE_2_0.queue_app_id == "bytedance/seedance-2.0"
    assert SEEDANCE_2_5.queue_app_id == "bytedance/seedance-2.5"


def test_full_submit_uploads_both_frames_then_posts_the_built_payload(tmp_path):
    posted = []

    def handler(request):
        url = str(request.url)
        if url.endswith("/storage/upload/initiate"):
            n = len([p for p in posted if p[0] == "initiate"]) + 1
            posted.append(("initiate", None))
            return httpx.Response(200, json={"upload_url": f"https://up/{n}", "file_url": f"https://f/{n}.jpg"})
        if url.startswith("https://up/"):
            return httpx.Response(200)
        if url == "https://queue.fal.run/fal-ai/kling-video/v3/standard/image-to-video":
            posted.append(("submit", json.loads(request.content)))
            return httpx.Response(200, json={"request_id": "r1", "status_url": "s", "response_url": "r"})
        return httpx.Response(404)

    job = _provider(KLING_3_STANDARD, handler).submit_video_job(_req(tmp_path, extra_params={"multi_prompt": SHOTS}))
    body = [p for kind, p in posted if kind == "submit"]
    assert len(body) == 1 and body[0]["start_image_url"] == "https://f/1.jpg" and body[0]["end_image_url"] == "https://f/2.jpg"
    assert job.provider_job_id == "r1" and job.estimated_cost_usd == 0.504


def test_registry_holds_every_config_by_submit_path():
    for config in NEW + (WAN_3_0_STANDARD,):
        assert FAL_VIDEO_MODELS[config.submit_path] is config


# --- shot-class routing ----------------------------------------------------------------------------

def test_every_doctrine_shot_class_has_a_route_table_and_every_route_is_a_fal_model():
    assert set(routing.SHOT_ROUTES) == set(SHOT_CLASSES)
    for routes in routing.SHOT_ROUTES.values():
        for route in routes:
            assert route.model in FAL_VIDEO_MODELS and route.evidence
            assert route.status in routing.PROVEN + (routing.CANDIDATE_UNPROVEN, routing.FAILED)


def test_kling_v3_standard_is_a_candidate_not_proven_tier_2():
    kling = next(r for r in routing.routes("repetitive_labor") if r.model == KLING_3_STANDARD.submit_path)
    assert kling.status == routing.CANDIDATE_UNPROVEN
    with pytest.raises(routing.RoutingError, match="No proven model for repetitive_labor"):
        routing.select_video_model("repetitive_labor")
    assert routing.select_video_model("repetitive_labor", allow_unproven=True).model == KLING_3_STANDARD.submit_path


def test_seedance_2_5_is_proven_precision_and_wan_is_never_used_for_labor():
    route = routing.select_video_model("precision")
    assert (route.model, route.status) == (SEEDANCE_2_5.submit_path, routing.PROVEN_PRECISION)
    assert route.config is SEEDANCE_2_5
    for cls in ("repetitive_labor", "precision"):
        with pytest.raises(routing.RoutingError, match="not an allowed route"):
            routing.select_video_model(cls, allow_unproven=True, model=WAN_3_0_STANDARD.submit_path)
    assert routing.select_video_model("environmental").model == WAN_3_0_STANDARD.submit_path


def test_time_jumps_are_manual_stills_never_video():
    with pytest.raises(routing.RoutingError, match="manually in ChatGPT"):
        routing.select_video_model("time_jump")
    assert routing.STILL_SOURCE == "manual_chatgpt" and routing.VIDEO_PROVIDER == "fal"


def test_train_car_stills_stay_manual():
    from scripts import run_train_car_video_2_plan as plan
    assert plan.STILLS_SOURCE == "manual"
