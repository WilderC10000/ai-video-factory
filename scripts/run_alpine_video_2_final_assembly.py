#!/usr/bin/env python3
"""FORMA VIDEO #2 - FINAL ASSEMBLY (all 8 real clips -> one ~30-31s cut).

Pure local FFmpeg. NO API calls, NO FAL_API_KEY needed, NO spend of any
kind.

Combines every real Wan clip in story order - Opening/Site Prep, Base/
Floor, Floorboards, A-Frame Ribs, Roof/Cladding, Glass Facade, Interior
Design, Final Reveal - into one finished cut. The site reference image
and all six Nano Banana Pro EDIT stills are NOT separate visible shots in
this timeline: they only ever served as the starting-image conditioning
for the clip that follows them. The "jump cut" the viewer sees is simply
the accelerated transition from one real clip straight into the next.

Each clip gets its own ACCELERATION FACTOR - a plain constant below, free
and instantly re-editable without touching any paid stage. No clip is
trimmed (each raw clip is used in full, start=0/end=None) because every
duration was already chosen upstream, per shot, to hit its FORMA 90%
Process Rule target; only the post-hoc acceleration is retuned here to
land the finished cut in the target window.

These factors were chosen to land at approximately the target duration
while respecting every protection from the final cost-efficiency pass:
the A-frame rib hero shot (Shot 4) and final reveal (Shot 8) are NOT
shortened below their approved finished-duration floors, and interior
(Shot 7) keeps enough finished time to show real furnishing progress.
Adjust ACCEL_FACTORS after watching the real raw clips and re-run - free,
local, instant.

Usage (from the repo root - no FAL_API_KEY needed, all eight real clips
must already exist from prior real runs of their own scripts):
    python -m scripts.run_alpine_video_2_final_assembly
"""
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

from app.services.video_assembly import VideoAssemblyError, accelerate_video, concatenate_videos, has_audio_stream
from scripts.run_alpine_video_2_common import MANIFEST_PATH, OUTPUT_DIR
from scripts.run_alpine_video_2_edit3_framing_complete import EDIT3_OUTPUT_PATH  # noqa: F401 (documents chain)
from scripts.run_alpine_video_2_shot1_opening_prep import SHOT1_RAW_PATH
from scripts.run_alpine_video_2_shot2_base_floor import SHOT2_RAW_PATH
from scripts.run_alpine_video_2_shot3_floorboards import SHOT3_RAW_PATH
from scripts.run_alpine_video_2_shot4_aframe_ribs import SHOT4_RAW_PATH
from scripts.run_alpine_video_2_shot5_roof_cladding import SHOT5_RAW_PATH
from scripts.run_alpine_video_2_shot6_glass import SHOT6_RAW_PATH
from scripts.run_alpine_video_2_shot7_interior import SHOT7_RAW_PATH
from scripts.run_alpine_video_2_shot8_reveal import SHOT8_RAW_PATH

# Source audio is now preserved (atempo-retimed with each clip). New output names,
# so the earlier silent master (alpine_video_2_final_visual.mp4) and its silent
# per-clip files in final/ are kept untouched rather than overwritten.
FINAL_DIR = OUTPUT_DIR / "final_with_audio"
FINAL_VISUAL_MASTER_PATH = OUTPUT_DIR / "alpine_video_2_final_with_source_audio.mp4"
SILENT_MASTER_PATH = OUTPUT_DIR / "alpine_video_2_final_visual.mp4"

# name -> (source_path, accel_factor). Order = final story/timeline order.
# Factor chosen so raw_seconds / factor ~= that shot's approved finished-
# duration target (see README "Running FORMA Video #2" for the full table).
CLIP_SPECS: list[tuple[str, Path, float]] = [
    ("01_shot1_opening_prep", SHOT1_RAW_PATH, 2.0),
    ("02_shot2_base_floor", SHOT2_RAW_PATH, 3.3),
    ("03_shot3_floorboards", SHOT3_RAW_PATH, 3.7),
    ("04_shot4_aframe_ribs", SHOT4_RAW_PATH, 3.33),
    ("05_shot5_roof_cladding", SHOT5_RAW_PATH, 3.3),
    ("06_shot6_glass", SHOT6_RAW_PATH, 2.9),
    ("07_shot7_interior", SHOT7_RAW_PATH, 2.5),
    ("08_shot8_reveal", SHOT8_RAW_PATH, 1.1),
]

TARGET_MIN_SECONDS = 30.5
TARGET_MAX_SECONDS = 31.5


def fail(message: str) -> None:
    print(f"\nSTOPPED: {message}")
    sys.exit(1)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def load_manifest() -> dict:
    if MANIFEST_PATH.exists():
        return json.loads(MANIFEST_PATH.read_text())
    return {"experiment": "alpine_video_2", "created_at": _now()}


def save_manifest(manifest: dict) -> None:
    MANIFEST_PATH.parent.mkdir(parents=True, exist_ok=True)
    MANIFEST_PATH.write_text(json.dumps(manifest, indent=2))


def _ffprobe_duration(path: Path) -> float:
    import subprocess

    result = subprocess.run(
        [
            "ffprobe", "-v", "error", "-show_entries", "format=duration",
            "-of", "default=noprint_wrappers=1:nokey=1", str(path),
        ],
        capture_output=True, text=True, check=True,
    )
    return float(result.stdout.strip())


class AssemblyError(Exception):
    """Final assembly could not run or failed; nothing was written to the manifest."""


def assemble_final(
    clip_specs: list[tuple[str, Path, float]] = CLIP_SPECS,
    final_dir: Path = FINAL_DIR,
    master_path: Path = FINAL_VISUAL_MASTER_PATH,
    manifest_path: Path = MANIFEST_PATH,
    log=print,
) -> dict:
    """Non-interactive service form of the final assembly (used by the FORMA
    Virtual Studio job runner). Local FFmpeg only - never any API call or spend.
    Raises AssemblyError instead of exiting."""
    missing = [(name, p) for name, p, _ in clip_specs if not p.exists()]
    if missing:
        raise AssemblyError(
            "Not all eight real clips exist yet:\n"
            + "\n".join(f"  - {name}: {p}" for name, p in missing)
            + "\nRun each stage's own script (approved individually) before this step."
        )

    log("=" * 70)
    log("FORMA VIDEO #2 - FINAL ASSEMBLY - NO API CALLS, NO SPEND")
    log("=" * 70)

    accelerated_paths: list[Path] = []
    per_clip_report = []
    for i, (name, source, factor) in enumerate(clip_specs, 1):
        log(f"\n[{i}/{len(clip_specs)}] {name}: accelerate {factor:g}x")
        accel_path = final_dir / f"{name}_final.mp4"

        try:
            accelerate_video(source, accel_path, factor=factor)
        except VideoAssemblyError as e:
            raise AssemblyError(f"{name}: acceleration failed: {e}") from e
        log(f"      accelerated -> {accel_path}")

        finished_duration = _ffprobe_duration(accel_path)
        per_clip_report.append({
            "name": name, "source": str(source), "accel_factor": factor,
            "source_has_audio": has_audio_stream(source),
            "finished_seconds": round(finished_duration, 2),
        })
        accelerated_paths.append(accel_path)

    log(f"\n[{len(clip_specs) + 1}/{len(clip_specs) + 1}] Concatenating all {len(accelerated_paths)} clips into the final visual master...")
    try:
        concatenate_videos(accelerated_paths, master_path)
    except VideoAssemblyError as e:
        raise AssemblyError(f"Final concatenation failed: {e}") from e

    total_duration = _ffprobe_duration(master_path)

    manifest = json.loads(manifest_path.read_text()) if manifest_path.exists() else {"experiment": "alpine_video_2", "created_at": _now()}
    previous = manifest.get("final_assembly")
    if isinstance(previous, dict):
        # Keep the earlier assembly's record instead of overwriting it; its files are untouched.
        n = 1
        while f"final_assembly__attempt{n}" in manifest:
            n += 1
        manifest[f"final_assembly__attempt{n}"] = {**previous, "archived_at": _now()}
    manifest["final_assembly"] = {
        "clips": per_clip_report,
        "audio": "source audio preserved: each clip's audio atempo-retimed by its accel factor "
                 "(silence where a clip has none), AAC 44.1 kHz stereo",
        "final_visual_master_path": str(master_path),
        "final_duration_seconds": round(total_duration, 2),
        "target_range_seconds": [TARGET_MIN_SECONDS, TARGET_MAX_SECONDS],
        "completed_at": _now(),
    }
    manifest_path.write_text(json.dumps(manifest, indent=2))
    return {"output_path": str(master_path), "final_duration_seconds": total_duration, "clips": per_clip_report}


def main() -> None:
    try:
        result = assemble_final()
    except AssemblyError as e:
        fail(str(e))
    total_duration = result["final_duration_seconds"]
    per_clip_report = result["clips"]

    print("\n" + "=" * 70)
    print("FINAL ASSEMBLY DONE - no API calls were made.")
    print("=" * 70)
    print(f"Final visual master: {FINAL_VISUAL_MASTER_PATH}")
    print(f"Final duration:      {total_duration:.2f}s  (target {TARGET_MIN_SECONDS:.1f}-{TARGET_MAX_SECONDS:.1f}s)")
    print(f"Manifest:            {MANIFEST_PATH}")

    if not (TARGET_MIN_SECONDS <= total_duration <= TARGET_MAX_SECONDS):
        print(
            f"\nNOTE: {total_duration:.2f}s is outside the {TARGET_MIN_SECONDS:.1f}-{TARGET_MAX_SECONDS:.1f}s "
            "target. Adjust ACCEL_FACTORS in CLIP_SPECS above and re-run - free, local, instant."
        )

    print("\nPer-clip breakdown:")
    for c in per_clip_report:
        print(f"  {c['name']}: {c['finished_seconds']}s ({c['accel_factor']:g}x)")

    print(f"\nReview {FINAL_VISUAL_MASTER_PATH.name} against:")
    print("  - each phase shows real, on-camera visible completion before its jump cut (70-90% rule)")
    print("  - pacing accelerates through construction, eases for interior and the reveal")
    print("  - the A-frame rib hero moment and final reveal both get real screen time")
    print("  - lake/mountains stay a major visual element throughout, never just background")
    print("  - no dead motion left in - if a clip still drags, tighten its factor and re-run")


if __name__ == "__main__":
    main()
