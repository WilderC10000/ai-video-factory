"""fal clip03 proof runner (Kling v3 Standard, Tier 2 candidate) - fake transport, no network, no cost."""
import json
import shutil

import httpx
import pytest

from scripts import run_train_car_fal_proof as proof

REAL_SETUP_DIR = proof.DEFAULT_SETUP_DIR
SUBMIT_URL = "https://queue.fal.run/fal-ai/kling-video/v3/standard/image-to-video"


class FakeFal:
    def __init__(self, reject: bool = False):
        self.calls, self.reject, self.uploads = [], reject, 0

    def __call__(self, request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        self.calls.append((request.method, url))
        if url.endswith("/storage/upload/initiate"):
            self.uploads += 1
            return httpx.Response(200, json={"upload_url": f"https://up.test/{self.uploads}",
                                             "file_url": f"https://files.test/{self.uploads}.jpg"})
        if url.startswith("https://up.test/"):
            return httpx.Response(200)
        if url == SUBMIT_URL:
            if self.reject:
                return httpx.Response(422, json={"detail": "multi_prompt cannot be used with end_image_url"})
            return httpx.Response(200, json={"request_id": "r-1", "status_url": "https://q.test/status",
                                             "response_url": "https://q.test/result"})
        if url == "https://q.test/status":
            return httpx.Response(200, json={"status": "COMPLETED"})
        if url == "https://q.test/result":
            return httpx.Response(200, json={"video": {"url": "https://cdn.test/out.mp4"}})
        if url == "https://cdn.test/out.mp4":
            return httpx.Response(200, content=b"mp4")
        return httpx.Response(404, text=f"unexpected {url}")

    def submits(self):
        return sum(url == SUBMIT_URL for _, url in self.calls)


def _provider(fake, setup):
    return proof.provider_for(setup, api_key="fake-key", client=httpx.Client(transport=httpx.MockTransport(fake)))


@pytest.fixture
def sandbox(tmp_path, monkeypatch):
    """Copies of the approved cp02/cp03 stills + a manifest that approves them, and a setup folder."""
    from scripts import run_train_car_video_2_plan as plan

    real = json.loads(proof.MANIFEST_PATH.read_text())
    stills = tmp_path / "stills"
    stills.mkdir()
    entries = {}
    for key in ("cp02_still", "cp03_still"):
        dest = stills / f"{key}.jpg"
        shutil.copy(real[key]["output_path"], dest)
        entries[key] = {"output_path": str(dest), "approved_sha256": real[key]["approved_sha256"],
                        "approved_via": "manual", "actual_cost_usd": 0.15}
    manifest = tmp_path / "manifest.json"
    manifest.write_text(json.dumps({"budget_cap_usd": 15.0, **entries, "proof_gate": {"passed": False}}))
    setup_dir = tmp_path / "setup"
    setup_dir.mkdir()
    setup = json.loads((REAL_SETUP_DIR / "setup.json").read_text())
    setup["cost"] = setup["cost"] | {"max_approved_usd": None, "approved": None}  # each test approves explicitly
    # Shots within Kling's 512-character limit (the recorded attempt-4 shots are over it - see below).
    shots = [{"prompt": shot["prompt"][:500], "duration": shot["duration"]}
             for shot in setup["model"]["extra_params"]["multi_prompt"]]
    setup["model"] = setup["model"] | {"extra_params": setup["model"]["extra_params"] | {"multi_prompt": shots}}
    monkeypatch.setattr(plan, "STILLS_SOURCE", "manual")
    monkeypatch.setattr(proof, "CLIPS_DIR", tmp_path / "clips")
    return manifest, setup_dir, setup


def _prepare(fake, manifest, setup_dir, setup):
    prepared = proof.prepare(_provider(fake, setup), setup, manifest)
    (setup_dir / "prepared.json").write_text(json.dumps(prepared))
    return prepared


def _approved(setup, usd=0.51):
    return setup | {"cost": setup["cost"] | {"max_approved_usd": usd}}


def test_real_setup_is_a_three_beat_hard_cut_kling_proof_with_audio_off():
    setup = json.loads((REAL_SETUP_DIR / "setup.json").read_text())
    assert (setup["attempt_key"], setup["shot_class"]) == ("clip03__attempt4", "repetitive_labor")
    assert setup["cost"]["max_approved_usd"] in (None, 0.51)  # approved 2026-09-28: up to $0.51
    shots = setup["model"]["extra_params"]["multi_prompt"]
    assert [s["duration"] for s in shots] == [2, 2, 2] and setup["model"]["duration"] == 6
    assert shots[0]["prompt"].count("Opens exactly on the first image") == 1
    assert all("HARD JUMP CUT" in s["prompt"] for s in shots[1:])
    assert "Ends exactly on the last image" in shots[-1]["prompt"]
    assert all("Locked camera" in s["prompt"] and "bearded builder" in s["prompt"] for s in shots)
    assert proof.route_for(setup).status == "candidate_unproven"


def test_the_recorded_attempt_4_setup_is_now_refused_locally_for_its_shot_length():
    """clip03__attempt4 failed at fal with a 422: each Kling v3 multi_prompt shot is limited to 512
    characters (not in the schema). The same setup is now refused before any upload or submission."""
    setup = json.loads((REAL_SETUP_DIR / "setup.json").read_text())
    assert all(len(s["prompt"]) > 512 for s in setup["model"]["extra_params"]["multi_prompt"])
    fake = FakeFal()
    with pytest.raises(proof.VideoProviderError, match="512-character"):
        proof.prepare(_provider(fake, setup), setup)
    assert fake.calls == []


def test_prepare_uploads_stills_and_builds_the_exact_payload_without_generating(sandbox):
    manifest, setup_dir, setup = sandbox
    fake = FakeFal()
    prepared = _prepare(fake, manifest, setup_dir, setup)
    assert fake.submits() == 0 and fake.uploads == 2
    payload = prepared["payload"]
    assert payload["start_image_url"] == "https://files.test/1.jpg" and payload["end_image_url"] == "https://files.test/2.jpg"
    assert "prompt" not in payload and len(payload["multi_prompt"]) == 3
    assert payload["duration"] == "6" and payload["generate_audio"] is False and "aspect_ratio" not in payload
    assert prepared["estimate_usd"] == 0.504 and prepared["route_status"] == "candidate_unproven"
    assert "fake-key" not in json.dumps(prepared)


def test_submit_refuses_until_an_amount_is_approved_in_setup(sandbox):
    manifest, setup_dir, setup = sandbox
    fake = FakeFal()
    _prepare(fake, manifest, setup_dir, setup)
    with pytest.raises(proof.ProofError, match="approved amount: estimate \\$0.5040; approved none yet"):
        proof.submit(_provider(fake, setup), 0.60, setup=setup, setup_dir=setup_dir, manifest_path=manifest)
    with pytest.raises(proof.ProofError, match="above the approved \\$0.50"):
        proof.submit(_provider(fake, _approved(setup)), 0.50, setup=_approved(setup), setup_dir=setup_dir,
                     manifest_path=manifest)
    assert fake.submits() == 0


def test_submit_refuses_a_setup_or_still_changed_after_prepare(sandbox):
    manifest, setup_dir, setup = sandbox
    fake = FakeFal()
    _prepare(fake, manifest, setup_dir, setup)
    edited = _approved(setup)
    edited["model"] = edited["model"] | {"extra_params": edited["model"]["extra_params"] | {"shot_type": "intelligent"}}
    with pytest.raises(proof.ProofError, match="setup.json changed since --prepare"):
        proof.submit(_provider(fake, edited), 0.60, setup=edited, setup_dir=setup_dir, manifest_path=manifest)
    (manifest.parent / "stills" / "cp03_still.jpg").write_bytes(b"swapped")
    with pytest.raises(proof.ProofError, match="not the file that was approved|Approved stills required"):
        proof.submit(_provider(fake, _approved(setup)), 0.60, setup=_approved(setup), setup_dir=setup_dir,
                     manifest_path=manifest)
    assert fake.submits() == 0


def test_submit_sends_the_prepared_payload_verbatim_once_and_records_the_job_first(sandbox):
    manifest, setup_dir, setup = sandbox
    fake = FakeFal()
    prepared = _prepare(fake, manifest, setup_dir, setup)
    approved = _approved(setup)
    entry = proof.submit(_provider(fake, approved), 0.51, setup=approved, setup_dir=setup_dir, manifest_path=manifest,
                         log=lambda *_: None, poll_seconds=0)
    assert fake.submits() == 1 and entry["payload"] == prepared["payload"]
    assert entry["provider"] == "fal" and entry["provider_job_id"] == "r-1" and entry["actual_cost_usd"] == 0.504
    assert json.loads(manifest.read_text())["proof_gate"] == {"passed": False}  # never touched
    with pytest.raises(proof.ProofError, match="no earlier job"):
        proof.submit(_provider(fake, approved), 0.51, setup=approved, setup_dir=setup_dir, manifest_path=manifest)
    assert fake.submits() == 1


def test_a_rejected_submission_is_recorded_as_a_free_finding(sandbox):
    manifest, setup_dir, setup = sandbox
    fake = FakeFal(reject=True)
    _prepare(fake, manifest, setup_dir, setup)
    approved = _approved(setup)
    with pytest.raises(proof.ProofError, match="no job, not charged"):
        proof.submit(_provider(fake, approved), 0.51, setup=approved, setup_dir=setup_dir, manifest_path=manifest)
    assert "cannot be used with end_image_url" in (setup_dir / "submit_rejected.json").read_text()
    assert "clip03__attempt4" not in json.loads(manifest.read_text())


def test_a_job_that_finishes_with_a_validation_error_stops_the_runner_as_failed(sandbox):
    """Regression (clip03__attempt4, 2026-09-28): fal said COMPLETED, the result was a 422 (Kling
    multi_prompt shots over 512 characters). The runner must record it failed and stop - not poll forever."""
    manifest, setup_dir, setup = sandbox
    fake = FakeFal()
    _prepare(fake, manifest, setup_dir, setup)
    original = fake.__call__

    def with_422(request):
        if str(request.url) == "https://q.test/result":
            return httpx.Response(422, json={"detail": [{"msg": "Prompt must not exceed 512 characters."}]})
        return original(request)

    approved = _approved(setup)
    provider = proof.provider_for(approved, api_key="fake-key", client=httpx.Client(transport=httpx.MockTransport(with_422)))
    with pytest.raises(proof.ProofError, match="512 characters"):
        proof.submit(provider, 0.51, setup=approved, setup_dir=setup_dir, manifest_path=manifest,
                     log=lambda *_: None, poll_seconds=0, wait_seconds=5)
    entry = json.loads(manifest.read_text())["clip03__attempt4"]
    assert entry["status"] == "failed" and entry["actual_cost_usd"] is None and fake.submits() == 1
