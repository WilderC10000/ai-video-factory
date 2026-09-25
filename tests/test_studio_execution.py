"""FORMA Virtual Studio - decisions, launches and the job runner.

Every execution here runs in MOCK mode against a temp copy shaped like
data/alpine_video_2 (mock providers, $0.00). No test can reach a paid provider:
live mode is never enabled and FAL_API_KEY is never read.
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
from app.studio.models import (
    ApprovalStatus,
    JobStatus,
    Severity,
    StageStatus,
    StudioEvent,
    StudioJob,
    StudioProject,
)
from app.studio.service import build_snapshot
from tests.test_studio_importer import data_dir  # noqa: F401  (fixture)

FIXTURE_JPG = Path("app/providers/image/fixtures/mock_reference.jpg").resolve()
FIXTURE_MP4 = Path("app/providers/video/fixtures/mock_clip.mp4").resolve()
SLUG = "alpine_video_2"


@pytest.fixture()
def sandbox(data_dir, monkeypatch):  # noqa: F811
    """Temp data dir with real media bytes where the pipeline decodes them, in mock mode."""
    alpine = data_dir / SLUG
    for name in ("edit4_roof_complete.jpg", "edit3_framing_complete.jpg", "site_reference.jpg"):
        shutil.copy(FIXTURE_JPG, alpine / name)
    for name in ("shot5_roof_cladding_raw.mp4", "shot4_aframe_ribs_raw.mp4"):
        shutil.copy(FIXTURE_MP4, alpine / name)
    monkeypatch.setattr(settings, "studio_execution_mode", "mock")
    monkeypatch.setattr(settings, "studio_data_dir", str(data_dir))
    monkeypatch.setattr(settings, "fal_api_key", None)
    return data_dir


@pytest.fixture()
def runner():
    return JobRunner(SessionLocal)


class _HeldRunner:
    """Accepts jobs but never runs them - keeps a job 'active' for lock tests."""

    def __init__(self):
        self.submitted: list[str] = []

    def submit(self, job_id):
        self.submitted.append(job_id)


def _manifest(root: Path) -> dict:
    return json.loads((root / SLUG / "manifest.json").read_text())


def _write_manifest(root: Path, manifest: dict) -> None:
    (root / SLUG / "manifest.json").write_text(json.dumps(manifest, indent=2))


def _rid() -> str:
    return uuid.uuid4().hex


def _stage(db, key):
    project = db.scalar(select(StudioProject).where(StudioProject.slug == SLUG))
    return next(s for s in project.stages if s.key == key)


def _agents(db) -> dict:
    return {r["id"]: r["agent"] for r in build_snapshot(db, SLUG)["rooms"]}


# --- modes -------------------------------------------------------------------------------

def test_disabled_mode_refuses_every_launch_but_records_decisions(db_session, data_dir, runner, monkeypatch):  # noqa: F811
    assert settings.studio_execution_mode == "disabled"
    monkeypatch.setattr(settings, "studio_data_dir", str(data_dir))
    import_all(db_session, data_dir)
    plan = control.launch_plan(db_session, SLUG, "edit4_roof_complete", "continue", resync=False)
    assert not plan["allowed"] and "disabled" in plan["problems"][0]

    with pytest.raises(control.ControlError) as e:
        control.launch(db_session, runner, SLUG, "edit4_roof_complete", mode="continue", request_id=_rid(),
                       confirmed=True, approve_first=True)
    assert e.value.status_code == 409
    assert db_session.scalar(select(StudioJob)) is None
    # The approval half of Approve & Continue is still recorded.
    assert _stage(db_session, "edit4_roof_complete").approval_state == ApprovalStatus.APPROVED


def test_mock_mode_refuses_to_run_against_real_data(monkeypatch):
    from app.studio.execution import mode_problems

    monkeypatch.setattr(settings, "studio_execution_mode", "mock")
    monkeypatch.setattr(settings, "studio_data_dir", "./data")
    assert "sandbox" in mode_problems()[0]
    monkeypatch.setattr(settings, "studio_execution_mode", "live")
    monkeypatch.setattr(settings, "fal_api_key", None)
    assert "FAL_API_KEY" in mode_problems()[0]


# --- decisions ---------------------------------------------------------------------------

def test_approve_only_and_reject_never_create_jobs(db_session, sandbox):
    import_all(db_session, sandbox)
    control.record_decision(db_session, SLUG, "edit4_roof_complete", "reject", "  roof pitch is wrong ")
    stage = _stage(db_session, "edit4_roof_complete")
    assert stage.approval_state == ApprovalStatus.REJECTED and stage.requires_human_review
    event = db_session.scalar(select(StudioEvent).where(StudioEvent.type == "decision"))
    assert event.severity == Severity.MEDIUM and "roof pitch is wrong" in event.message
    agents = _agents(db_session)
    assert agents["build_logic_workshop"]["status"] == "blocked" and agents["build_logic_workshop"]["requires_human_review"]

    import_all(db_session, sandbox)  # a re-sync keeps the studio decision
    assert _stage(db_session, "edit4_roof_complete").approval_state == ApprovalStatus.REJECTED

    control.record_decision(db_session, SLUG, "edit4_roof_complete", "approve")
    assert _stage(db_session, "edit4_roof_complete").approval_state == ApprovalStatus.APPROVED
    assert db_session.scalar(select(StudioJob)) is None
    assert "shot6" not in _manifest(sandbox)

    with pytest.raises(control.ControlError):  # nothing to review on a stage that never ran
        control.record_decision(db_session, SLUG, "shot7", "approve")


# --- approve & continue --------------------------------------------------------------------

def test_approve_and_continue_runs_next_stage_and_resyncs(db_session, sandbox, runner):
    import_all(db_session, sandbox)
    assert _agents(db_session)["build_logic_workshop"]["status"] == "waiting_for_approval"

    job = control.launch(db_session, runner, SLUG, "edit4_roof_complete", mode="continue", request_id=_rid(),
                         confirmed=True, approve_first=True)
    assert job.stage_key == "shot6" and job.is_paid and job.expected_cost_usd == 0.55
    runner.wait(job.id)

    db_session.expire_all()
    job = db_session.get(StudioJob, job.id)
    assert job.status == JobStatus.SUCCEEDED, job.error
    assert job.active_lock is None and job.execution_mode == "mock"
    assert job.output_paths[0].endswith("shot6_glass_raw.mp4") and Path(job.output_paths[0]).is_file()
    assert "Submitting" in job.log

    manifest = _manifest(sandbox)
    assert manifest["shot6"]["completed_at"] and manifest["shot6"]["actual_cost_usd"] == 0.0
    shot6 = _stage(db_session, "shot6")
    assert shot6.status == StageStatus.COMPLETE and shot6.approval_state == ApprovalStatus.PENDING
    assert _stage(db_session, "edit4_roof_complete").approval_state == ApprovalStatus.APPROVED
    agents = _agents(db_session)
    assert agents["render_bay"]["status"] == "waiting_for_approval" and agents["render_bay"]["requires_human_review"]
    assert agents["build_logic_workshop"]["requires_human_review"] is False


def test_continue_requires_approval_and_confirmation(db_session, sandbox, runner):
    import_all(db_session, sandbox)
    with pytest.raises(control.ControlError) as e:
        control.launch(db_session, runner, SLUG, "edit4_roof_complete", mode="continue", request_id=_rid(),
                       confirmed=False, approve_first=True)
    assert e.value.status_code == 400
    with pytest.raises(control.ControlError) as e:
        control.launch(db_session, runner, SLUG, "edit4_roof_complete", mode="continue", request_id=_rid(),
                       confirmed=True, approve_first=False)
    assert "must be approved" in e.value.message
    assert db_session.scalar(select(StudioJob)) is None


# --- duplicate protection --------------------------------------------------------------------

def test_double_click_returns_the_same_job_and_a_second_launch_is_refused(db_session, sandbox):
    import_all(db_session, sandbox)
    held = _HeldRunner()
    rid = _rid()
    first = control.launch(db_session, held, SLUG, "edit4_roof_complete", mode="continue", request_id=rid,
                           confirmed=True, approve_first=True)
    again = control.launch(db_session, held, SLUG, "edit4_roof_complete", mode="continue", request_id=rid,
                           confirmed=True, approve_first=True)
    assert again.id == first.id and held.submitted == [first.id]

    with pytest.raises(control.ControlError) as e:
        control.launch(db_session, held, SLUG, "edit4_roof_complete", mode="continue", request_id=_rid(),
                       confirmed=True, approve_first=True)
    assert e.value.status_code == 409 and "already running" in e.value.message
    assert len(db_session.scalars(select(StudioJob)).all()) == 1


def test_database_lock_rejects_a_second_active_job_for_the_project(db_session, sandbox):
    from sqlalchemy.exc import IntegrityError

    import_all(db_session, sandbox)
    project = db_session.scalar(select(StudioProject).where(StudioProject.slug == SLUG))
    for rid in ("a", "b"):
        db_session.add(StudioJob(project_id=project.id, stage_key="shot6", mode="continue", action="video",
                                 execution_mode="mock", request_id=rid, active_lock=project.id))
    with pytest.raises(IntegrityError):
        db_session.commit()


# --- budget ------------------------------------------------------------------------------

def test_budget_cap_blocks_paid_launch_and_finance_room(db_session, sandbox, runner):
    manifest = _manifest(sandbox)
    manifest["budget_cap_usd"] = 4.0  # $3.60 spent, Shot 6 caps at $0.55 -> $4.15 > $4.00
    _write_manifest(sandbox, manifest)
    import_all(db_session, sandbox)

    plan = control.launch_plan(db_session, SLUG, "edit4_roof_complete", "continue")
    assert not plan["allowed"] and plan["problems"][0].startswith("Budget")
    assert plan["remaining_after_usd"] == pytest.approx(-0.15)
    with pytest.raises(control.ControlError) as e:
        control.launch(db_session, runner, SLUG, "edit4_roof_complete", mode="continue", request_id=_rid(),
                       confirmed=True, approve_first=True)
    assert e.value.status_code == 402
    assert db_session.scalar(select(StudioJob)) is None and "shot6" not in _manifest(sandbox)
    finance = _agents(db_session)["finance_room"]
    assert finance["status"] == "blocked" and "$0.55" in finance["status_reason"]


def test_pipeline_budget_guard_raises_before_any_manifest_write(tmp_path):
    from scripts import run_alpine_video_2_common as pipeline

    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_text(json.dumps({"budget_cap_usd": 1.0, "x": {"actual_cost_usd": 0.9}}))
    with pytest.raises(pipeline.PipelineStepError, match="exceed the remaining hard budget"):
        pipeline.check_budget(0.25, manifest_path)
    assert json.loads(manifest_path.read_text()) == {"budget_cap_usd": 1.0, "x": {"actual_cost_usd": 0.9}}


# --- retry -------------------------------------------------------------------------------

def test_retry_archives_previous_attempt_and_reopens_review(db_session, sandbox, runner):
    import_all(db_session, sandbox)
    control.record_decision(db_session, SLUG, "edit4_roof_complete", "reject", "cladding wrong color")
    plan = control.launch_plan(db_session, SLUG, "edit4_roof_complete", "retry")
    assert plan["allowed"] and plan["paid"] and plan["estimated_cost_usd"] == 0.15
    assert (plan["spent_usd"], plan["remaining_usd"], plan["remaining_after_usd"]) == (3.6, 2.9, 2.75)

    job = control.launch(db_session, runner, SLUG, "edit4_roof_complete", mode="retry", request_id=_rid(), confirmed=True)
    runner.wait(job.id)
    db_session.expire_all()
    assert db_session.get(StudioJob, job.id).status == JobStatus.SUCCEEDED

    manifest = _manifest(sandbox)
    archived = manifest["edit4_roof_complete__attempt1"]
    assert archived["actual_cost_usd"] == 0.15 and archived["output_path"].endswith("edit4_roof_complete.attempt1.jpg")
    assert Path(archived["output_path"]).is_file()
    assert (sandbox / SLUG / "edit4_roof_complete.jpg").is_file()
    project = db_session.scalar(select(StudioProject).where(StudioProject.slug == SLUG))
    assert project.budget.spent_usd == pytest.approx(3.6)  # old attempt still counted, mock retry $0.00
    stage = _stage(db_session, "edit4_roof_complete")
    assert stage.approval_state == ApprovalStatus.PENDING  # new attempt, new review


def test_retry_refused_when_later_stages_are_built_on_it(db_session, sandbox):
    import_all(db_session, sandbox)
    plan = control.launch_plan(db_session, SLUG, "shot5", "retry")
    assert not plan["allowed"] and any("break the chain" in p for p in plan["problems"])


# --- failures ------------------------------------------------------------------------------

def test_failed_job_is_recorded_once_and_never_retried(db_session, sandbox, runner, monkeypatch):
    import app.studio.jobs as jobs_module
    from scripts.run_alpine_video_2_common import PipelineStepError

    calls = []

    def boom(action, **_kwargs):
        calls.append(action.stage.key)
        raise PipelineStepError("Provider reported generation failure: simulated")

    monkeypatch.setattr(jobs_module, "run_action", boom)
    import_all(db_session, sandbox)
    job = control.launch(db_session, runner, SLUG, "edit4_roof_complete", mode="continue", request_id=_rid(),
                         confirmed=True, approve_first=True)
    runner.wait(job.id)
    db_session.expire_all()
    job = db_session.get(StudioJob, job.id)
    assert job.status == JobStatus.FAILED and "simulated" in job.error and job.active_lock is None
    assert calls == ["shot6"]
    render = _agents(db_session)["render_bay"]
    assert render["status"] == "failed" and render["requires_human_review"]
    event = db_session.scalar(select(StudioEvent).where(StudioEvent.type == "job_failed"))
    assert event.severity == Severity.HIGH


def test_stale_active_jobs_are_failed_not_rerun_on_startup(db_session, sandbox, runner):
    import_all(db_session, sandbox)
    project = db_session.scalar(select(StudioProject).where(StudioProject.slug == SLUG))
    db_session.add(StudioJob(project_id=project.id, stage_key="shot6", mode="continue", action="video",
                             execution_mode="mock", request_id="stale", active_lock=project.id,
                             status=JobStatus.GENERATING))
    db_session.commit()
    assert runner.recover_stale_jobs() == 1
    db_session.expire_all()
    job = db_session.scalar(select(StudioJob).where(StudioJob.request_id == "stale"))
    assert job.status == JobStatus.FAILED and job.active_lock is None and "NOT re-run" in job.error


# --- HTTP ---------------------------------------------------------------------------------

def test_http_decision_preview_and_launch(client, db_session, sandbox):
    import_all(db_session, sandbox)
    r = client.post(f"/studio/projects/{SLUG}/stages/edit4_roof_complete/decision", json={"decision": "approve"})
    assert r.status_code == 200 and r.json()["status"] == "approved"
    preview = client.get(f"/studio/projects/{SLUG}/stages/edit4_roof_complete/launch-preview?mode=continue").json()
    assert preview["allowed"] and preview["target_stage"]["key"] == "shot6"
    r = client.post(f"/studio/projects/{SLUG}/stages/edit4_roof_complete/launch",
                    json={"mode": "continue", "request_id": _rid(), "confirmed": False})
    assert r.status_code == 400

    from app.studio.jobs import get_runner

    r = client.post(f"/studio/projects/{SLUG}/stages/edit4_roof_complete/launch",
                    json={"mode": "continue", "request_id": _rid(), "confirmed": True})
    assert r.status_code == 202, r.text
    get_runner().wait(r.json()["id"])
    job = client.get(f"/studio/jobs/{r.json()['id']}").json()
    assert job["status"] == "succeeded" and job["phase_label"] == "Complete"


# --- no duplicate paid attempts while an earlier provider job may still exist --------------------

def test_retry_is_blocked_while_an_earlier_provider_job_is_unfinished(db_session, sandbox):
    alpine = sandbox / SLUG
    manifest = _manifest(sandbox)
    manifest["shot6"] = {"estimated_cost_usd": 0.55, "raw_video_path": None, "actual_cost_usd": None,
                         "completed_at": None, "provider_job_id": "job-still-queued"}
    _write_manifest(sandbox, manifest)
    (alpine / "shot6_last_job.json").write_text(json.dumps({"provider_job_id": "job-still-queued", "meta": {}}))
    import_all(db_session, sandbox)

    retry = control.launch_plan(db_session, SLUG, "shot6", "retry")
    assert not retry["allowed"]
    assert any("Retry is blocked" in p and "job-still-queued" in p for p in retry["problems"])
    recover = control.launch_plan(db_session, SLUG, "shot6", "recover")
    assert recover["allowed"] and not recover["paid"] and recover["estimated_cost_usd"] == 0.0
