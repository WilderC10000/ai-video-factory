"""Continuity checkpoints for chained still edits (still doctrine rule 3).

Every generated still after the first is an edit of the previous one, so small drift can accumulate. Every
CONTINUITY_EVERY chained edits since the last major anchor (the first still, or the first still of a new
camera), the still at that depth is compared against the anchor before the chain may continue:

    measure()   FREE, local (ffmpeg): frame offset and PSNR of the background band, anchor vs still
    record()    a person's verdict on geometry, camera, builder identity and environment
    required_problem()   why the next still may not be generated yet (used by still_gen.plan)

The numbers flag drift; the person decides. A failed check blocks the chain: regenerate the drifted still
or move to the next image tier.
"""
import json
import os
import shutil
import subprocess
from datetime import datetime, timezone
from pathlib import Path

from app.forma.production import stills
from app.forma.production.spec import ProjectSpec

CONTINUITY_EVERY = 5
DIMENSIONS = ("geometry", "camera", "builder", "environment")
_W, _H = 192, 336  # 9:16 analysis size (1 px here = 4 px of a 768 px wide still)
_BAND = 0.30  # top band (sky / trees / slope): background that construction should not touch
_MAX_SHIFT = 4
FLAG_SHIFT_PCT = 2.0
FLAG_BAND_PSNR = 18.0
_CACHE: dict[tuple[str, str], dict] = {}


def chain_position(spec: ProjectSpec, key: str) -> tuple[str, int]:
    """(anchor key, number of chained edits from the anchor to this still)."""
    depth, cur = 0, key
    while True:
        src = spec.edit_source(cur)
        if src is None or spec.still_camera(src) != spec.still_camera(cur):
            return cur, depth
        depth, cur = depth + 1, src


def due(spec: ProjectSpec, key: str) -> bool:
    _, depth = chain_position(spec, key)
    return depth > 0 and depth % CONTINUITY_EVERY == 0


def _gray(path: Path) -> list[int]:
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        raise RuntimeError("ffmpeg is not installed")
    out = subprocess.run([ffmpeg, "-v", "error", "-i", str(path), "-vf", f"scale={_W}:{_H}", "-f", "rawvideo",
                          "-pix_fmt", "gray", "-"], capture_output=True, check=True).stdout
    if len(out) != _W * _H:
        raise RuntimeError(f"unexpected frame size from {path}")
    return list(out)


def _mse(a: list[int], b: list[int], dx: int, dy: int, rows: int) -> float:
    total, n = 0, 0
    for y in range(_MAX_SHIFT, rows - _MAX_SHIFT):
        ra, rb = y * _W, (y + dy) * _W
        for x in range(_MAX_SHIFT, _W - _MAX_SHIFT):
            d = a[ra + x] - b[rb + x + dx]
            total += d * d
            n += 1
    return total / n


def _psnr(mse: float) -> float:
    import math
    return 99.0 if mse == 0 else round(10 * math.log10(255 * 255 / mse), 2)


def measure(anchor_path: Path, still_path: Path) -> dict:
    """Drift numbers between the anchor and a later still (local, cached by file hashes)."""
    key = (stills.file_sha256(anchor_path), stills.file_sha256(still_path))
    if key not in _CACHE:
        a, b = _gray(anchor_path), _gray(still_path)
        rows = int(_H * _BAND)
        shifts = {(dx, dy): _mse(a, b, dx, dy, rows)
                  for dx in range(-_MAX_SHIFT, _MAX_SHIFT + 1) for dy in range(-_MAX_SHIFT, _MAX_SHIFT + 1)}
        (dx, dy), best = min(shifts.items(), key=lambda kv: kv[1])
        scale = 768 / _W
        offset_pct = round(100 * max(abs(dx) / _W, abs(dy) / _H), 2)
        m = {"offset_px": [round(dx * scale), round(dy * scale)], "offset_pct": offset_pct,
             "band_psnr_db": _psnr(shifts[(0, 0)]), "band_psnr_aligned_db": _psnr(best),
             "frame_psnr_db": _psnr(_mse(a, b, 0, 0, _H))}
        flags = []
        if offset_pct >= FLAG_SHIFT_PCT:
            flags.append(f"camera: the frame has moved {m['offset_px']} px ({offset_pct}%) against the anchor")
        if m["band_psnr_aligned_db"] < FLAG_BAND_PSNR:
            flags.append(f"environment: the background band differs from the anchor ({m['band_psnr_aligned_db']} dB "
                         f"after alignment, flag below {FLAG_BAND_PSNR} dB)")
        m["flags"] = flags
        _CACHE[key] = m
    return _CACHE[key]


def info(spec: ProjectSpec, manifest_path: Path, key: str, manifest: dict, media_url=None) -> dict:
    """What the studio shows about this still's place in the chain and its continuity check."""
    anchor, depth = chain_position(spec, key)
    out = {"anchor": anchor, "depth": depth, "every": CONTINUITY_EVERY, "due": due(spec, key),
           "check": (manifest.get("continuity_checks") or {}).get(key), "metrics": None, "anchor_url": None,
           "error": None}
    if not out["due"]:
        return out
    a, s = stills.state(manifest_path, anchor, manifest), stills.state(manifest_path, key, manifest)
    if a.get("path") and media_url:
        out["anchor_url"] = media_url(a["path"])
    if a.get("path") and s.get("path"):
        try:
            out["metrics"] = measure(Path(a["path"]), Path(s["path"]))
        except (RuntimeError, OSError, subprocess.CalledProcessError) as e:
            out["error"] = str(e)
    return out


def passed(manifest_path: Path, key: str, manifest: dict) -> bool:
    rec = (manifest.get("continuity_checks") or {}).get(key)
    cur = stills.state(manifest_path, key, manifest)
    return bool(rec and rec.get("verdict") == "pass" and rec.get("still_sha256") == cur.get("sha256")
                and cur["state"] == "approved")


def required_problem(spec: ProjectSpec, manifest_path: Path, source_key: str, manifest: dict) -> str | None:
    """The source of the next edit is due a continuity check that has not passed yet."""
    if not due(spec, source_key) or passed(manifest_path, source_key, manifest):
        return None
    anchor, depth = chain_position(spec, source_key)
    rec = (manifest.get("continuity_checks") or {}).get(source_key)
    if rec and rec.get("verdict") == "fail":
        return (f"Continuity check FAILED on {source_key} against {anchor}: regenerate {source_key} or move to the next "
                "image tier before continuing.")
    return (f"Continuity checkpoint: {source_key} is chained edit {depth} since the anchor {anchor} - compare it "
            "against the anchor (geometry, camera, builder, environment) and record the result before continuing.")


class ContinuityError(Exception):
    def __init__(self, message: str, status: int = 400):
        super().__init__(message)
        self.status = status


def record(spec: ProjectSpec, manifest_path: Path, key: str, verdict: str, note: str, dims: dict[str, bool]) -> dict:
    """A person's continuity verdict for a still that is due a check (local, free)."""
    if not due(spec, key):
        raise ContinuityError(f"{key} is not due a continuity check.", 409)
    if verdict not in ("pass", "fail"):
        raise ContinuityError("verdict must be 'pass' or 'fail'")
    if not note.strip():
        raise ContinuityError("Say what you compared (a short note).")
    if verdict == "pass" and not all(dims.get(d) for d in DIMENSIONS):
        raise ContinuityError(f"A pass needs all of {', '.join(DIMENSIONS)} confirmed as holding.")
    manifest = json.loads(Path(manifest_path).read_text())
    st = stills.state(manifest_path, key, manifest)
    if st["state"] != "approved":
        raise ContinuityError(f"{key} is {st['state']} - approve the still before its continuity check.", 409)
    anchor, depth = chain_position(spec, key)
    a = stills.state(manifest_path, anchor, manifest)
    metrics = None
    if a.get("path"):
        try:
            metrics = measure(Path(a["path"]), Path(st["path"]))
        except (RuntimeError, OSError, subprocess.CalledProcessError):
            pass
    rec = {"anchor": anchor, "depth": depth, "anchor_sha256": a.get("sha256"), "still_sha256": st["sha256"],
           "verdict": verdict, "dimensions": {d: bool(dims.get(d)) for d in DIMENSIONS}, "note": note.strip(),
           "metrics": metrics, "at": datetime.now(timezone.utc).isoformat()}
    manifest.setdefault("continuity_checks", {})[key] = rec
    tmp = Path(manifest_path).with_suffix(".json.tmp")
    tmp.write_text(json.dumps(manifest, indent=2))
    os.replace(tmp, manifest_path)
    return rec
