"""Which studio stages can be executed from the UI, and how.

A stage is launchable when its pipeline script exposes a service-form entry
point: Alpine shot/edit scripts define `SPEC`, multi-stage scripts (the train
car) define `SPECS` keyed by stage (run through execute_generate / execute_edit /
execute_video_shot), and final assembly scripts define `assemble_final`. A
script may also define `launch_blockers(stage_key, manifest_path)` - its own
gates (run order, proof gate), which the studio shows and enforces. Scripts without one (e.g. the site reference, Shots 1-2, all
of Cliffside) stay CLI-only - the studio says so instead of guessing.

The scripts are imported, never shelled out to, so the exact same code the
CLI runs is what the studio runs.
"""
import importlib
from dataclasses import dataclass
from functools import cache

from app.studio.importers.stage_maps import PROJECTS_BY_SLUG, StageDef
from app.studio.models import StageKind


@dataclass(frozen=True)
class StageAction:
    project_slug: str
    stage: StageDef
    module_name: str
    paid: bool

    @property
    def kind(self) -> StageKind:
        return self.stage.kind

    def module(self):
        return importlib.import_module(self.module_name)

    def spec(self):
        module = self.module()
        specs = getattr(module, "SPECS", None)
        if isinstance(specs, dict):
            return specs.get(self.stage.key)
        return getattr(module, "SPEC", None)

    def blockers(self, manifest_path) -> list[str]:
        check = getattr(self.module(), "launch_blockers", None)
        return list(check(self.stage.key, manifest_path)) if callable(check) else []


def _module_name(script_path: str) -> str:
    return script_path.removesuffix(".py").replace("/", ".")


@cache
def get_action(project_slug: str, stage_key: str) -> StageAction | None:
    pdef = PROJECTS_BY_SLUG.get(project_slug)
    stage = next((s for s in pdef.stages if s.key == stage_key), None) if pdef else None
    if stage is None or not stage.script:
        return None
    name = _module_name(stage.script)
    try:
        module = importlib.import_module(name)
    except ImportError:
        return None
    if stage.kind == StageKind.ASSEMBLY:
        return StageAction(project_slug, stage, name, paid=False) if hasattr(module, "assemble_final") else None
    specs = getattr(module, "SPECS", None)
    has_spec = stage.key in specs if isinstance(specs, dict) else getattr(module, "SPEC", None) is not None
    if stage.kind in (StageKind.VIDEO, StageKind.IMAGE_EDIT, StageKind.IMAGE_GENERATE) and has_spec:
        return StageAction(project_slug, stage, name, paid=True)
    return None


@cache
def stage_intent(project_slug: str, stage_key: str) -> dict | None:
    """What the stage was supposed to do, straight from its script: the prompt and
    the review checklist the CLI prints after generation."""
    action = get_action(project_slug, stage_key)
    if action is None:
        return None
    if action.kind == StageKind.ASSEMBLY:
        doc = (action.module().__doc__ or "").strip().split("\n\n")
        return {"title": doc[0] if doc else action.stage.label, "prompt": None,
                "checklist": [], "note": doc[1].replace("\n", " ") if len(doc) > 1 else None}
    spec = action.spec()
    return {
        "title": spec.title,
        "prompt": getattr(spec, "prompt", None) or getattr(spec, "edit_prompt", None),
        "checklist": list(spec.review_checklist),
        "note": spec.next_step_note,
    }
