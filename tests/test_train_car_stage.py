"""FORMA Video #2 (train car) - incremental runner, proof gate, and Virtual Studio flow.

Everything runs in MOCK mode against a temp data dir ($0.00 mock providers). No test can
reach a paid provider: live mode is never enabled and FAL_API_KEY is cleared.
"""
import json
import shutil
import uuid
from pathlib import Path

import pytest
from sqlalchemy import select

from app.config import settings
from app.db import SessionLocal
from app.studio import control
from app.studio.importers.manifest_importer import import_all
from app.studio.jobs import JobRunner
from app.studio.models import JobStatus, StudioJob, StudioProject
from app.studio.service import build_snapshot
from scripts import run_train_car_video_2_plan as plan
from scripts import run_train_car_video_2_stage as stage_mod
from scripts.run_alpine_video_2_common import EditSpec, ImageGenerateSpec, VideoShotSpec

SLUG = plan.SLUG


def test_specs_cover_every_stage_with_the_right_kind():
    assert set(stage_mod.SPECS) == set(stage_mod.STAGES)
    for key, spec in stage_mod.SPECS.items():
        kind = stage_mod.STAGES[key].kind
        expected = {"image_generate": ImageGenerateSpec, "image_edit": EditSpec, "video": VideoShotSpec}[kind]
        assert isinstance(spec, expected), key
    clip03 = stage_mod.SPECS["clip03"]
    assert clip03.start_frame_path.name == "cp02_still.jpg" and clip03.end_frame_path.name == "cp03_still.jpg"
    assert clip03.disable_prompt_expansion and clip03.duration_seconds == 6.0 and clip03.max_spend_usd == 0.30
    assert stage_mod.SPECS["clip01"].end_frame_path is None
    assert all(s.end_frame_path is not None for k, s in stage_mod.SPECS.items() if k.startswith("clip") and k != "clip01")


def _manifest(tmp: Path, **extra) -> Path:
    path = tmp / "manifest.json"
    path.write_text(json.dumps({"experiment": SLUG, "budget_cap_usd": 15.0, **extra}))
    return path


@pytest.fixture()
def api_stills(monkeypatch):
    """The original paid-still flow (plan.STILLS_SOURCE = "api")."""
    monkeypatch.setattr(plan, "STILLS_SOURCE", "api")


def test_blockers_enforce_cap_order_and_proof_gate(tmp_path, api_stills):
    no_cap = tmp_path / "nocap.json"
    no_cap.write_text(json.dumps({"experiment": SLUG, "budget_cap_usd": None}))
    assert any("budget cap" in b for b in stage_mod.launch_blockers("cp01_still", no_cap))

    m = _manifest(tmp_path)
    assert stage_mod.launch_blockers("cp01_still", m) == []
    assert any("cp01_still must be generated" in b for b in stage_mod.launch_blockers("cp02_bridge", m))

    done = {"completed_at": "2026-09-24T00:00:00+00:00", "actual_cost_usd": 0.0}
    m = _manifest(tmp_path, **{k: done for k in ["cp01_still", "cp02_bridge", "cp02_still", "cp03_still", "clip03"]})
    blockers = stage_mod.launch_blockers("clip01", m)
    assert len(blockers) == 1 and blockers[0].startswith("PROOF GATE")
    with pytest.raises(Exception, match="Say what you checked"):
        stage_mod.pass_proof("   ", m)
    stage_mod.pass_proof("end frame held; railcar stable; causal clearing", m)
    assert stage_mod.launch_blockers("clip01", m) == []


def test_failed_proof_keeps_gate_closed_and_blocks_the_video_model(tmp_path, api_stills):
    done = {"completed_at": "2026-09-24T00:00:00+00:00", "actual_cost_usd": 0.0}
    clip = done | {"video_model": stage_mod.VIDEO_MODEL, "provider_job_id": "job-1"}
    m = _manifest(tmp_path, **{k: done for k in ["cp01_still", "cp02_bridge", "cp02_still", "cp03_still"]}, clip03=clip)
    attempt = stage_mod.fail_proof("morphs toward the end still", failure_class="motion_mechanism",
                                   findings=["no scoop/carry/dump cycle"], continuity="pass", manifest_path=m)
    assert attempt["model"] == stage_mod.VIDEO_MODEL and attempt["provider_job_id"] == "job-1"
    assert json.loads(m.read_text())["proof_gate"]["passed"] is False
    assert any("failed the clip03 proof" in b for b in stage_mod.launch_blockers("clip01", m))
    assert any("failed the clip03 proof" in b for b in stage_mod.launch_blockers("clip03", m))
    assert not any("failed the clip03 proof" in b for b in stage_mod.launch_blockers("cp04_bridge", m))
    with pytest.raises(Exception, match="already reviewed and failed"):
        stage_mod.pass_proof("looks fine now", m)


def test_pass_proof_refused_before_the_proof_clip_exists(tmp_path):
    with pytest.raises(Exception, match="hasn't been generated"):
        stage_mod.pass_proof("looks fine", _manifest(tmp_path))


@pytest.fixture()
def train_sandbox(tmp_path, monkeypatch, api_stills):
    project = tmp_path / SLUG
    project.mkdir()
    _manifest(project)
    (project / "storyboard").mkdir()
    shutil.copy(Path("app/providers/image/fixtures/mock_reference.jpg"), project / "storyboard" / "cp03.jpg")
    monkeypatch.setattr(settings, "studio_execution_mode", "mock")
    monkeypatch.setattr(settings, "studio_data_dir", str(tmp_path))
    monkeypatch.setattr(settings, "fal_api_key", None)
    return tmp_path


@pytest.mark.skipif(not shutil.which("ffmpeg"), reason="sandbox mock video needs ffmpeg")
def test_first_proof_runs_through_the_studio_and_stops_at_the_gate(db_session, train_sandbox):
    runner = JobRunner(SessionLocal)
    import_all(db_session, train_sandbox, slugs=[SLUG])
    project = db_session.scalar(select(StudioProject).where(StudioProject.slug == SLUG))
    assert len(project.stages) == 47 and project.budget.cap_usd == 15.0

    def launch(key, mode):
        job = control.launch(db_session, runner, SLUG, key, mode=mode, request_id=uuid.uuid4().hex,
                             confirmed=True, approve_first=(mode == "continue"))
        runner.wait(job.id)
        db_session.expire_all()
        return db_session.get(StudioJob, job.id)

    # Nothing can start out of order.
    assert not control.launch_plan(db_session, SLUG, "cp02_still", "generate")["allowed"]

    assert launch("cp01_still", "generate").status == JobStatus.SUCCEEDED
    for key in ["cp01_still", "cp02_bridge", "cp02_still", "cp03_still"]:
        job = launch(key, "continue")
        assert job.status == JobStatus.SUCCEEDED, (key, job.error)
    assert job.stage_key == "clip03"

    manifest = json.loads((train_sandbox / SLUG / "manifest.json").read_text())
    assert manifest["clip03"]["end_frame_path"].endswith("cp03_still.jpg")
    assert "SKIP REPETITION, NOT EXPLANATION" in manifest["clip03"]["video_prompt"]

    snap = build_snapshot(db_session, SLUG)
    clip03 = next(s for s in snap["stages"] if s["key"] == "clip03")
    assert clip03["approval_state"] == "pending" and clip03["target_frame_url"] and clip03["storyboard_checkpoint_url"]

    plan_after = control.launch_plan(db_session, SLUG, "clip03", "continue")
    assert not plan_after["allowed"] and plan_after["target_stage"]["key"] == "clip01"
    assert any(p.startswith("PROOF GATE") for p in plan_after["problems"])
    with pytest.raises(control.ControlError):
        launch("clip03", "continue")
    assert db_session.scalar(select(StudioJob).where(StudioJob.stage_key == "clip01")) is None


# --- manual stills (ChatGPT): the stills folder is the source of truth ---------------------------

JPG = Path("app/providers/image/fixtures/mock_reference.jpg")


@pytest.fixture()
def manual(tmp_path, monkeypatch):
    monkeypatch.setattr(plan, "STILLS_SOURCE", "manual")
    project = tmp_path / "proj"
    (project / "stills").mkdir(parents=True)
    return _manifest(project), project / "stills"


def _state(m, stills, key):
    return stage_mod.still_state(key, json.loads(m.read_text()), stills)["state"]


def test_manual_mode_never_generates_stills(manual):
    m, _ = manual
    for key in ("cp01_still", "cp02_bridge", "cp04_still"):
        blockers = stage_mod.launch_blockers(key, m)
        assert len(blockers) == 1 and "made manually in ChatGPT" in blockers[0]
    with pytest.raises(Exception, match="made manually in ChatGPT"):
        stage_mod.run_stage("cp01_still", manifest_path=m)


def test_manual_still_place_approve_replace_cycle(manual):
    m, stills = manual
    assert _state(m, stills, "cp03_still") == "missing"
    with pytest.raises(Exception, match="no still yet"):
        stage_mod.approve_still("cp03_still", "ok", manifest_path=m)

    (stills / "cp03_still.png").write_bytes(b"chatgpt v1")  # a ChatGPT export: jpg, png or webp
    assert _state(m, stills, "cp03_still") == "placed"
    with pytest.raises(Exception, match="Say what you checked"):
        stage_mod.approve_still("cp03_still", " ", manifest_path=m)
    first = stage_mod.approve_still("cp03_still", "clearing strip 80% done", manifest_path=m)
    assert _state(m, stills, "cp03_still") == "approved"
    assert first["actual_cost_usd"] == 0.0 and first["source"] == "manual"
    assert stage_mod.approved_still("cp03_still", m)[0] == stills / "cp03_still.png"

    (stills / "cp03_still.png").write_bytes(b"chatgpt v2")  # iterate in ChatGPT and overwrite
    assert _state(m, stills, "cp03_still") == "changed"
    with pytest.raises(Exception, match="not the file that was approved"):
        stage_mod.approved_still("cp03_still", m)
    stage_mod.approve_still("cp03_still", "v2 better shovel pose", manifest_path=m)
    manifest = json.loads(m.read_text())
    assert _state(m, stills, "cp03_still") == "approved"
    assert manifest["cp03_still__attempt1"]["approval_note"] == "clearing strip 80% done"

    (stills / "cp03_still.jpg").write_bytes(b"a second file for the same key")
    assert _state(m, stills, "cp03_still") == "ambiguous"


def test_generated_still_replaced_manually_keeps_its_spend(manual):
    from scripts.run_alpine_video_2_common import spent_so_far

    m, stills = manual
    (stills / "cp02_still.jpg").write_bytes(b"api still")
    m.write_text(json.dumps(json.loads(m.read_text()) | {"cp02_still": {
        "output_path": str(stills / "cp02_still.jpg"), "actual_cost_usd": 0.15,
        "completed_at": "2026-09-24T00:00:00+00:00"}}))
    kept = stage_mod.approve_still("cp02_still", "approved in studio", manifest_path=m)
    assert kept["actual_cost_usd"] == 0.15  # same file: approval recorded in place

    (stills / "cp02_still.jpg").unlink()
    (stills / "cp02_still.png").write_bytes(b"chatgpt still")
    stage_mod.approve_still("cp02_still", "chatgpt redo", manifest_path=m)
    manifest = json.loads(m.read_text())
    assert manifest["cp02_still__attempt1"]["actual_cost_usd"] == 0.15
    assert manifest["cp02_still"]["actual_cost_usd"] == 0.0 and spent_so_far(manifest) == 0.15


def test_manual_clip_needs_its_exact_approved_stills(manual):
    m, stills = manual
    blockers = stage_mod.launch_blockers("clip03", m)
    assert any("Needs an approved cp02_still" in b for b in blockers)
    assert any("Needs an approved cp03_still" in b for b in blockers)
    for key in ("cp02_still", "cp03_still"):
        shutil.copy(JPG, stills / f"{key}.jpg")
        stage_mod.approve_still(key, "ok", manifest_path=m)
    assert stage_mod.launch_blockers("clip03", m) == []  # cp01 / the bridge are not clip03's frames
    (stills / "cp03_still.jpg").write_bytes(b"swapped after approval")
    assert any("not the file that was approved" in b for b in stage_mod.launch_blockers("clip03", m))


def test_live_specs_point_at_the_approved_still_file(manual, monkeypatch):
    m, stills = manual
    monkeypatch.setattr(stage_mod, "MANIFEST_PATH", m)
    (stills / "cp03_still.png").write_bytes(b"png from chatgpt")
    stage_mod.approve_still("cp03_still", "ok", manifest_path=m)
    assert stage_mod.SPECS["clip03"].end_frame_path == stills / "cp03_still.png"
    assert stage_mod.SPECS.get("clip03").end_frame_path == stills / "cp03_still.png"
