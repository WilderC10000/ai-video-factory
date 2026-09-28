"""The only paid step: submit ONE clip as ONE fal job - and the free steps around it (plan, review).

submit() refuses unless: execution mode is live, the spec has no doctrine errors, both anchor stills are
approved (exact hashes), a person approved the spend for this clip and it is unconsumed, the estimate fits
that approval / the per-clip ceiling / the project cap, and no job of this clip is in flight. The job id is
written to the manifest before anything else happens; the studio's free status checks
(app.studio.attempt_status) then carry it through queue -> generate -> download. Nothing is ever retried.
"""
import dataclasses
import json
import os
from datetime import datetime, timezone
from pathlib import Path

from app.forma.production import budget, rules, stills
from app.forma.production.spec import Clip, ProjectSpec
from app.forma.production.state import attempts, clip_state
from app.forma.routing import Route, select_video_model
from app.providers.base import VideoGenerationRequest, VideoProviderError
from app.providers.video.fal import FalVideoModelConfig, FalVideoProvider
from app.studio.attempt_status import is_unfinished, raw_output_path

NEGATIVE = ("morphing, objects appearing or vanishing on their own, teleporting tools or materials, camera "
            "movement, zoom, pan, dissolve, crossfade, different person, different building, on-screen text, blur, "
            "distort, low quality")


class SubmitError(Exception):
    def __init__(self, message: str, status: int = 409, problems: list[str] | None = None):
        super().__init__(message)
        self.status, self.problems = status, problems or []


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def route_for(clip: Clip) -> Route:
    return select_video_model(clip.shot.shot_class, allow_unproven=clip.shot.proof, model=clip.shot.model)


def model_config(route: Route, clip: Clip) -> FalVideoModelConfig:
    cfg = route.config
    if cfg.duration_param is None and "duration" in cfg.extra_payload:  # e.g. Wan 3.0 pins duration in its payload
        cfg = dataclasses.replace(cfg, extra_payload={**cfg.extra_payload, "duration": clip.beat.duration_seconds})
    return cfg


def prompt(spec: ProjectSpec, clip: Clip) -> str:
    cp = spec.checkpoint(clip.shot.from_cp)
    camera = spec.cameras.get(cp.camera, cp.camera)
    move = ("The camera performs only the move described." if clip.shot.camera_moves
            else "Locked camera - no movement, no zoom, no pan.")
    return (f"Vertical 9:16 realistic documentary footage, one continuous {clip.beat.duration_seconds}-second shot. "
            f"Camera: {camera}. {move} It starts exactly on the first image and ends exactly on the last image. "
            f"One local task at {clip.beat.location}: {clip.beat.task}. Same builder ({spec.bibles.get('builder', '')}), "
            f"same structure and location. Every change is caused by the builder's visible hands and tools; "
            "materials come from a visible source and go to a visible destination; nothing morphs, appears or "
            "vanishes on its own.")


def plan(spec: ProjectSpec, manifest_path: Path, clip_key: str) -> dict:
    """FREE, local: everything the studio shows before any spend."""
    clip = spec.clip(clip_key)
    manifest = json.loads(Path(manifest_path).read_text())
    spec_errors = rules.errors(spec)
    try:
        route = route_for(clip)
        cfg = model_config(route, clip)
        request = VideoGenerationRequest(prompt=prompt(spec, clip), duration_seconds=float(clip.beat.duration_seconds),
                                         reference_image_path="start", end_image_path="end")
        estimate = FalVideoProvider(cfg, api_key="(not used)").estimate_cost(request)
        route_out = {"model": route.model, "status": route.status, "evidence": route.evidence}
    except Exception as e:  # routing / pricing problems are shown, not raised
        route_out, estimate = {"model": None, "status": "none", "evidence": str(e)}, None
    st = clip_state(spec, manifest_path, manifest, clip, bool(spec_errors))
    return {"clip": clip.key, "shot": clip.shot.id, "shot_title": clip.shot.title, "n": clip.n,
            "of": clip.shot.clip_count, "shot_class": clip.shot.shot_class, "complexity": clip.shot.complexity,
            "proof": clip.shot.proof, "start_still": clip.start_still, "end_still": clip.end_still,
            "duration_seconds": clip.beat.duration_seconds, "task": clip.beat.task, "location": clip.beat.location,
            "prompt": prompt(spec, clip), "route": route_out, "estimate_usd": estimate, **st,
            "budget_approval": (manifest.get("clip_budget") or {}).get(clip.key),
            "budget": budget.spend(manifest, spec),
            "money_problems": budget.submit_problems(manifest, spec, clip.key, estimate) if estimate else [],
            "spec_errors": [f"{p.where}: {p.message}" for p in spec_errors]}


def submit(spec: ProjectSpec, manifest_path: Path, clip_key: str, *, execution_mode: str,
           provider: FalVideoProvider | None = None) -> dict:
    """PAID: exactly one fal job for this clip. Returns the recorded attempt entry."""
    if execution_mode != "live":
        raise SubmitError(f"Execution mode is {execution_mode!r} - paid submissions need STUDIO_EXECUTION_MODE=live.")
    if spec.status == "frozen":
        raise SubmitError(f"{spec.name} is frozen - no new submissions.")
    info = plan(spec, manifest_path, clip_key)
    problems = list(info["spec_errors"]) + list(info["money_problems"])
    if info["state"] != "budget_approved":
        problems.insert(0, f"Clip is {info['state']}: " + ("; ".join(info["reasons"]) or "not ready to submit"))
    if info["estimate_usd"] is None:
        problems.append(f"No model/price: {info['route']['evidence']}")
    manifest = json.loads(Path(manifest_path).read_text())
    if any(is_unfinished(v) for _, v in attempts(manifest, clip_key)):
        problems.append("A job for this clip is already in flight.")
    if problems:
        raise SubmitError("Not submitted.", problems=problems)

    clip = spec.clip(clip_key)
    route = route_for(clip)
    cfg = model_config(route, clip)
    (start, start_sha), (end, end_sha) = (stills.approved_file(manifest_path, clip.start_still),
                                          stills.approved_file(manifest_path, clip.end_still))
    extra = {"negative_prompt": NEGATIVE} if "negative_prompt" in cfg.passthrough_params else {}
    request = VideoGenerationRequest(prompt=info["prompt"], reference_image_path=str(start), end_image_path=str(end),
                                     duration_seconds=float(clip.beat.duration_seconds), extra_params=extra)
    provider = provider or FalVideoProvider(cfg)
    provider.check_request(request)
    image_url, end_url = provider.upload_image(str(start)), provider.upload_image(str(end))  # free
    payload = provider.build_payload(request, image_url, end_url)
    estimate = provider.estimate_cost(request)
    n = len(attempts(manifest, clip_key)) + 1
    key = f"{clip_key}__attempt{n}"
    try:
        submitted = provider.submit_payload(payload, estimate)
    except VideoProviderError as e:  # rejected at submission: no job, nothing charged, approval stays open
        raise SubmitError(f"fal rejected the request (no job, not charged): {e}") from e
    manifest = json.loads(Path(manifest_path).read_text())
    manifest[key] = {
        "provider": "fal", "video_model": route.model, "route_status_at_submit": route.status,
        "shot": clip.shot.id, "beat": {"n": clip.n, "of": clip.shot.clip_count, "group": clip.shot.id},
        "payload": payload, "estimated_cost_usd": estimate, "approved_usd": manifest["clip_budget"][clip_key]["max_usd"],
        "provider_job_id": submitted.provider_job_id, "meta": submitted.meta,
        "start_still": clip.start_still, "start_frame_path": str(start), "start_frame_sha256": start_sha,
        "end_still": clip.end_still, "end_frame_path": str(end), "end_frame_sha256": end_sha,
        "submitted_at": _now(), "provider_status": None, "status_checked_at": None,
        "planned_output_path": str(raw_output_path(manifest_path, key, route.model)),
        "raw_video_path": None, "actual_cost_usd": None, "completed_at": None}
    manifest["clip_budget"][clip_key]["consumed_by"] = key
    tmp = Path(manifest_path).with_suffix(".json.tmp")
    tmp.write_text(json.dumps(manifest, indent=2))
    os.replace(tmp, manifest_path)
    return {"attempt": key, **manifest[key]}


def review(spec: ProjectSpec, manifest_path: Path, clip_key: str, attempt_key: str, verdict: str, note: str) -> dict:
    """A person's verdict on a finished attempt. Accept makes it the clip's result; reject frees the clip for
    a new (separately approved) attempt."""
    spec.clip(clip_key)
    if verdict not in ("accept", "reject"):
        raise SubmitError("verdict must be 'accept' or 'reject'", 400)
    manifest = json.loads(Path(manifest_path).read_text())
    entry = manifest.get(attempt_key)
    if not attempt_key.startswith(f"{clip_key}__attempt") or not isinstance(entry, dict):
        raise SubmitError(f"{attempt_key} is not an attempt of {clip_key}.", 404)
    if verdict == "accept" and not (entry.get("completed_at") and entry.get("raw_video_path")):
        raise SubmitError("Only a finished attempt with a video can be accepted.")
    now = _now()
    entry["review"] = {"verdict": "accepted" if verdict == "accept" else "rejected", "note": note.strip(), "at": now}
    if verdict == "accept":
        manifest[clip_key] = {**{k: v for k, v in entry.items() if k != "actual_cost_usd"},  # cost stays on the attempt
                              "accepted_attempt": attempt_key, "accepted_at": now, "actual_cost_usd": 0.0}
    tmp = Path(manifest_path).with_suffix(".json.tmp")
    tmp.write_text(json.dumps(manifest, indent=2))
    os.replace(tmp, manifest_path)
    return entry["review"]
