"""Which manifests the studio mirrors, and how each manifest key maps to a stage.

Only real FORMA productions are listed here. The older fal_* experiment
folders and forma_video_1_chapter_* are deliberately not imported in v0.1.

planned_cost_usd mirrors each stage script's own MAX_SPEND_USD constant
(tests/test_studio_importer.py asserts they stay in sync) so the studio can
show planned spend for stages that have not run yet without importing, and
thereby executing, any pipeline script at runtime.
"""
from dataclasses import dataclass, field
from pathlib import Path

from app.studio.models import StageKind

EDIT_CAP = 0.15  # NANO_BANANA_PRO_EDIT flat rate, used by every checkpoint edit


@dataclass(frozen=True)
class StageDef:
    key: str
    label: str
    kind: StageKind
    room_id: str
    script: str | None
    planned_cost_usd: float | None
    job_state_file: str | None = None  # <x>_last_job.json written when a fal job is submitted
    storyboard_ref: str | None = None  # storyboard reference image, relative to the project folder


@dataclass(frozen=True)
class ProjectDef:
    slug: str
    name: str
    cap_usd: float | None           # used only when the manifest records no budget_cap_usd
    cap_source: str | None
    stages: list[StageDef]
    notes: list[str] = field(default_factory=list)  # standing info-level facts about the project
    spec_driven: bool = False  # Project #3 on: stages come from <project>/project.json (app.forma.production)
    frozen: bool = False  # R&D history: viewable and recoverable, never launched or submitted again


def _video(key, label, script, cost, job_file):
    return StageDef(key, label, StageKind.VIDEO, "render_bay", script, cost, job_file)


def _edit(key, label, script):
    return StageDef(key, label, StageKind.IMAGE_EDIT, "build_logic_workshop", script, EDIT_CAP)


def _assembly(key, label, script):
    return StageDef(key, label, StageKind.ASSEMBLY, "edit_suite", script, 0.0)


ALPINE_VIDEO_2 = ProjectDef(
    slug="alpine_video_2",
    name="FORMA Video #2 - Alpine Lake A-Frame",
    cap_usd=6.50,
    cap_source="manifest budget_cap_usd",
    stages=[
        StageDef("site_reference", "Site reference image", StageKind.IMAGE_GENERATE, "continuity_office",
                 "scripts/run_alpine_video_2_site_reference.py", 0.15),
        _video("shot1", "Shot 1 - Opening + Site Prep", "scripts/run_alpine_video_2_shot1_opening_prep.py",
               0.35, "shot1_last_job.json"),
        _video("shot2", "Shot 2 - Base + Floor", "scripts/run_alpine_video_2_shot2_base_floor.py",
               0.50, "shot2_last_job.json"),
        _edit("edit1_base_floor_complete", "Checkpoint 1 - Base/Floor Complete",
              "scripts/run_alpine_video_2_edit1_base_floor_complete.py"),
        _video("shot3", "Shot 3 - Floorboards", "scripts/run_alpine_video_2_shot3_floorboards.py",
               0.65, "shot3_last_job.json"),
        _edit("edit2_floor_complete", "Checkpoint 2 - Floor Complete",
              "scripts/run_alpine_video_2_edit2_floor_complete.py"),
        _video("shot4", "Shot 4 - A-Frame Ribs [HERO]", "scripts/run_alpine_video_2_shot4_aframe_ribs.py",
               0.75, "shot4_last_job.json"),
        _edit("edit3_framing_complete", "Checkpoint 3 - Framing Complete",
              "scripts/run_alpine_video_2_edit3_framing_complete.py"),
        _video("shot5", "Shot 5 - Roof + Cladding", "scripts/run_alpine_video_2_shot5_roof_cladding.py",
               0.60, "shot5_last_job.json"),
        _edit("edit4_roof_complete", "Checkpoint 4 - Roof/Cladding Complete",
              "scripts/run_alpine_video_2_edit4_roof_complete.py"),
        _video("shot6", "Shot 6 - Glass Facade", "scripts/run_alpine_video_2_shot6_glass.py",
               0.55, "shot6_last_job.json"),
        _edit("edit5_glass_complete", "Checkpoint 5 - Glass Complete + Interior Move",
              "scripts/run_alpine_video_2_edit5_glass_complete.py"),
        _video("shot7", "Shot 7 - Interior Design", "scripts/run_alpine_video_2_shot7_interior.py",
               0.50, "shot7_last_job.json"),
        _edit("edit6_exterior_reveal_viewpoint", "Checkpoint 6 - Exterior Reveal Viewpoint",
              "scripts/run_alpine_video_2_edit6_exterior_reveal_viewpoint.py"),
        _video("shot8", "Shot 8 - Final Reveal", "scripts/run_alpine_video_2_shot8_reveal.py",
               0.25, "shot8_last_job.json"),
        _assembly("final_assembly", "Final assembly", "scripts/run_alpine_video_2_final_assembly.py"),
    ],
)

CLIFFSIDE_VIDEO_1 = ProjectDef(
    slug="cliffside_video_1",
    name="FORMA Video #1 - Cliffside",
    cap_usd=5.00,
    cap_source="scripts/run_cliffside_video_1_budget_check.py DEFAULT_CAP_USD (Part 2 authorization)",
    stages=[
        _assembly("rough_assembly", "Part 1 rough assembly", "scripts/run_cliffside_video_1_rough_assembly.py"),
        _edit("decking_complete_edit", "Checkpoint - Decking Complete",
              "scripts/run_cliffside_video_1_decking_complete_edit.py"),
        _video("framing", "Framing", "scripts/run_cliffside_video_1_part2_framing.py", 0.30, "framing_last_job.json"),
        _edit("framing_complete_edit", "Checkpoint - Framing Complete",
              "scripts/run_cliffside_video_1_part2_framing_edit.py"),
        _video("glass", "Glass + Door", "scripts/run_cliffside_video_1_part2_glass.py", 0.25, "glass_last_job.json"),
        _edit("exterior_complete_edit", "Checkpoint - Exterior Complete",
              "scripts/run_cliffside_video_1_part2_exterior_edit.py"),
        _video("reveal", "Reveal", "scripts/run_cliffside_video_1_part2_reveal.py", 0.35, "reveal_last_job.json"),
        _assembly("final_assembly", "Final assembly", "scripts/run_cliffside_video_1_final_assembly.py"),
    ],
    notes=[
        "Part 1 clips (segments 1a/1b/2 and decking) were generated in the fal_* experiment folders, "
        "which are not imported in v0.1 - their spend is not included in this budget.",
    ],
)

def _train_car() -> ProjectDef:
    """Built from the 20-checkpoint plan, in its incremental execution order."""
    from scripts import run_train_car_video_2_plan as plan

    stages = {s.key: s for s in plan.build_stage_plan()}
    kinds = {"image_generate": StageKind.IMAGE_GENERATE, "image_edit": StageKind.IMAGE_EDIT, "video": StageKind.VIDEO}
    defs = []
    beat_stills = {}  # manual intermediate stills, shown (and uploadable) right before the clip that needs them
    for beat in plan.BEAT_STILLS.values():
        beat_stills.setdefault(f"clip{beat.checkpoint:02d}", []).append(
            StageDef(beat.key, beat.label, StageKind.IMAGE_EDIT, "continuity_office", None, 0.0))
    for key in plan.execution_order(list(stages.values())):
        defs.extend(beat_stills.get(key, []))
        st = stages[key]
        if st.kind == "video":
            room = "render_bay"
        elif key.endswith("_bridge") or st.kind == "image_generate":
            room = "continuity_office"  # camera changes / establishing reference
        else:
            room = "build_logic_workshop"  # checkpoint construction states
        manual_still = st.kind != "video" and plan.STILLS_SOURCE == "manual"
        defs.append(StageDef(
            key, st.label, kinds[st.kind], room, "scripts/run_train_car_video_2_stage.py",
            0.0 if manual_still else st.estimated_cost_usd,
            f"clips/{key}_last_job.json" if st.kind == "video" else None,
            storyboard_ref=f"storyboard/cp{st.checkpoint:02d}.jpg",
        ))
    return ProjectDef(
        slug=plan.SLUG, name=f"{plan.PROJECT_NAME} [R&D - frozen]", cap_usd=None, cap_source=None, stages=defs,
        frozen=True,
        notes=["FROZEN 2026-09-28 as R&D history (Project #2): Wan, Higgsfield and Kling proofs are kept as "
               "evidence; nothing new is launched or submitted from this project. Production continues in "
               "Project #3.",
               f"Proof gate: nothing after {plan.PROOF_STAGE} runs until the first end-frame test is marked passed.",
               *(["Stills are made manually (ChatGPT): place them in stills/ and approve with "
                  "`python -m scripts.run_train_car_video_2_stage --approve-still <key> \"<note>\"` - "
                  "the studio never generates them; only video spends money."]
                 if plan.STILLS_SOURCE == "manual" else []),
               "Doctrine: SKIP REPETITION, NOT EXPLANATION (docs/forma/creative/FORMA_CREATIVE_BRAIN.md)."],
    )


TRAIN_CAR_VIDEO_2 = _train_car()

SPEC_PROJECT_SLUGS = ("forma_project_3",)


def spec_project(slug: str, data_dir: Path | None = None) -> ProjectDef | None:
    """A Project #3-style project, built from its project.json: stills in the Continuity Office (uploaded and
    approved in the studio), clips in the Render Bay (priced, approved and submitted in the studio)."""
    from app.config import settings
    from app.forma.production.spec import SpecError, load_spec
    from app.forma.production.submit import model_config, route_for
    from app.providers.base import VideoGenerationRequest
    from app.providers.video.fal import FalVideoProvider

    path = Path(data_dir or settings.studio_data_path) / slug / "project.json"
    try:
        spec = load_spec(path)
    except SpecError:
        return None
    defs = [StageDef(still.key, still.label, StageKind.IMAGE_EDIT, "continuity_office", None, 0.0)
            for still in spec.stills()]
    order = {s.key: i for i, s in enumerate(spec.stills())}
    for clip in spec.clips():
        try:
            route = route_for(clip)
            est = FalVideoProvider(model_config(route, clip), api_key="-").estimate_cost(VideoGenerationRequest(
                prompt="", duration_seconds=float(clip.beat.duration_seconds)))
        except Exception:
            est = None
        label = f"{clip.shot.id.upper()} clip {clip.n}/{clip.shot.clip_count} - {clip.shot.title}"
        defs.append(StageDef(clip.key, label, StageKind.VIDEO, "render_bay", None, est))
    # Production order: each clip sits between its start still and its end still.
    rank = {clip.key: order[clip.end_still] - 0.5 for clip in spec.clips()}
    defs.sort(key=lambda d: rank.get(d.key, order.get(d.key, 0)))
    return ProjectDef(slug=spec.slug, name=spec.name, cap_usd=spec.budget_cap_usd, cap_source="project.json budget.cap_usd",
                      stages=defs, spec_driven=True, frozen=spec.status == "frozen",
                      notes=[f"Project status: {spec.status}. Stills are uploaded and approved in the studio; every "
                             "clip needs its own spend approval; nothing is retried automatically."])


PROJECTS: list[ProjectDef] = [ALPINE_VIDEO_2, CLIFFSIDE_VIDEO_1, TRAIN_CAR_VIDEO_2]
PROJECTS_BY_SLUG: dict[str, ProjectDef] = {p.slug: p for p in PROJECTS}


def refresh_spec_projects(data_dir: Path | None = None) -> None:
    """(Re)build spec-driven projects from their project.json - called on every import."""
    for slug in SPEC_PROJECT_SLUGS:
        pdef = spec_project(slug, data_dir)
        PROJECTS[:] = [p for p in PROJECTS if p.slug != slug] + ([pdef] if pdef else [])
        PROJECTS_BY_SLUG.pop(slug, None)
        if pdef:
            PROJECTS_BY_SLUG[slug] = pdef


refresh_spec_projects()
