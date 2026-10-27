"""Generated stills - the default for Project #3: one approval-gated fal image call per still.

    first still (CP01)   text-to-image from its brief (or an edit of `stills.first_still_references`)
    every later still    an EDIT of the previous still in production order (spec.edit_source): its exact
                         approved file and sha256 go to fal, so the previous pixels are authoritative.
                         This covers intermediates, checkpoints after static time jumps and camera changes.

The person drives every step; nothing chains:

    plan()      FREE, local: mode, model, source still, estimate, and every reason it may not run now
    generate()  PAID in live mode ($0 mock provider in mock mode). Needs confirmed=True and max_usd within the
                per-still ceiling and the project cap. The attempt is written to the manifest as <key>__genN
                with the estimate counted as spent BEFORE fal is called (corrected to $0 only if fal refused the
                request). The result is placed as <key>.png - `placed`, never auto-approved - and nothing else
                happens: no retry, no next still, no clip.

Approval and replacement use stills.py exactly like an upload, so a manual upload stays an optional override
for any still, and a still regenerated after approval is `changed` (its clips blocked) until approved again.
"""
import json
import os
import shutil
import subprocess
from datetime import datetime, timedelta, timezone
from pathlib import Path

from app.forma.production import budget, continuity, stills
from app.forma.production.spec import ProjectSpec
from app.providers.base import ImageEditRequest, ImageGenerationRequest, ImageProviderError
from app.providers.image.fal import (
    NANO_BANANA_2_EDIT,
    NANO_BANANA_2_GENERATE,
    NANO_BANANA_EDIT,
    NANO_BANANA_GENERATE,
    NANO_BANANA_PRO_EDIT,
    NANO_BANANA_PRO_GENERATE,
    FalImageModelConfig,
    FalImageProvider,
)

# The still models a project may name. Status is this repo's own evidence, like app.forma.routing for video.
STILL_MODELS: dict[str, tuple[FalImageModelConfig, str]] = {
    NANO_BANANA_GENERATE.model_id: (NANO_BANANA_GENERATE, "candidate_unproven"),
    NANO_BANANA_EDIT.model_id: (NANO_BANANA_EDIT, "candidate_unproven"),
    NANO_BANANA_2_GENERATE.model_id: (NANO_BANANA_2_GENERATE, "candidate_unproven"),
    NANO_BANANA_2_EDIT.model_id: (NANO_BANANA_2_EDIT, "candidate_unproven"),
    # Used for the Alpine / Video #1 / train-car checkpoint stills and continuity edit tests (2026-09).
    NANO_BANANA_PRO_GENERATE.model_id: (NANO_BANANA_PRO_GENERATE, "proven"),
    NANO_BANANA_PRO_EDIT.model_id: (NANO_BANANA_PRO_EDIT, "proven"),
}
EDIT_PARAMS = {"aspect_ratio": "auto", "output_format": "png", "limit_generations": True}  # keep the source frame
GENERATE_PARAMS = {"aspect_ratio": "9:16", "output_format": "png"}
IN_FLIGHT_SECONDS = 600  # a generation started this recently and never finished blocks another one


class StillGenError(Exception):
    def __init__(self, message: str, status: int = 409, problems: list[str] | None = None):
        super().__init__(message)
        self.status, self.problems = status, problems or []


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _read(manifest_path: Path) -> dict:
    return json.loads(Path(manifest_path).read_text())


def _write(manifest_path: Path, manifest: dict) -> None:
    tmp = Path(manifest_path).with_suffix(".json.tmp")
    tmp.write_text(json.dumps(manifest, indent=2))
    os.replace(tmp, manifest_path)


def generations(manifest: dict, key: str) -> list[tuple[str, dict]]:
    found = [(k, v) for k, v in manifest.items() if isinstance(v, dict) and k.startswith(f"{key}__gen")]
    return sorted(found, key=lambda kv: int(kv[0].rpartition("__gen")[2] or 0))


def _in_flight(entry: dict) -> bool:
    if entry.get("status") != "running":
        return False
    started = datetime.fromisoformat(entry["started_at"])
    return _now() - started < timedelta(seconds=IN_FLIGHT_SECONDS)


def _references(spec: ProjectSpec, manifest_path: Path) -> list[Path]:
    return [Path(manifest_path).parent / r for r in spec.stills_config.first_still_references]


def plan(spec: ProjectSpec, manifest_path: Path, key: str, manifest: dict | None = None, media_url=None) -> dict:
    """FREE, local: what generating this still would do and cost, and why it may not run right now."""
    if key not in spec.still_keys():
        raise StillGenError(f"{key} is not a still of {spec.slug}", 404)
    manifest = manifest if manifest is not None else _read(manifest_path)
    cfg_s = spec.stills_config
    source_key = spec.edit_source(key)
    refs = _references(spec, manifest_path) if source_key is None else []
    mode = "generate" if source_key is None and not refs else "edit"
    # The first still is text-to-image unless it edits reference images; everything else is an edit.
    model = cfg_s.model_for(key, is_first=source_key is None and not refs)
    known = STILL_MODELS.get(model)
    estimate = round(known[0].price_per_image, 4) if known else None
    problems: list[str] = []
    if not cfg_s.can_generate:
        problems.append(f"{spec.slug} uses manual stills only (stills.generation_fallback is false) - upload instead.")
    if spec.status in ("frozen", "paused"):
        problems.append(f"{spec.name} is {spec.status} - no paid generation (set status back to planning to resume).")
    if known is None:
        problems.append(f"{model} is not a known still model ({', '.join(STILL_MODELS)}).")
    if cfg_s.proof_stills and key not in cfg_s.proof_stills:
        problems.append(f"Proof in progress: only {', '.join(cfg_s.proof_stills)} may be generated "
                        "(stills.proof_stills in project.json).")
    source = None
    if source_key is not None:
        st = stills.state(manifest_path, source_key, manifest)
        source = {"key": source_key, "state": st["state"], "path": st.get("path"), "sha256": st.get("sha256"),
                  "url": media_url(st["path"]) if media_url and st.get("path") else None}
        if st["state"] != "approved":
            problems.append(f"The source still {source_key} is {st['state']} - approve it first; every later still "
                            "is an edit of the previous approved still.")
        gate = continuity.required_problem(spec, manifest_path, source_key, manifest)
        if gate:
            problems.append(gate)
    for r in refs:
        if not r.is_file():
            problems.append(f"Reference image {r} does not exist.")
    tries = generations(manifest, key)
    if any(_in_flight(v) for _, v in tries):
        problems.append("A generation of this still is already running.")
    if estimate is not None:
        if estimate > cfg_s.per_still_max_usd + 1e-9:
            problems.append(f"Estimate ${estimate:.4f} is above the per-still ceiling ${cfg_s.per_still_max_usd:.2f}.")
        money = budget.spend(manifest, spec)
        if estimate > money["remaining_usd"] + 1e-9:
            problems.append(f"Project cap: ${money['spent_usd']:.2f} spent + ${money['reserved_usd']:.2f} in flight + "
                            f"${estimate:.4f} would exceed ${money['cap_usd']:.2f} (raise budget.cap_usd in project.json).")
    current = stills.state(manifest_path, key, manifest)
    latest_key, latest = tries[-1] if tries else (None, None)
    # The current file was generated from a source that is no longer the approved source -> regenerate.
    stale_source = bool(latest and source and latest.get("output_sha256") == current.get("sha256")
                        and latest.get("source_sha256") not in (None, source.get("sha256")))
    still = next(s for s in spec.stills() if s.key == key)
    return {"key": key, "source_mode": cfg_s.source, "fallback": cfg_s.source != "generate", "mode": mode,
            "model": model,
            "model_status": known[1] if known else "unknown", "estimate_usd": estimate,
            "model_override": key in cfg_s.model_overrides,
            "per_still_max_usd": cfg_s.per_still_max_usd, "source": source, "references": [str(r) for r in refs],
            "prompt": still.brief, "exists": current["state"] != "missing", "stale_source": stale_source,
            "problems": problems, "budget": budget.spend(manifest, spec),
            "continuity": continuity.info(spec, manifest_path, key, manifest, media_url),
            "attempts": [{"key": k, "status": v.get("status"), "model": v.get("model"), "cost_usd": v.get("actual_cost_usd"),
                          "started_at": v.get("started_at"), "error": v.get("error")} for k, v in tries]}


def generate(spec: ProjectSpec, manifest_path: Path, key: str, *, execution_mode: str, max_usd: float,
             confirmed: bool, replace: bool = False, provider=None) -> dict:
    """ONE image call for ONE still (paid in live mode). Places the result; never approves, retries or continues."""
    if not confirmed:
        raise StillGenError("Confirm the generation (one fal call).", 400)
    if execution_mode not in ("live", "mock"):
        raise StillGenError(f"Execution mode is {execution_mode!r} - generating a still needs STUDIO_EXECUTION_MODE=live "
                            "(paid) or mock (free sandbox).")
    info = plan(spec, manifest_path, key)
    problems = list(info["problems"])
    est = info["estimate_usd"]
    if est is not None and not 0 < max_usd <= spec.stills_config.per_still_max_usd:
        problems.append(f"Approve between $0.01 and the per-still ceiling ${spec.stills_config.per_still_max_usd:.2f}.")
    elif est is not None and est > max_usd + 1e-9:
        problems.append(f"Estimate ${est:.4f} is above the approved ${max_usd:.2f}.")
    try:
        stills.check_replace(manifest_path, key, replace)
    except stills.StillError as e:
        problems.append(str(e))
    if problems:
        raise StillGenError("Not generated.", problems=problems)

    cfg = STILL_MODELS[info["model"]][0]
    if provider is None:
        if execution_mode == "mock":
            from app.providers.image.mock import MockImageProvider
            provider = MockImageProvider(cost_per_megapixel=0.0)
        else:
            provider = FalImageProvider(cfg)
    cost = est if execution_mode == "live" else 0.0
    inputs: list[tuple[str, str]] = []  # (path, sha256) actually sent
    if info["source"]:
        path, sha = stills.approved_file(manifest_path, info["source"]["key"])
        inputs.append((str(path), sha))
    for r in info["references"]:
        inputs.append((r, stills.file_sha256(Path(r))))

    manifest = _read(manifest_path)
    n = len(generations(manifest, key)) + 1
    gen_key = f"{key}__gen{n}"
    manifest[gen_key] = {
        "kind": "still_generation", "still": key, "provider": provider.name, "model": cfg.model_id,
        "mode": info["mode"], "execution_mode": execution_mode, "prompt": info["prompt"],
        "source_still": info["source"]["key"] if info["source"] else None,
        "source_path": inputs[0][0] if info["source"] else None,
        "source_sha256": inputs[0][1] if info["source"] else None,
        "references": [{"path": p, "sha256": h} for p, h in inputs[1 if info["source"] else 0:]],
        "approved_usd": round(float(max_usd), 4), "estimated_cost_usd": cost,
        "actual_cost_usd": cost,  # counted as spent until fal is known to have refused the request
        "status": "running", "started_at": _now().isoformat(), "completed_at": None}
    _write(manifest_path, manifest)

    out = stills.stills_dir(manifest_path) / "_generated" / f"{gen_key}.png"
    try:
        if info["mode"] == "edit":
            params = EDIT_PARAMS if info["source"] else {**EDIT_PARAMS, "aspect_ratio": "9:16"}
            if cfg.supports_resolution:
                params = {**params, "resolution": "1K"}  # pins the flat 1K price
            result = provider.edit_image(ImageEditRequest(info["prompt"], [p for p, _ in inputs], dict(params)), str(out))
        else:
            result = provider.generate_image(ImageGenerationRequest(info["prompt"], 768, 1344, dict(GENERATE_PARAMS)),
                                             str(out))
        data, normalized_from = _to_frame_size(Path(result.file_path), spec.stills_config.frame_size)
        record = stills.place(manifest_path, key, data, original_filename=out.name, source=f"generated ({cfg.model_id})")
    except (ImageProviderError, stills.StillError, OSError, subprocess.CalledProcessError) as e:
        manifest = _read(manifest_path)
        charged = getattr(e, "charged", True) and execution_mode == "live"
        manifest[gen_key].update(status="failed", error=str(e), completed_at=_now().isoformat(),
                                 actual_cost_usd=cost if charged else 0.0)
        _write(manifest_path, manifest)
        raise StillGenError(f"Generation failed ({'may have been charged' if charged else 'not charged'}): {e}",
                            502) from e
    manifest = _read(manifest_path)
    manifest[gen_key].update(status="complete", completed_at=_now().isoformat(),
                             actual_cost_usd=cost if execution_mode == "live" else 0.0,
                             output_path=record["stored_as"], output_sha256=record["sha256"],
                             width=record["width"], height=record["height"],
                             provider_meta=result.meta, replaced=record.get("replaced"),
                             normalized_from=normalized_from)
    manifest.setdefault("still_generations", {})[key] = gen_key
    _write(manifest_path, manifest)
    return {"generation": gen_key, **manifest[gen_key], "state": stills.state(manifest_path, key)["state"]}


def _scale(src: Path, size: tuple[int, int]) -> bytes:
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        raise OSError("ffmpeg is needed to scale a still to the project frame size")
    return subprocess.run([ffmpeg, "-v", "error", "-i", str(src), "-vf", f"scale={size[0]}:{size[1]}:flags=lanczos",
                           "-f", "image2pipe", "-vcodec", "png", "-"], capture_output=True, check=True).stdout


def _to_frame_size(path: Path, size: tuple[int, int] | None) -> tuple[bytes, list[int] | None]:
    """The image bytes at the project frame size (scaled, never cropped: models that change the frame size
    stretch the same scene, so a scale keeps it aligned with the previous still). (bytes, original size or None)."""
    data = path.read_bytes()
    _, w, h = stills.sniff(data)
    if size is None or (w, h) == tuple(size):
        return data, None
    return _scale(path, size), [w, h]


def normalize_approved(spec: ProjectSpec, manifest_path: Path, key: str) -> dict:
    """FREE, local: scale an approved still to the project frame size and carry its approval over (the content
    a person approved is unchanged; only the pixel dimensions are). The original goes to stills/_replaced/."""
    size = spec.stills_config.frame_size
    if size is None:
        raise StillGenError("project.json stills.frame_size is not set.", 400)
    manifest = _read(manifest_path)
    st = stills.state(manifest_path, key, manifest)
    if st["state"] != "approved":
        raise StillGenError(f"{key} is {st['state']} - only an approved still is normalized (approve it first).")
    data, original = _to_frame_size(Path(st["path"]), size)
    if original is None:
        return {"key": key, "normalized": False, "size": list(size)}
    previous = manifest[key]
    record = stills.place(manifest_path, key, data, original_filename=f"{key}.png",
                          source=f"normalized to {size[0]}x{size[1]} from {original[0]}x{original[1]}")
    manifest = _read(manifest_path)
    manifest.setdefault("still_normalizations", {})[key] = {**record, "from_size": original,
                                                           "approved_sha256_before": previous.get("approved_sha256")}
    _write(manifest_path, manifest)
    note = (f"Scaled {original[0]}x{original[1]} -> {size[0]}x{size[1]} (normalization only). Content approval carried "
            f"over: {previous.get('approval_note')}")
    stills.approve(manifest_path, key, note)
    return {"key": key, "normalized": True, "from": original, "size": list(size), "sha256": record["sha256"]}
