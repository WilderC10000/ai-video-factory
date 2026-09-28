"""Higgsfield provider + clip03 proof runner, against a fake transport (no network, no cost)."""
import json
import shutil
from pathlib import Path

import httpx
import pytest

from app.providers.base import ProviderJobState, VideoGenerationRequest, VideoProviderError
from app.providers.video.higgsfield import (
    KLING_O3_FIRST_LAST_FRAME,
    SEEDANCE_2_5_IMAGE_TO_VIDEO,
    HiggsfieldVideoProvider,
)
from scripts import run_train_car_higgsfield_proof as proof

REAL_SETUP = Path(proof.SETUP_PATH)
SUBMIT_URLS = {"https://api.higgsfield.ai/kling-video/o3/first-last-frame",
               "https://api.higgsfield.ai/bytedance/seedance-2.5/image-to-video"}
STILL_9_16 = Path("data/train_car_video_2/stills/cp02_still.jpg")  # 768x1376


class FakeHiggsfield:
    def __init__(self, estimate_usd="0.5000", final_status="completed", description=None):
        self.calls: list[tuple[str, str, dict | None]] = []
        self.estimate_usd, self.final_status, self.description = estimate_usd, final_status, description
        self.uploads = 0

    def __call__(self, request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        body = json.loads(request.content) if request.content and request.method == "POST" else None
        self.calls.append((request.method, url, body))
        if request.method == "PUT":
            assert "Authorization" not in request.headers  # never send the key to presigned storage
            return httpx.Response(200)
        assert request.headers.get("Authorization") == "Key kid:ksecret" or "cdn.test" in url
        if url.endswith("/files/generate-upload-url"):
            self.uploads += 1
            return httpx.Response(200, json={"public_url": f"https://cdn.test/in{self.uploads}.jpg",
                                             "upload_url": f"https://store.test/up{self.uploads}?sig=x",
                                             "upload_headers": {"Content-Type": "image/jpeg",
                                                                "x-amz-tagging": "retention=temporary"}})
        if "/estimate/" in url:
            if self.description is not None:  # token-priced models answer with a description
                return httpx.Response(200, json={"type": "description", "pricing_description": self.description})
            usd = ({"std": "0.3000"}.get(body.get("mode")) or {"720p": "0.9000"}.get(body.get("resolution"))
                   or self.estimate_usd)
            return httpx.Response(200, json={"credits": "8.000", "usd": usd})
        if url in SUBMIT_URLS:
            return httpx.Response(200, json={"status": "queued", "request_id": "req-1",
                                             "status_url": "https://api.higgsfield.ai/requests/req-1/status",
                                             "cancel_url": "https://api.higgsfield.ai/requests/req-1/cancel"})
        if url.endswith("/requests/req-1/status"):
            if self.final_status == "completed":
                return httpx.Response(200, json={"status": "completed", "request_id": "req-1",
                                                 "video": {"url": "https://cdn.test/out.mp4"}})
            return httpx.Response(200, json={"status": self.final_status, "error": "boom"})
        if url == "https://cdn.test/out.mp4":
            return httpx.Response(200, content=b"mp4")
        return httpx.Response(404, text=f"unexpected {url}")


def _provider(fake, config=KLING_O3_FIRST_LAST_FRAME):
    return HiggsfieldVideoProvider(config, api_key_id="kid", api_key_secret="ksecret",
                                   client=httpx.Client(transport=httpx.MockTransport(fake)),
                                   allow_retired_submit=True)  # exercising the retained code path


def _setup_provider(fake, setup):
    return proof.model_provider(setup, api_key_id="kid", api_key_secret="ksecret",
                                client=httpx.Client(transport=httpx.MockTransport(fake)), allow_retired_submit=True)


@pytest.fixture
def frames(tmp_path):
    a, b = tmp_path / "a.jpg", tmp_path / "b.jpg"
    a.write_bytes(b"start")
    b.write_bytes(b"end")
    return a, b


def test_payload_matches_the_kling_o3_first_last_frame_schema(frames):
    fake = FakeHiggsfield()
    payload = _provider(fake).build_payload(VideoGenerationRequest(
        prompt="p", reference_image_path=str(frames[0]), end_image_path=str(frames[1]),
        duration_seconds=6.0, aspect_ratio="9:16"))
    assert payload == {"prompt": "p", "first_frame_url": "https://cdn.test/in1.jpg",
                       "last_frame_url": "https://cdn.test/in2.jpg", "aspect_ratio": "9:16", "duration": 6,
                       "mode": "pro", "sound": "off", "multi_shots": False}
    assert not any(url in SUBMIT_URLS for _, url, _ in fake.calls)  # nothing submitted


@pytest.mark.parametrize("change, match", [
    ({"duration_seconds": 6.5}, "whole-second"), ({"duration_seconds": 20.0}, "whole-second"),
    ({"aspect_ratio": "4:5"}, "aspect ratio"), ({"prompt": "x" * 2501}, "truncat"),
    ({"reference_image_path": None}, "first frame")])
def test_invalid_requests_are_refused_not_altered(frames, change, match):
    base = dict(prompt="p", reference_image_path=str(frames[0]), end_image_path=str(frames[1]),
                duration_seconds=6.0, aspect_ratio="9:16")
    with pytest.raises(VideoProviderError, match=match):
        _provider(FakeHiggsfield()).build_payload(VideoGenerationRequest(**(base | change)))


def test_missing_keys_refuse_before_any_call(frames, monkeypatch):
    from app.config import settings
    monkeypatch.setattr(settings, "hf_api_key_id", None)
    monkeypatch.setattr(settings, "hf_api_key_secret", None)
    monkeypatch.setattr(settings, "hf_key", None)
    fake = FakeHiggsfield()
    provider = HiggsfieldVideoProvider(client=httpx.Client(transport=httpx.MockTransport(fake)))
    with pytest.raises(VideoProviderError, match="HF_KEY"):
        provider.upload_image(frames[0])
    assert fake.calls == []


def test_hf_key_is_read_as_id_colon_secret(monkeypatch):
    from app.config import settings
    from app.providers.video.higgsfield import _split_key

    assert _split_key("kid:ksecret") == ("kid", "ksecret")
    assert _split_key(' "kid:ksecret" ') == ("kid", "ksecret")
    for bad in (None, "", "no-separator", ":secret", "kid:", "a:b:c"):
        assert _split_key(bad) == (None, None)
    monkeypatch.setattr(settings, "hf_api_key_id", None)
    monkeypatch.setattr(settings, "hf_api_key_secret", None)
    monkeypatch.setattr(settings, "hf_key", "kid:ksecret")
    fake = FakeHiggsfield()
    provider = HiggsfieldVideoProvider(client=httpx.Client(transport=httpx.MockTransport(fake)))
    assert provider.get_job_status("req-1").status == ProviderJobState.COMPLETED  # sent "Key kid:ksecret"


def test_seedance_payload_matches_its_schema(tmp_path):
    end = STILL_9_16.with_name("cp03_still.jpg")
    payload = _provider(FakeHiggsfield(), SEEDANCE_2_5_IMAGE_TO_VIDEO).build_payload(VideoGenerationRequest(
        prompt="p", reference_image_path=str(STILL_9_16), end_image_path=str(end), duration_seconds=6.0,
        aspect_ratio="9:16", extra_params={"resolution": "480p", "generate_audio": False}))
    # No aspect_ratio / mode / sound: the endpoint rejects unknown fields (additionalProperties: false).
    assert payload == {"prompt": "p", "image_url": "https://cdn.test/in1.jpg", "end_image_url": "https://cdn.test/in2.jpg",
                       "duration": 6, "resolution": "480p", "generate_audio": False}


def test_seedance_refuses_wrong_shape_start_frame_and_foreign_fields(tmp_path):
    square = tmp_path / "square.png"
    square.write_bytes(bytes.fromhex("89504e470d0a1a0a0000000d49484452") + (512).to_bytes(4, "big") * 2 + bytes(16))
    provider = _provider(FakeHiggsfield(), SEEDANCE_2_5_IMAGE_TO_VIDEO)
    with pytest.raises(VideoProviderError, match="framing follows the first frame"):
        provider.build_payload(VideoGenerationRequest(prompt="p", reference_image_path=str(square),
                                                      duration_seconds=6.0, aspect_ratio="9:16"))
    with pytest.raises(VideoProviderError, match="does not accept"):
        provider.build_payload(VideoGenerationRequest(prompt="p", reference_image_path=str(STILL_9_16),
                                                      duration_seconds=6.0, aspect_ratio="9:16",
                                                      extra_params={"mode": "pro"}))


def test_status_mapping(frames):
    ok = _provider(FakeHiggsfield()).get_job_status("req-1")
    assert ok.status == ProviderJobState.COMPLETED and ok.output_url == "https://cdn.test/out.mp4"
    for terminal in ("failed", "nsfw", "canceled"):
        bad = _provider(FakeHiggsfield(final_status=terminal)).get_job_status("req-1")
        assert bad.status == ProviderJobState.FAILED and bad.actual_cost_usd == 0.0


# --- proof runner ---------------------------------------------------------------------------------

@pytest.fixture
def sandbox(tmp_path, monkeypatch):
    """A copy of the train-car stills folder with cp02/cp03 approved, as the manual workflow leaves it."""
    from scripts import run_train_car_video_2_plan as plan

    setup = json.loads(REAL_SETUP.read_text())
    stills = tmp_path / "stills"
    stills.mkdir()
    entries = {}
    for key, label in (("cp02_still", "start_frame"), ("cp03_still", "end_frame")):
        dest = stills / f"{key}.jpg"
        shutil.copy(setup["held_constant"][label]["path"], dest)
        entries[key] = {"output_path": str(dest), "completed_at": "2026-09-24T00:00:00+00:00",
                        "actual_cost_usd": 0.45,
                        "approved_sha256": setup["held_constant"][label]["sha256"], "approved_via": "manual"}
    manifest = tmp_path / "manifest.json"
    manifest.write_text(json.dumps({"budget_cap_usd": 15.0, **entries,
                                    "clip03": {"video_prompt": setup["held_constant"]["prompt"]}}))
    monkeypatch.setattr(plan, "STILLS_SOURCE", "manual")
    monkeypatch.setattr(proof, "JOB_PATH", tmp_path / "job.json")
    monkeypatch.setattr(proof, "CLIPS_DIR", tmp_path / "clips")
    return manifest, setup


def test_prepare_is_free_and_uses_the_approved_stills_and_pinned_prompt(sandbox):
    manifest, setup = sandbox
    fake = FakeHiggsfield()
    prepared = proof.prepare(_setup_provider(fake, setup), json.loads(manifest.read_text()), setup, manifest)
    assert prepared["same_stills_as_wan_baseline"] is True and prepared["model"] == setup["model"]["endpoint_id"]
    assert prepared["start_frame"].endswith("cp02_still.jpg") and prepared["end_frame"].endswith("cp03_still.jpg")
    assert prepared["estimate_usd"] == 0.5 and prepared["compare_estimates_usd"] == {"720p": 0.9}
    assert prepared["payload"] == {
        "prompt": setup["held_constant"]["prompt"], "image_url": "https://cdn.test/in1.jpg",
        "end_image_url": "https://cdn.test/in2.jpg", "duration": 6, "resolution": "480p", "generate_audio": False}
    assert not any(url in SUBMIT_URLS for _, url, _ in fake.calls)
    assert "ksecret" not in json.dumps(prepared)


def test_prepare_refuses_a_still_changed_since_approval(sandbox):
    manifest, setup = sandbox
    (manifest.parent / "stills" / "cp03_still.jpg").write_bytes(b"swapped after approval")
    fake = FakeHiggsfield()
    with pytest.raises(proof.ProofError, match="not the file that was approved"):
        proof.prepare(_setup_provider(fake, setup), json.loads(manifest.read_text()), setup, manifest)
    assert fake.calls == []


def test_submit_refuses_above_approved_or_hard_cap(sandbox):
    manifest, setup = sandbox
    for fake, approve in ((FakeHiggsfield("0.5000"), 0.40), (FakeHiggsfield("1.4000"), 5.0)):
        with pytest.raises(proof.ProofError, match="not submitted"):
            proof.submit(_setup_provider(fake, setup), approve, manifest_path=manifest, setup=setup,
                         log=lambda *_: None)
        assert not any(url in SUBMIT_URLS for _, url, _ in fake.calls)


def test_submit_records_job_id_then_completes_and_never_resubmits(sandbox):
    manifest, setup = sandbox
    fake = FakeHiggsfield()
    entry = proof.submit(_setup_provider(fake, setup), 0.60, manifest_path=manifest, setup=setup, log=lambda *_: None,
                         poll_seconds=0)
    assert entry["provider_job_id"] == "req-1" and entry["actual_cost_usd"] == 0.5
    assert sum(url in SUBMIT_URLS for _, url, _ in fake.calls) == 1
    with pytest.raises(proof.ProofError, match="already exists"):
        proof.submit(_setup_provider(fake, setup), 0.60, manifest_path=manifest, setup=setup, log=lambda *_: None)
    assert sum(url in SUBMIT_URLS for _, url, _ in fake.calls) == 1


def test_config_is_kling_o3_first_last_frame():
    assert KLING_O3_FIRST_LAST_FRAME.endpoint_id == "kling-video/o3/first-last-frame"
    assert KLING_O3_FIRST_LAST_FRAME.static_payload == {"mode": "pro", "sound": "off", "multi_shots": False}


# --- token-priced estimate (Seedance 2.5), approved amount, local final check -----------------------

DESCRIPTION = "For 16:9 video without video input, your request costs roughly $0.2056 per second of generated video at 480p, $0.4622 at 720p, and $1.1372 at 1080p. Each 1,000 video tokens costs $0.0214 at 480p or 720p and $0.0234 at 1080p."


def test_token_priced_estimate_uses_the_published_rate_upper_bound():
    provider = _provider(FakeHiggsfield(description=DESCRIPTION), SEEDANCE_2_5_IMAGE_TO_VIDEO)
    est = provider.estimate_payload({"duration": 6, "resolution": "480p"})
    assert est["tokens"] == 58320 and est["usd"] == 1.248  # ceil(480 x 864 x 6 x 24 / 1024) x $0.0214/1k
    assert "upper bound" in est["basis"]


def test_token_priced_estimate_refuses_if_the_published_rate_changed():
    provider = _provider(FakeHiggsfield(description=DESCRIPTION.replace("$0.0214", "$0.0300")),
                         SEEDANCE_2_5_IMAGE_TO_VIDEO)
    with pytest.raises(VideoProviderError, match="pricing changed"):
        provider.estimate_payload({"duration": 6, "resolution": "480p"})


def test_submit_respects_the_approved_amount_in_setup(sandbox):
    manifest, setup = sandbox
    assert proof.max_approved_usd(setup) == 1.30
    fake = FakeHiggsfield(description=DESCRIPTION)  # $1.2480
    tight = setup | {"cost": {"max_approved_usd": 1.20}}
    with pytest.raises(proof.ProofError, match="approved for this proof"):
        proof.submit(_setup_provider(fake, tight), 5.0, manifest_path=manifest, setup=tight, log=lambda *_: None)
    with pytest.raises(proof.ProofError, match="no cost.max_approved_usd"):
        proof.max_approved_usd(setup | {"cost": {}})
    assert not any(url in SUBMIT_URLS for _, url, _ in fake.calls)


def test_submit_refuses_when_a_job_file_already_exists(sandbox):
    manifest, setup = sandbox
    proof.JOB_PATH.write_text("{}")
    fake = FakeHiggsfield(description=DESCRIPTION)
    with pytest.raises(proof.ProofError, match="already exists"):
        proof.submit(_setup_provider(fake, setup), 1.30, manifest_path=manifest, setup=setup, log=lambda *_: None)
    assert fake.calls == []


def test_final_check_is_local_and_reports_each_condition(sandbox, monkeypatch):
    manifest, setup = sandbox
    monkeypatch.setattr(httpx.Client, "send", lambda *a, **k: pytest.fail("final_check made a network call"))
    checks = proof.final_check(setup, manifest)
    for name in ("model", "settings", "prompt", "start still", "end still", "no other Higgsfield job", "spend",
                 "proof gate closed", "approved amount"):
        assert checks[name][0], (name, checks[name])
    (manifest.parent / "stills" / "cp02_still.jpg").write_bytes(b"swapped")
    assert not proof.final_check(setup, manifest)["stills"][0]


# --- retired 2026-09-28: recovery only --------------------------------------------------------------

def test_retired_provider_refuses_to_submit_without_any_call(frames):
    fake = FakeHiggsfield()
    provider = HiggsfieldVideoProvider(api_key_id="kid", api_key_secret="ksecret",
                                       client=httpx.Client(transport=httpx.MockTransport(fake)))
    with pytest.raises(VideoProviderError, match="retired"):
        provider.submit_video_job(VideoGenerationRequest(prompt="p", reference_image_path=str(frames[0]),
                                                         end_image_path=str(frames[1]), duration_seconds=5.0))
    assert fake.calls == []


def test_retired_runner_refuses_submit_but_still_recovers(sandbox):
    manifest, setup = sandbox
    fake = FakeHiggsfield()
    retired = proof.model_provider(setup, api_key_id="kid", api_key_secret="ksecret",
                                   client=httpx.Client(transport=httpx.MockTransport(fake)))
    with pytest.raises(proof.ProofError, match="retired"):
        proof.submit(retired, 5.0, manifest_path=manifest, setup=setup, log=lambda *_: None)
    assert fake.calls == []
    data = json.loads(manifest.read_text())
    data[proof.ENTRY_KEY] = {"provider": "higgsfield", "video_model": setup["model"]["endpoint_id"],
                             "provider_job_id": "req-1", "meta": {}, "estimated_cost_usd": 0.5}
    manifest.write_text(json.dumps(data))
    entry = proof.recover(retired, manifest_path=manifest, log=lambda *_: None, poll_seconds=0,
                          output=manifest.parent / "out.mp4")
    assert entry["actual_cost_usd"] == 0.5 and not any(url in SUBMIT_URLS for _, url, _ in fake.calls)
