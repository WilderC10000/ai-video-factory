"""Which studio projects have manual (ChatGPT) stills, and what the studio shows / does for each.

Local only: listing, uploading and approving stills never calls a provider or generates anything.
Covers Project #3 (from its project.json) and the frozen train-car project (its plan + beat stills).
"""
import json
from functools import lru_cache
from pathlib import Path

from app.forma.production import stills
from app.forma.production.spec import SpecError, load_spec


def _train_car_catalog(manifest_path: Path) -> dict[str, dict]:
    from scripts import run_train_car_video_2_plan as plan

    if plan.STILLS_SOURCE != "manual":
        return {}
    stages = plan.build_stage_plan()
    users: dict[str, list[str]] = {}
    for st in stages:
        if st.kind == "video":
            for k in (st.source, st.end_frame):
                if k:
                    users.setdefault(k, []).append(st.key)
    for setup_file in (manifest_path.parent / "provider_tests").glob("*/setup.json"):
        try:
            setup = json.loads(setup_file.read_text())
        except (OSError, ValueError):
            continue
        for k in (setup.get("stills") or {}).get("start"), (setup.get("stills") or {}).get("end"):
            if k and setup.get("attempt_key") and setup["attempt_key"] not in users.setdefault(k, []):
                users[k].append(setup["attempt_key"])
    out = {st.key: {"label": st.label, "brief": None, "used_by": users.get(st.key, [])}
           for st in stages if st.kind != "video"}
    for key, beat in plan.BEAT_STILLS.items():
        out[key] = {"label": beat.label, "brief": beat.brief, "used_by": users.get(key, [])}
    return out


def _spec_catalog(manifest_path: Path) -> dict[str, dict]:
    try:
        spec = load_spec(manifest_path.parent / "project.json")
    except SpecError:
        return {}
    return {s.key: {"label": s.label, "brief": s.brief, "used_by": spec.dependents(s.key)} for s in spec.stills()}


@lru_cache(maxsize=None)
def _catalog_builder(slug: str):
    from app.studio.importers.stage_maps import PROJECTS_BY_SLUG

    pdef = PROJECTS_BY_SLUG.get(slug)
    if pdef is None:
        return None
    if pdef.spec_driven:
        return _spec_catalog
    if slug == "train_car_video_2":
        return _train_car_catalog
    return None


def catalog(slug: str, manifest_path: Path) -> dict[str, dict]:
    build = _catalog_builder(slug)
    return build(Path(manifest_path)) if build else {}


def infos(slug: str, manifest_path: Path, manifest: dict | None = None, media_url=None) -> dict[str, dict]:
    cat = catalog(slug, manifest_path)
    if not cat:
        return {}
    manifest = manifest if manifest is not None else json.loads(Path(manifest_path).read_text())
    return {key: stills.info(manifest_path, key, label=c["label"], dependents=c["used_by"], manifest=manifest,
                             brief=c["brief"], media_url=media_url)
            for key, c in cat.items()}
