"""FORMA Video #2 (train car) - 20-checkpoint plan invariants. Pure local, no API calls."""
import ast
from pathlib import Path

import pytest

from scripts import run_train_car_video_2_plan as plan

CHECKPOINTS = plan.CHECKPOINTS
STAGES = plan.build_stage_plan()
STILLS = {s.key: s for s in STAGES if s.phase == "A"}
CLIPS = [s for s in STAGES if s.phase == "B"]


def test_twenty_checkpoints_cover_sixty_seconds_contiguously_with_rising_progress():
    assert [cp.number for cp in CHECKPOINTS] == list(range(1, 21))
    assert CHECKPOINTS[0].start_s == 0 and CHECKPOINTS[-1].end_s == 60
    for prev, cp in zip(CHECKPOINTS, CHECKPOINTS[1:]):
        assert cp.start_s == prev.end_s
        assert cp.progress > prev.progress
    assert CHECKPOINTS[-1].progress == 100


def test_every_checkpoint_has_the_required_fields():
    for cp in CHECKPOINTS:
        assert cp.title and cp.state and cp.action and cp.not_yet, cp.key
        assert cp.camera in plan.CAMERAS and cp.storyboard_camera, cp.key
        assert cp.number == 20 or cp.tools, cp.key          # the reveal uses no tools
        assert cp.number in (1, 20) or cp.adds, cp.key       # every build checkpoint adds something


def test_exists_and_not_yet_are_consistent():
    for cp in CHECKPOINTS:
        exists, not_yet = set(plan.must_exist(cp)), set(plan.must_not_exist(cp))
        assert not exists & set(cp.adds), cp.key          # nothing is introduced twice
        assert not (exists & not_yet), cp.key             # nothing both required and forbidden
        assert not (set(cp.adds) & not_yet), cp.key
    assert plan.must_exist(CHECKPOINTS[0]) == []
    assert plan.must_not_exist(CHECKPOINTS[-1]) == [CHECKPOINTS[-1].not_yet]


def test_one_clip_per_checkpoint_each_ending_exactly_on_its_checkpoint_still():
    assert [c.checkpoint for c in CLIPS] == list(range(1, 21))
    for clip in CLIPS[1:]:
        assert clip.end_frame == f"cp{clip.checkpoint:02d}_still"
        start = STILLS[clip.source]
        # Adjacent only: a clip starts from the previous checkpoint or from a bridge of that same state.
        assert start.checkpoint in (clip.checkpoint - 1, clip.checkpoint)
        if start.checkpoint == clip.checkpoint:
            assert start.key.endswith("_bridge") and not start.construction_delta


def test_no_construction_clip_changes_camera():
    for clip in CLIPS[1:]:
        start, end = STILLS[clip.source], STILLS[clip.end_frame]
        if clip.construction_delta:
            assert start.camera == end.camera == clip.camera, clip.key
    reveal = CLIPS[-1]
    assert not reveal.construction_delta and STILLS[reveal.source].camera != reveal.camera


def test_every_still_is_an_edit_of_an_earlier_still():
    order = [s.key for s in STAGES if s.phase == "A"]
    assert STILLS["cp01_still"].kind == "image_generate"
    for key in order[1:]:
        still = STILLS[key]
        assert still.kind == "image_edit" and still.source in STILLS
        assert order.index(still.source) < order.index(key), key  # previous pixels stay authoritative


def test_bridges_sit_exactly_where_the_camera_changes():
    bridges = sorted(k for k in STILLS if k.endswith("_bridge"))
    expected = sorted(
        f"cp{cp.number:02d}_bridge" for prev, cp in zip(CHECKPOINTS, CHECKPOINTS[1:])
        if cp.camera != prev.camera and cp.adds
    )
    assert bridges == expected == ["cp02_bridge", "cp04_bridge", "cp05_bridge", "cp07_bridge",
                                   "cp08_bridge", "cp16_bridge", "cp19_bridge"]
    # A bridge re-uses the last still from its own camera when one exists (interior pixels stay interior).
    assert STILLS["cp07_bridge"].source == "cp04_still"
    assert STILLS["cp16_bridge"].source == "cp07_still"


def test_final_timing_and_cost_estimate():
    c = plan.cost_summary(STAGES)
    assert c["final_seconds"] == 60
    assert all(clip.accel_factor >= 1.0 for clip in CLIPS)
    assert (c["stills"], c["bridges"], c["clips"]) == (27, 7, 20)
    assert c["phase_a_usd"] == pytest.approx(27 * 0.15)
    assert c["phase_b_usd"] == pytest.approx(c["raw_video_seconds"] * 0.05)
    assert c["total_usd"] == pytest.approx(c["phase_a_usd"] + c["phase_b_usd"])


def test_plan_module_makes_no_provider_calls():
    tree = ast.parse(Path(plan.__file__).read_text(encoding="utf-8"))
    imported = {getattr(n, "module", None) or "" for n in ast.walk(tree) if isinstance(n, ast.ImportFrom)}
    imported |= {a.name for n in ast.walk(tree) if isinstance(n, ast.Import) for a in n.names}
    assert not any(m.startswith(("app.providers", "httpx", "requests")) for m in imported)


@pytest.mark.skipif(not plan.STORYBOARD_DECK.exists(), reason="storyboard deck not present")
def test_storyboard_images_extract_one_per_checkpoint(tmp_path):
    written = plan.extract_storyboard_images(plan.STORYBOARD_DECK, tmp_path)
    assert set(written) == {"overview"} | {f"cp{n:02d}" for n in range(1, 21)}
    assert all(Path(p).stat().st_size > 1000 for p in written.values())


# --- decisions of 2026-09-24: order fix, incremental gating, doctrine in prompts -------------

def test_glass_precedes_cladding_and_nothing_regresses():
    titles = {cp.number: cp.title for cp in CHECKPOINTS}
    assert titles[12] == "Install panoramic glass"
    assert titles[13] == "Cladding/weatherproofing begins"
    assert titles[14] == "Exterior cladding near complete + finish"
    cp12 = CHECKPOINTS[11]
    assert "weather wrap and trim" in plan.must_not_exist(cp12)          # cladding cannot appear at CP12
    assert "panoramic glass" in plan.must_exist(CHECKPOINTS[12])        # glass stays at CP13 and after
    assert "panoramic glass" in plan.must_exist(CHECKPOINTS[13])
    assert plan.STORYBOARD_SLIDE[12] == 20 and plan.STORYBOARD_SLIDE[13] == 18 and plan.STORYBOARD_SLIDE[14] == 19


def test_budget_resolution_and_cameras_are_the_decided_ones():
    assert plan.BUDGET_CAP_USD == 15.00 and plan.RESOLUTION == "480p"
    assert set(plan.CAMERAS) == {"WIDE", "FACADE", "INTERIOR"}
    assert {cp.camera for cp in CHECKPOINTS} == {"WIDE", "FACADE", "INTERIOR"}


def test_execution_order_starts_with_the_minimal_end_frame_proof():
    order = plan.execution_order(STAGES)
    assert order[:5] == ["cp01_still", "cp02_bridge", "cp02_still", "cp03_still", "clip03"]
    assert order[4] == plan.PROOF_STAGE
    proof_cost = sum(s.estimated_cost_usd for s in STAGES if s.key in order[:5])
    assert proof_cost == pytest.approx(0.90)
    # After the proof: every clip comes after both of its stills.
    for clip in CLIPS:
        for needed in (clip.source, clip.end_frame):
            if needed:
                assert order.index(needed) < order.index(clip.key), clip.key


def test_every_prompt_carries_the_doctrine_and_clips_are_pinned():
    for stage in STAGES:
        prompt = plan.stage_prompt(stage)
        assert "SKIP REPETITION, NOT EXPLANATION" in prompt, stage.key
        assert "9:16" in prompt or stage.kind != "video", stage.key
    for clip in CLIPS[1:]:
        assert "ends exactly on the last image" in plan.stage_prompt(clip) or "end exactly on the last image" in plan.stage_prompt(clip)
    construction = [c for c in CLIPS[1:] if c.construction_delta]
    for clip in construction:
        prompt = plan.stage_prompt(clip)
        assert "locked, no movement" in prompt and "70 to 90" in prompt, clip.key
