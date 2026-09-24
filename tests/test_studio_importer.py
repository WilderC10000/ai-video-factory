"""FORMA Virtual Studio - manifest importer.

Every test builds its own synthetic data directory shaped like the real
data/alpine_video_2 and data/cliffside_video_1 folders, so nothing here
depends on (or can touch) the real production files - except the last two
tests, which read the real manifests when present and verify they are left
byte-for-byte untouched.
"""
import hashlib
import importlib
import json
from pathlib import Path

import pytest
from sqlalchemy import func, select

from app.config import ROOT_DIR
from app.studio.importers.manifest_importer import import_all
from app.studio.importers.stage_maps import ALPINE_VIDEO_2, CLIFFSIDE_VIDEO_1
from app.studio.models import (
    AgentStatus,
    ApprovalStatus,
    ProjectSource,
    Severity,
    StageKind,
    StageStatus,
    StudioAgent,
    StudioApproval,
    StudioBudget,
    StudioEvent,
    StudioProject,
    StudioStage,
)
from app.studio.rooms import ROOMS

ALPINE_DONE = [  # (key, actual cost, output file, previous-frame file) - mirrors the real manifest up to edit4
    ("site_reference", 0.15, "site_reference.jpg", None),
    ("shot1", 0.35, "shot1_opening_prep_raw.mp4", "site_reference.jpg"),
    ("shot2", 0.50, "shot2_base_floor_raw.mp4", "shot2_start_frame.jpg"),
    ("edit1_base_floor_complete", 0.15, "edit1_base_floor_complete.jpg", "edit1_source_frame.jpg"),
    ("shot3", 0.65, "shot3_floorboards_raw.mp4", "edit1_base_floor_complete.jpg"),
    ("edit2_floor_complete", 0.15, "edit2_floor_complete.jpg", "edit2_source_frame.jpg"),
    ("shot4", 0.75, "shot4_aframe_ribs_raw.mp4", "edit2_floor_complete.jpg"),
    ("edit3_framing_complete", 0.15, "edit3_framing_complete.jpg", "edit3_source_frame.jpg"),
    ("shot5", 0.60, "shot5_roof_cladding_raw.mp4", "edit3_framing_complete.jpg"),
    ("edit4_roof_complete", 0.15, "edit4_roof_complete.jpg", "edit4_source_frame.jpg"),
]

CLIFFSIDE_DONE = [
    ("decking_complete_edit", 0.15, "decking_complete_edit.jpg", "decking_real_last_frame.jpg"),
    ("framing", 0.30, "framing_raw.mp4", "decking_complete_edit.jpg"),
    ("framing_complete_edit", 0.15, "framing_complete_edit.jpg", "framing_real_last_frame.jpg"),
    ("glass", 0.25, "glass_raw.mp4", "framing_complete_edit.jpg"),
    ("exterior_complete_edit", 0.15, "exterior_complete_edit.jpg", "glass_real_last_frame.jpg"),
    ("reveal", 0.35, "reveal_raw.mp4", "exterior_complete_edit.jpg"),
]


def _entry(project_dir: Path, key: str, cost: float, output: str, prev: str | None, n: int) -> dict:
    is_video = output.endswith(".mp4")
    entry = {
        ("video_model" if is_video else "image_model"): "alibaba/wan-3.0/image-to-video" if is_video else "fal-ai/x",
        "estimated_cost_usd": cost,
        ("raw_video_path" if is_video else "output_path"): str(project_dir / output),
        "actual_cost_usd": cost,
        "completed_at": f"2026-09-10T05:{n:02d}:00+00:00",
    }
    if prev:
        entry["start_frame_path" if is_video else "source_frame_path"] = str(project_dir / prev)
    return entry


def _write(path: Path, data: dict) -> None:
    path.write_text(json.dumps(data, indent=2))


def _read(path: Path) -> dict:
    return json.loads(path.read_text())


@pytest.fixture()
def data_dir(tmp_path: Path) -> Path:
    """A data/ directory with an Alpine-shaped and a Cliffside-shaped production,
    every referenced file present on disk, plus an experiment folder that must be ignored."""
    alpine = tmp_path / "alpine_video_2"
    alpine.mkdir()
    manifest = {"experiment": "alpine_video_2", "created_at": "2026-09-10T05:18:19+00:00", "budget_cap_usd": 6.5}
    for n, (key, cost, out, prev) in enumerate(ALPINE_DONE):
        manifest[key] = _entry(alpine, key, cost, out, prev, n)
        for f in (out, prev):
            if f:
                (alpine / f).write_bytes(b"x")
    (alpine / "shot5_last_job.json").write_text(json.dumps({"provider_job_id": "job-5", "meta": {}}))
    _write(alpine / "manifest.json", manifest)

    cliff = tmp_path / "cliffside_video_1"
    cliff.mkdir()
    manifest = {
        "experiment": "cliffside_video_1",
        "rough_assembly": {"rough_assembly_path": str(cliff / "rough_assembly_preview.mp4"),
                           "completed_at": "2026-09-10T00:55:07+00:00"},
    }
    (cliff / "rough_assembly_preview.mp4").write_bytes(b"x")
    for n, (key, cost, out, prev) in enumerate(CLIFFSIDE_DONE):
        manifest[key] = _entry(cliff, key, cost, out, prev, n)
        for f in (out, prev):
            (cliff / f).write_bytes(b"x")
    manifest["final_assembly"] = {"clips": [], "final_visual_master_path": str(cliff / "final.mp4"),
                                  "final_duration_seconds": 30.63, "completed_at": "2026-09-10T04:30:29+00:00"}
    (cliff / "final.mp4").write_bytes(b"x")
    _write(cliff / "manifest.json", manifest)

    experiment = tmp_path / "fal_bakeoff_test"
    experiment.mkdir()
    _write(experiment / "manifest.json", {"experiment": "fal_bakeoff_test", "x": {"actual_cost_usd": 9.0}})
    return tmp_path


def _counts(db) -> dict:
    return {m.__tablename__: db.scalar(select(func.count()).select_from(m))
            for m in (StudioProject, StudioStage, StudioEvent, StudioApproval, StudioBudget, StudioAgent)}


def _stage_state(db) -> list[tuple]:
    rows = db.scalars(select(StudioStage).order_by(StudioStage.project_id, StudioStage.order)).all()
    return [(s.key, s.status, s.actual_cost_usd, s.latest_output_path, s.latest_output_exists,
             s.previous_frame_path, s.approval_state, s.requires_human_review) for s in rows]


def _stages(db, slug: str) -> dict[str, StudioStage]:
    project = db.scalar(select(StudioProject).where(StudioProject.slug == slug))
    return {s.key: s for s in project.stages}


def _snapshot_files(root: Path) -> dict[str, tuple[str, int]]:
    return {str(p.relative_to(root)): (hashlib.sha256(p.read_bytes()).hexdigest(), p.stat().st_mtime_ns)
            for p in sorted(root.rglob("*")) if p.is_file()}


# --- idempotency / no duplicates ------------------------------------------------

def test_reimport_is_idempotent(db_session, data_dir):
    first = import_all(db_session, data_dir)
    counts, state = _counts(db_session), _stage_state(db_session)

    second = import_all(db_session, data_dir)

    assert _counts(db_session) == counts
    assert _stage_state(db_session) == state
    assert all(r.events_created == 0 and r.approvals_created == 0 and r.approvals_updated == 0 for r in second)
    assert [r.spent_usd for r in second] == [r.spent_usd for r in first]
    assert db_session.scalar(select(func.count()).select_from(StudioProject).where(StudioProject.is_active)) == 1


def test_no_duplicate_events_across_repeated_and_advancing_imports(db_session, data_dir):
    for _ in range(3):
        import_all(db_session, data_dir)
    keys = db_session.scalars(select(StudioEvent.dedupe_key)).all()
    assert len(keys) == len(set(keys))
    before = len(keys)

    # The pipeline (not the importer) advances: Shot 6 runs after the edit4 review gate.
    alpine = data_dir / "alpine_video_2"
    manifest = _read(alpine / "manifest.json")
    manifest["shot6"] = _entry(alpine, "shot6", 0.55, "shot6_glass_raw.mp4", "edit4_roof_complete.jpg", 50)
    (alpine / "shot6_glass_raw.mp4").write_bytes(b"x")
    _write(alpine / "manifest.json", manifest)

    result = import_all(db_session, data_dir, slugs=["alpine_video_2"])[0]
    import_all(db_session, data_dir, slugs=["alpine_video_2"])

    keys = db_session.scalars(select(StudioEvent.dedupe_key)).all()
    assert len(keys) == len(set(keys))
    # shot6 completed + edit4 gate inferred approved + new shot6 review requested
    assert result.events_created == 3 and len(keys) == before + 3
    assert result.approvals_created == 1 and result.approvals_updated == 1
    gate = db_session.scalar(select(StudioApproval).where(StudioApproval.dedupe_key == "alpine_video_2:edit4_roof_complete:gate"))
    assert gate.status == ApprovalStatus.APPROVED and gate.decided_via == "pipeline"
    pending = db_session.scalars(select(StudioApproval).where(StudioApproval.status == ApprovalStatus.PENDING,
                                                              StudioApproval.project_id == gate.project_id)).all()
    assert [a.dedupe_key for a in pending] == ["alpine_video_2:shot6:gate"]


def test_importer_never_overwrites_a_studio_decision(db_session, data_dir):
    import_all(db_session, data_dir)
    gate = db_session.scalar(select(StudioApproval).where(StudioApproval.dedupe_key == "alpine_video_2:edit4_roof_complete:gate"))
    gate.status, gate.decided_via, gate.note = ApprovalStatus.REJECTED, "studio", "roof pitch wrong"
    db_session.commit()

    import_all(db_session, data_dir)
    db_session.refresh(gate)
    assert (gate.status, gate.note) == (ApprovalStatus.REJECTED, "roof pitch wrong")


# --- budget -----------------------------------------------------------------------

def test_budget_is_recomputed_not_accumulated(db_session, data_dir):
    import_all(db_session, data_dir)
    import_all(db_session, data_dir)
    alpine = db_session.scalar(select(StudioProject).where(StudioProject.slug == "alpine_video_2"))
    b = alpine.budget
    assert (b.cap_usd, b.spent_usd, b.remaining_usd) == (6.5, 3.6, 2.9)
    assert b.cap_source == "manifest budget_cap_usd"
    assert b.planned_remaining_spend_usd == pytest.approx(0.55 + 0.15 + 0.50 + 0.15 + 0.25)
    assert not b.over_cap and not b.plan_exceeds_cap

    # A cost correction in the manifest replaces, never adds to, the mirrored total.
    path = data_dir / "alpine_video_2" / "manifest.json"
    manifest = _read(path)
    manifest["shot4"]["actual_cost_usd"] = 0.70
    manifest["budget_cap_usd"] = 4.0
    _write(path, manifest)
    import_all(db_session, data_dir)
    db_session.refresh(b)
    assert (b.spent_usd, b.remaining_usd) == (3.55, 0.45)
    assert b.plan_exceeds_cap and not b.over_cap
    blocked = db_session.scalar(select(StudioEvent).where(StudioEvent.dedupe_key == "alpine_video_2:shot6:blocked_budget"))
    assert blocked.severity == Severity.HIGH and blocked.requires_human_review


def test_budget_over_cap_is_critical(db_session, data_dir):
    path = data_dir / "alpine_video_2" / "manifest.json"
    manifest = _read(path)
    manifest["budget_cap_usd"] = 3.0
    _write(path, manifest)
    import_all(db_session, data_dir)
    events = db_session.scalars(select(StudioEvent).where(StudioEvent.severity == Severity.CRITICAL)).all()
    assert len(events) == 1 and "exceeds the $3.00 cap" in events[0].message


# --- stage mapping ----------------------------------------------------------------

def test_alpine_stage_mapping(db_session, data_dir):
    import_all(db_session, data_dir)
    stages = _stages(db_session, "alpine_video_2")
    assert list(stages) == [s.key for s in ALPINE_VIDEO_2.stages]
    assert len(stages) == 16

    done = {k for k, *_ in ALPINE_DONE}
    for key, s in stages.items():
        assert s.status == (StageStatus.COMPLETE if key in done else StageStatus.PENDING), key
    assert stages["site_reference"].room_id == "continuity_office"
    assert stages["shot4"].kind == StageKind.VIDEO and stages["shot4"].room_id == "render_bay"
    assert stages["edit3_framing_complete"].room_id == "build_logic_workshop"
    assert stages["final_assembly"].room_id == "edit_suite"

    shot3 = stages["shot3"]
    assert shot3.previous_frame_path.endswith("edit1_base_floor_complete.jpg") and shot3.previous_frame_exists
    assert shot3.latest_output_path.endswith("shot3_floorboards_raw.mp4") and shot3.latest_output_exists
    assert stages["shot5"].provider_job_id == "job-5"
    assert stages["shot6"].planned_cost_usd == 0.55 and stages["shot6"].actual_cost_usd is None
    # Nullable references are ready but unfilled until real agents exist.
    assert all(s.storyboard_checkpoint_path is None and s.continuity_severity is None
               and s.build_logic_severity is None for s in stages.values())

    # Human gates: everything upstream approved via the pipeline, edit4 waiting on the user.
    assert stages["shot5"].approval_state == ApprovalStatus.APPROVED and not stages["shot5"].requires_human_review
    assert stages["edit4_roof_complete"].approval_state == ApprovalStatus.PENDING
    assert stages["edit4_roof_complete"].requires_human_review
    assert stages["shot6"].approval_state == ApprovalStatus.PENDING
    assert stages["shot7"].approval_state is None

    project = db_session.scalar(select(StudioProject).where(StudioProject.slug == "alpine_video_2"))
    assert project.current_stage_key == "shot6"
    assert project.production_stage == "Awaiting review of Checkpoint 4 - Roof/Cladding Complete; next: Shot 6 - Glass Facade"
    assert project.is_active and project.source == ProjectSource.MANIFEST
    pending = db_session.scalars(select(StudioApproval).where(StudioApproval.status == ApprovalStatus.PENDING,
                                                              StudioApproval.project_id == project.id)).all()
    assert len(pending) == 1
    assert pending[0].title == "Review edit4_roof_complete.jpg and authorize Shot 6 - Glass Facade ($0.55)"
    assert pending[0].estimated_cost_usd == 0.55


def test_cliffside_stage_mapping(db_session, data_dir):
    import_all(db_session, data_dir)
    stages = _stages(db_session, "cliffside_video_1")
    assert list(stages) == [s.key for s in CLIFFSIDE_VIDEO_1.stages]
    assert all(s.status == StageStatus.COMPLETE for s in stages.values())
    assert stages["final_assembly"].latest_output_path.endswith("final.mp4")
    assert stages["final_assembly"].duration_seconds == 30.63
    assert stages["final_assembly"].requires_human_review
    assert stages["rough_assembly"].actual_cost_usd is None

    project = db_session.scalar(select(StudioProject).where(StudioProject.slug == "cliffside_video_1"))
    assert project.current_stage_key is None
    assert project.production_stage == "Complete - final cut awaiting review"
    assert not project.is_active  # Alpine was imported first and became active
    b = project.budget
    assert (b.cap_usd, b.spent_usd, b.remaining_usd) == (5.0, 1.35, 3.65)
    assert "DEFAULT_CAP_USD" in b.cap_source
    note = db_session.scalar(select(StudioEvent).where(StudioEvent.dedupe_key == "cliffside_video_1:note:0"))
    assert "not included" in note.message and note.severity == Severity.INFO


def test_only_real_productions_are_imported(db_session, data_dir):
    import_all(db_session, data_dir)
    projects = db_session.scalars(select(StudioProject)).all()
    assert sorted(p.slug for p in projects) == ["alpine_video_2", "cliffside_video_1"]
    assert all(p.source == ProjectSource.MANIFEST for p in projects)


def test_agents_seeded_for_every_room_without_fake_status(db_session, data_dir):
    import_all(db_session, data_dir)
    agents = db_session.scalars(select(StudioAgent)).all()
    assert sorted(a.room_id for a in agents) == sorted(r.id for r in ROOMS)
    assert all(a.status == AgentStatus.IDLE for a in agents)
    assert db_session.get(StudioAgent, "analytics_observatory").status_reason == "No data source yet"


def test_planned_costs_match_pipeline_script_caps():
    for pdef in (ALPINE_VIDEO_2, CLIFFSIDE_VIDEO_1):
        for s in pdef.stages:
            if s.kind == StageKind.ASSEMBLY:
                continue
            module = importlib.import_module(s.script.removesuffix(".py").replace("/", "."))
            cap = getattr(module, "MAX_SPEND_USD", None)
            if cap is None:
                cap = importlib.import_module("scripts.run_alpine_video_2_common").MAX_SPEND_USD_EDIT
            assert s.planned_cost_usd == cap, s.key


# --- missing / broken inputs ---------------------------------------------------------

def test_missing_files_are_handled_gracefully(db_session, data_dir):
    alpine = data_dir / "alpine_video_2"
    (alpine / "shot4_aframe_ribs_raw.mp4").unlink()
    (alpine / "edit3_source_frame.jpg").unlink()
    (alpine / "shot5_last_job.json").write_text("{not json")

    results = import_all(db_session, data_dir)
    assert all(r.found and r.error is None for r in results)
    stages = _stages(db_session, "alpine_video_2")
    assert stages["shot4"].status == StageStatus.COMPLETE and stages["shot4"].latest_output_exists is False
    assert stages["edit3_framing_complete"].previous_frame_exists is False
    assert stages["shot5"].provider_job_id is None
    severities = {e.dedupe_key.split(":")[2]: e.severity for e in db_session.scalars(
        select(StudioEvent).where(StudioEvent.type == "warning")) if e.dedupe_key.count(":") >= 3}
    assert severities == {"missing_output": Severity.MEDIUM, "missing_previous_frame": Severity.LOW}


def test_missing_or_malformed_manifest_is_skipped(db_session, data_dir):
    (data_dir / "alpine_video_2" / "manifest.json").unlink()
    (data_dir / "cliffside_video_1" / "manifest.json").write_text("{truncated")

    results = import_all(db_session, data_dir)
    assert [r.found for r in results] == [False, False]
    assert "No manifest" in results[0].error and "not valid JSON" in results[1].error
    assert db_session.scalar(select(func.count()).select_from(StudioProject)) == 0


def test_started_but_incomplete_stage_needs_human_review(db_session, data_dir):
    alpine = data_dir / "alpine_video_2"
    manifest = _read(alpine / "manifest.json")
    manifest["shot6"] = {"video_model": "wan", "estimated_cost_usd": 0.55, "raw_video_path": None,
                         "actual_cost_usd": None, "completed_at": None}
    _write(alpine / "manifest.json", manifest)
    (alpine / "shot6_last_job.json").write_text(json.dumps({"provider_job_id": "job-6"}))

    import_all(db_session, data_dir)
    shot6 = _stages(db_session, "alpine_video_2")["shot6"]
    assert shot6.status == StageStatus.STARTED and shot6.requires_human_review
    event = db_session.scalar(select(StudioEvent).where(StudioEvent.dedupe_key == "alpine_video_2:shot6:started_incomplete"))
    assert event.severity == Severity.HIGH and "recover_fal_video_job job-6" in event.message
    project = db_session.scalar(select(StudioProject).where(StudioProject.slug == "alpine_video_2"))
    assert project.production_stage == "Shot 6 - Glass Facade - in flight or interrupted"
    assert project.budget.planned_remaining_spend_usd == pytest.approx(0.55 + 0.15 + 0.50 + 0.15 + 0.25)


# --- read-only guarantee ---------------------------------------------------------

def test_importer_never_mutates_or_creates_pipeline_files(db_session, data_dir):
    (data_dir / "alpine_video_2" / "shot4_aframe_ribs_raw.mp4").unlink()  # exercise the warning paths too
    before = _snapshot_files(data_dir)
    import_all(db_session, data_dir)
    import_all(db_session, data_dir)
    assert _snapshot_files(data_dir) == before


REAL_DATA = ROOT_DIR / "data"
REAL_MANIFESTS = [REAL_DATA / p.slug / "manifest.json" for p in (ALPINE_VIDEO_2, CLIFFSIDE_VIDEO_1)]


@pytest.mark.skipif(not all(p.exists() for p in REAL_MANIFESTS), reason="real production data not present")
def test_real_manifests_import_read_only_and_match_pipeline_budget(db_session):
    from scripts.run_alpine_video_2_common import load_manifest, spent_so_far

    before = {p: (hashlib.sha256(p.read_bytes()).hexdigest(), p.stat().st_mtime_ns) for p in REAL_MANIFESTS}
    results = import_all(db_session, REAL_DATA)
    import_all(db_session, REAL_DATA)
    assert {p: (hashlib.sha256(p.read_bytes()).hexdigest(), p.stat().st_mtime_ns) for p in REAL_MANIFESTS} == before

    alpine = next(r for r in results if r.slug == "alpine_video_2")
    assert alpine.found and alpine.spent_usd == spent_so_far(load_manifest())
