"""Live status of provider attempts: persisted in the manifest, derived for the studio, checked for free.

Fake fal transport only - no network, no cost, and nothing here can submit a generation."""
import json
from datetime import datetime, timedelta, timezone

import httpx
import pytest

from app.providers.video.fal import KLING_3_STANDARD, FalVideoProvider
from app.studio import attempt_status as st
from app.studio.models import StudioProject
from app.studio.service import stage_attempts

KEY = "clip03__attempt4"
JOB = "01a0e9da-4874-7001-b5fc-a2be99b8f9ce"
SUBMIT = "https://queue.fal.run/fal-ai/kling-video/v3/standard/image-to-video"
LIMIT_422 = {"detail": [{"loc": ["body", "multi_prompt", 0, "prompt"],
                         "msg": "Value error, Prompt must not exceed 512 characters."}]}


class FakeFal:
    """fal queue for one Kling job: status goes through `statuses`, then the result."""

    def __init__(self, statuses=("IN_QUEUE",), result=(200, {"video": {"url": "https://cdn.test/out.mp4"}})):
        self.statuses, self.result, self.calls = list(statuses), result, []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        self.calls.append((request.method, url))
        assert url != SUBMIT, "a status check must never submit"
        if url == "https://q.test/status":
            status = self.statuses.pop(0) if len(self.statuses) > 1 else self.statuses[0]
            return httpx.Response(200, json={"status": status})
        if url == "https://q.test/result":
            return httpx.Response(self.result[0], json=self.result[1])
        if url == "https://cdn.test/out.mp4":
            return httpx.Response(200, content=b"mp4")
        return httpx.Response(404)


def _provider(fake):
    return FalVideoProvider(KLING_3_STANDARD, api_key="fake-key", client=httpx.Client(transport=httpx.MockTransport(fake)))


def _entry(**extra):
    return {"provider": "fal", "video_model": KLING_3_STANDARD.submit_path, "provider_job_id": JOB,
            "meta": {"status_url": "https://q.test/status", "response_url": "https://q.test/result"},
            "estimated_cost_usd": 0.504, "approved_usd": 0.51, "submitted_at": "2026-09-28T21:09:53+00:00",
            "payload": {"duration": "6", "generate_audio": False}, "raw_video_path": None,
            "actual_cost_usd": None, "completed_at": None, **extra}


@pytest.fixture
def manifest(tmp_path):
    path = tmp_path / "train_car_video_2" / "manifest.json"
    path.parent.mkdir()
    path.write_text(json.dumps({"budget_cap_usd": 15.0, "proof_gate": {"passed": False}, KEY: _entry()}))
    return path


def _read(path):
    return json.loads(path.read_text())


# --- phase derivation (what the snapshot shows, from persisted fields only) ----------------------------

@pytest.mark.parametrize("fields,exists,phase", [
    ({}, False, "submitted"),
    ({"provider_status": "IN_QUEUE"}, False, "queued"),
    ({"provider_status": "IN_PROGRESS"}, False, "generating"),
    ({"provider_status": "DOWNLOADING"}, False, "downloading"),
    ({"completed_at": "t", "raw_video_path": "x"}, True, "complete"),
    ({"status": "failed"}, False, "failed"),
    ({"status": "cancelled"}, False, "cancelled"),
    ({"provider_job_id": None}, False, "not_started"),
])
def test_phase_is_derived_from_persisted_fields(fields, exists, phase):
    assert st.attempt_phase(_entry(**fields), exists) == phase


def test_unfinished_kling_attempt_is_listed_with_everything_the_card_needs():
    manifest = {"clip03": {"video_model": "alibaba/wan-3.0/image-to-video", "provider_job_id": "wan-1"},
                KEY: _entry(provider_status="IN_QUEUE", status_checked_at="2026-09-28T21:10:05+00:00")}
    kling = stage_attempts(manifest, "clip03")[1]
    assert kling["model_label"] == "Kling v3 Standard" and kling["provider"] == "fal"
    assert (kling["label"], kling["attempt_number"]) == ("Attempt 4", 4)
    assert kling["provider_job_id"] == JOB and kling["phase"] == "queued" and kling["provider_status"] == "IN_QUEUE"
    assert kling["estimated_cost_usd"] == 0.504 and kling["submitted_at"] and kling["ended_at"] is None
    assert kling["local_file_exists"] is False and kling["output_url"] is None


# --- one free status check, persisted --------------------------------------------------------------

def test_check_persists_the_provider_status_and_heartbeat(manifest):
    fake = FakeFal(["IN_PROGRESS"])
    entry = st.check_attempt(manifest, KEY, provider=_provider(fake))
    assert entry["provider_status"] == "IN_PROGRESS" and entry["status_checked_at"]
    assert _read(manifest)[KEY]["provider_status"] == "IN_PROGRESS"  # survives a backend restart
    assert st.attempt_phase(_read(manifest)[KEY], False) == "generating"


def test_completed_job_is_downloaded_and_becomes_playable(manifest):
    fake = FakeFal(["COMPLETED"])
    entry = st.check_attempt(manifest, KEY, provider=_provider(fake))
    out = manifest.parent / "clips" / "clip03__attempt4_fal_fal-ai_kling-video_v3_standard_image-to-video_raw.mp4"
    assert entry["raw_video_path"] == str(out) and out.read_bytes() == b"mp4"
    assert entry["completed_at"] and entry["actual_cost_usd"] == 0.504 and entry["provider_status"] == "COMPLETED"
    card = stage_attempts(_read(manifest) | {"clip03": {"provider_job_id": "w"}}, "clip03")[1]
    assert card["phase"] == "complete" and card["local_file_exists"] and card["output_url"]


def test_completed_with_a_validation_error_is_failed_not_retried(manifest):
    fake = FakeFal(["COMPLETED"], result=(422, LIMIT_422))
    entry = st.check_attempt(manifest, KEY, provider=_provider(fake))
    assert entry["status"] == "failed" and "512 characters" in entry["error"] and entry["actual_cost_usd"] is None
    calls = len(fake.calls)
    assert st.check_attempt(manifest, KEY, provider=_provider(fake)) == _read(manifest)[KEY]
    assert len(fake.calls) == calls  # a finished attempt is never checked again


def test_a_fresh_runner_heartbeat_leaves_the_job_to_the_runner(manifest):
    data = _read(manifest)
    data[KEY]["status_checked_at"] = datetime.now(timezone.utc).isoformat()
    manifest.write_text(json.dumps(data))
    fake = FakeFal()
    st.check_attempt(manifest, KEY, provider=_provider(fake))
    assert fake.calls == []
    data[KEY]["status_checked_at"] = (datetime.now(timezone.utc) - timedelta(minutes=5)).isoformat()
    manifest.write_text(json.dumps(data))
    st.check_attempt(manifest, KEY, provider=_provider(fake))
    assert len(fake.calls) == 1


def test_a_job_recorded_only_in_job_json_is_still_shown(manifest):
    data = _read(manifest)
    del data[KEY]
    manifest.write_text(json.dumps(data))
    setup_dir = manifest.parent / "provider_tests" / "fal_kling"
    setup_dir.mkdir(parents=True)
    (setup_dir / "setup.json").write_text(json.dumps({"attempt_key": KEY, "model": {"endpoint_id": KLING_3_STANDARD.submit_path},
                                                      "cost": {"expected_usd": 0.504}}))
    (setup_dir / "job.json").write_text(json.dumps({"provider_job_id": JOB, "meta": {}}))
    orphans = st.orphan_job_entries(manifest, data)
    assert orphans[KEY]["provider_job_id"] == JOB
    card = stage_attempts(data | orphans | {"clip03": {"provider_job_id": "w"}}, "clip03")[1]
    assert card["phase"] == "submitted" and card["model_label"] == "Kling v3 Standard"


# --- the studio endpoint ---------------------------------------------------------------------------

def test_check_endpoint_is_free_and_persists(client, db_session, manifest, monkeypatch):
    db_session.add(StudioProject(slug="train_car_video_2", name="Train car", source_path=str(manifest)))
    db_session.commit()
    fake = FakeFal(["IN_QUEUE"])
    monkeypatch.setattr(st, "fal_provider_for", lambda entry: _provider(fake))
    body = client.post(f"/studio/projects/train_car_video_2/attempts/{KEY}/check").json()
    assert body["checked"] and body["phase"] == "queued" and body["provider_status"] == "IN_QUEUE"
    assert all(url != SUBMIT for _, url in fake.calls)
    again = client.post(f"/studio/projects/train_car_video_2/attempts/{KEY}/check").json()
    assert not again["checked"]  # fresh heartbeat: no second provider call
    assert client.post("/studio/projects/train_car_video_2/attempts/clip03/check").status_code == 400
