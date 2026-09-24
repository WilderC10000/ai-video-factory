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


def test_blockers_enforce_cap_order_and_proof_gate(tmp_path):
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


def test_pass_proof_refused_before_the_proof_clip_exists(tmp_path):
    with pytest.raises(Exception, match="hasn't been generated"):
        stage_mod.pass_proof("looks fine", _manifest(tmp_path))


@pytest.fixture()
def train_sandbox(tmp_path, monkeypatch):
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
