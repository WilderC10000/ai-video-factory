"""Doctrine checks on a project spec - run before any still is briefed or any clip is priced.

Errors block production (the studio will not brief stills or submit clips while any exist); warnings are
shown for review. Each check names the Creative Brain rule or production lesson it enforces.
"""
from dataclasses import dataclass

from app.forma.production.spec import COMPLEXITY_CLIPS, ProjectSpec
from app.forma.routing import CANDIDATE_UNPROVEN, RoutingError, select_video_model
from app.providers.video.fal import FAL_VIDEO_MODELS

MAX_CLIP_SECONDS = 5  # a single anchored clip is one local task, not a phase (lesson 3)


@dataclass(frozen=True)
class Problem:
    level: str  # "error" | "warning"
    where: str
    rule: str
    message: str


def check(spec: ProjectSpec) -> list[Problem]:
    out: list[Problem] = []

    def err(where, rule, msg):
        out.append(Problem("error", where, rule, msg))

    def warn(where, rule, msg):
        out.append(Problem("warning", where, rule, msg))

    ids = [c.id for c in spec.checkpoints]
    if len(set(ids)) != len(ids):
        err("checkpoints", "unique ids", "checkpoint ids repeat")
    for cp in spec.checkpoints:
        if cp.camera not in spec.cameras:
            err(cp.id, "camera bible", f"camera {cp.camera!r} is not defined in cameras")

    # Construction order and material flow (rules 2, 8; lessons 4-6): nothing regresses, every new element
    # has a visible material source.
    for prev, cp in zip(spec.checkpoints, spec.checkpoints[1:]):
        lost = [e for e in prev.built if e not in cp.built]
        if lost:
            err(cp.id, "no regression", f"elements disappear after {prev.id}: {', '.join(lost)}")
        for element in (e for e in cp.built if e not in prev.built):
            if not cp.materials.get(element):
                err(cp.id, "material flow", f"new element {element!r} has no visible material source")

    # Shots join consecutive checkpoints, one shot per gap.
    for shot, (a, b) in zip(spec.shots, zip(ids, ids[1:])):
        if (shot.from_cp, shot.to_cp) != (a, b):
            err(shot.id, "checkpoint chain", f"shots must join consecutive checkpoints in order ({a} -> {b})")
    if spec.checkpoints and len(spec.shots) != len(spec.checkpoints) - 1:
        err("shots", "checkpoint chain", f"{len(spec.checkpoints)} checkpoints need {len(spec.checkpoints) - 1} shots")

    for shot in spec.shots:
        # Adaptive clip count (lesson 11).
        n = len(shot.beats)
        if shot.complexity == "static":
            if shot.shot_class != "time_jump" or n:
                err(shot.id, "static = still edit", "a static shot is a time_jump with no beats (still edit only)")
            continue
        if shot.shot_class == "time_jump":
            err(shot.id, "static = still edit", "time_jump shots must be complexity 'static'")
        allowed = {"simple": (1,), "medium": (2,), "complex": (2, COMPLEXITY_CLIPS["complex"])}[shot.complexity]
        if n not in allowed:
            err(shot.id, "adaptive clip count",
                f"{shot.complexity} shot has {n} beats (simple 1, medium 2, complex 2-3)")
        for i, beat in enumerate(shot.beats, 1):
            if not beat.task.strip() or not beat.location.strip():
                err(f"{shot.id} beat {i}", "one local task", "every beat needs a task and a work location")
            if not 3 <= beat.duration_seconds <= MAX_CLIP_SECONDS:
                err(f"{shot.id} beat {i}", "one local task", f"clips are 3-{MAX_CLIP_SECONDS} s")
        # Camera vs construction (lesson 7; rule 7: camera changes happen only at cuts).
        if shot.camera_moves and shot.shot_class != "environmental":
            err(shot.id, "camera vs complexity", "camera movement is only planned on environmental shots")
        cams = {spec.checkpoint(shot.from_cp).camera, spec.checkpoint(shot.to_cp).camera}
        if len(cams) > 1 and not shot.camera_moves:
            err(shot.id, "stable cameras", f"{shot.from_cp} and {shot.to_cp} use different cameras - change the "
                                           "camera at a static cut (time_jump) or plan an environmental camera move")
        # Routing (lesson 11): a model must exist; unproven routes only as a proof.
        try:
            route = select_video_model(shot.shot_class, allow_unproven=shot.proof, model=shot.model)
        except RoutingError as e:
            err(shot.id, "model routing", str(e))
            continue
        if route.status == CANDIDATE_UNPROVEN:
            warn(shot.id, "proof before scaling", f"{route.model} is unproven for {shot.shot_class}: this shot is a proof")
        cfg = FAL_VIDEO_MODELS[route.model]
        for i, beat in enumerate(shot.beats, 1):
            if cfg.allowed_durations and beat.duration_seconds not in cfg.allowed_durations:
                err(f"{shot.id} beat {i}", "model limits",
                    f"{route.model} takes {list(cfg.allowed_durations)} s, not {beat.duration_seconds}")
        if cfg.end_image_param_name is None:
            err(shot.id, "anchored clips", f"{route.model} cannot pin an end still")
    return out


def errors(spec: ProjectSpec) -> list[Problem]:
    return [p for p in check(spec) if p.level == "error"]
