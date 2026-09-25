"""Higgsfield provider + clip03 proof runner, against a fake transport (no network, no cost)."""
import json
import shutil
from pathlib import Path

import httpx
import pytest

from app.providers.base import ProviderJobState, VideoGenerationRequest, VideoProviderError
from app.providers.video.higgsfield import KLING_O3_FIRST_LAST_FRAME, HiggsfieldVideoProvider
from scripts import run_train_car_higgsfield_proof as proof

REAL_SETUP = Path(proof.SETUP_PATH)
SUBMIT_URL = "https://api.higgsfield.ai/kling-video/o3/first-last-frame"


class FakeHiggsfield:
    def __init__(self, estimate_usd="0.5000", final_status="completed"):
        self.calls: list[tuple[str, str, dict | None]] = []
        self.estimate_usd, self.final_status = estimate_usd, final_status
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
            usd = self.estimate_usd if body.get("mode") == "pro" else "0.3000"
            return httpx.Response(200, json={"credits": "8.000", "usd": usd})
        if url.endswith("/kling-video/o3/first-last-frame"):
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


def _provider(fake):
    return HiggsfieldVideoProvider(api_key_id="kid", api_key_secret="ksecret",
                                   client=httpx.Client(transport=httpx.MockTransport(fake)))


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
    assert not any(url == SUBMIT_URL for _, url, _ in fake.calls)  # nothing submitted


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
    monkeypatch.setattr(proof, "RAW_OUTPUT", tmp_path / "clip03_higgsfield_raw.mp4")
    return manifest, setup


def test_prepare_is_free_and_uses_the_approved_stills_and_pinned_prompt(sandbox):
    manifest, setup = sandbox
    fake = FakeHiggsfield()
    prepared = proof.prepare(_provider(fake), json.loads(manifest.read_text()), setup, manifest)
    assert prepared["same_stills_as_wan_baseline"] is True
    assert prepared["start_frame"].endswith("cp02_still.jpg") and prepared["end_frame"].endswith("cp03_still.jpg")
    assert prepared["estimate_usd"] == 0.5 and prepared["estimate_std_usd"] == 0.3
    assert prepared["payload"]["prompt"] == setup["held_constant"]["prompt"]
    assert {k: prepared["payload"][k] for k in ("mode", "sound", "multi_shots", "duration", "aspect_ratio")} == \
        {"mode": "pro", "sound": "off", "multi_shots": False, "duration": 6, "aspect_ratio": "9:16"}
    assert not any(url == SUBMIT_URL for _, url, _ in fake.calls)
    assert "ksecret" not in json.dumps(prepared)


def test_prepare_refuses_a_still_changed_since_approval(sandbox):
    manifest, setup = sandbox
    (manifest.parent / "stills" / "cp03_still.jpg").write_bytes(b"swapped after approval")
    fake = FakeHiggsfield()
    with pytest.raises(proof.ProofError, match="not the file that was approved"):
        proof.prepare(_provider(fake), json.loads(manifest.read_text()), setup, manifest)
    assert fake.calls == []


def test_submit_refuses_above_approved_or_hard_cap(sandbox):
    manifest, setup = sandbox
    for fake, approve in ((FakeHiggsfield("0.5000"), 0.40), (FakeHiggsfield("1.2000"), 5.0)):
        with pytest.raises(proof.ProofError, match="not submitted"):
            proof.submit(_provider(fake), approve, manifest_path=manifest, setup=setup, log=lambda *_: None)
        assert not any(url == SUBMIT_URL for _, url, _ in fake.calls)


def test_submit_records_job_id_then_completes_and_never_resubmits(sandbox):
    manifest, setup = sandbox
    fake = FakeHiggsfield()
    entry = proof.submit(_provider(fake), 0.60, manifest_path=manifest, setup=setup, log=lambda *_: None,
                         poll_seconds=0)
    assert entry["provider_job_id"] == "req-1" and entry["actual_cost_usd"] == 0.5
    assert sum(url == SUBMIT_URL for _, url, _ in fake.calls) == 1
    with pytest.raises(proof.ProofError, match="already has provider job"):
        proof.submit(_provider(fake), 0.60, manifest_path=manifest, setup=setup, log=lambda *_: None)
    assert sum(url == SUBMIT_URL for _, url, _ in fake.calls) == 1


def test_config_is_kling_o3_first_last_frame():
    assert KLING_O3_FIRST_LAST_FRAME.endpoint_id == "kling-video/o3/first-last-frame"
    assert KLING_O3_FIRST_LAST_FRAME.static_payload == {"mode": "pro", "sound": "off", "multi_shots": False}
