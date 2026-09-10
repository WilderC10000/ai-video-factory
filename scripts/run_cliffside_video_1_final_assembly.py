#!/usr/bin/env python3
"""CLIFFSIDE VIDEO #1 - FINAL ASSEMBLY (all 7 real clips -> one ~30-32s cut).

Pure local FFmpeg. NO API calls, NO FAL_API_KEY needed, NO spend of any
kind.

Combines every real clip in story order - Segment 1A, 1B, 2, the
Construction Frontier decking clip, Framing, Glass, and the Reveal - into
one finished cut. The two jump-cut EDIT images (decking_complete_edit.jpg,
framing_complete_edit.jpg, exterior_complete_edit.jpg) are NOT separate
visible shots in this timeline: they only ever served as Wan's starting-
image conditioning for the clip that follows them. The "jump cut" the
viewer sees is simply the trimmed+accelerated transition from one real
clip straight into the next.

Each clip gets its own TRIM (in/out seconds - keep only the convincing
part; "do not preserve footage just because it was paid for") and its own
ACCELERATION FACTOR (pacing builds through construction, then eases for
the Reveal). Both are plain constants below - free, local, and
instantly re-editable without touching any paid stage. Trim happens
BEFORE acceleration (trim in raw time, then speed up what's left).

Default trims keep each clip's full raw duration (start=0, end=None) and
factors match the story's intended pacing curve - edit TRIM_SPECS/
ACCEL_FACTORS after watching the real raw clips and re-run; this script
never touches the source files.

Usage (from the repo root - no FAL_API_KEY needed, all seven real clips
must already exist from prior real runs of their own scripts):
    python -m scripts.run_cliffside_video_1_final_assembly
"""
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

from app.services.video_assembly import VideoAssemblyError, accelerate_video, concatenate_videos, trim_video
from scripts.run_cliffside_video_1_part2_framing import FRAMING_RAW_PATH
from scripts.run_cliffside_video_1_part2_glass import GLASS_RAW_PATH
from scripts.run_cliffside_video_1_part2_reveal import REVEAL_RAW_PATH
from scripts.run_cliffside_video_1_rough_assembly import (
    DECKING_RAW_PATH,
    MANIFEST_PATH,
    OUTPUT_DIR,
    SEGMENT_1A_PATH,
    SEGMENT_1B_PATH,
    SEGMENT_2_PATH,
)

FINAL_DIR = OUTPUT_DIR / "final"
FINAL_VISUAL_MASTER_PATH = OUTPUT_DIR / "cliffside_video_1_final_visual.mp4"

# name -> (source_path, trim_start_s, trim_end_s_or_None, accel_factor)
# Order = final story/timeline order. Trim is applied first (in raw-clip
# seconds), then acceleration. Tune these after watching the real clips.
CLIP_SPECS: list[tuple[str, Path, float, float | None, float]] = [
    ("01_segment_1a", SEGMENT_1A_PATH, 0.0, None, 1.5),
    ("02_segment_1b", SEGMENT_1B_PATH, 0.0, None, 2.0),
    ("03_segment_2", SEGMENT_2_PATH, 0.0, None, 2.2),
    ("04_decking", DECKING_RAW_PATH, 0.0, None, 2.5),
    ("05_framing", FRAMING_RAW_PATH, 0.0, None, 1.8),
    ("06_glass", GLASS_RAW_PATH, 0.0, None, 1.6),
    ("07_reveal", REVEAL_RAW_PATH, 0.0, None, 1.1),
]

TARGET_MIN_SECONDS = 30.0
TARGET_MAX_SECONDS = 32.0


def fail(message: str) -> None:
    print(f"\nSTOPPED: {message}")
    sys.exit(1)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def load_manifest() -> dict:
    if MANIFEST_PATH.exists():
        return json.loads(MANIFEST_PATH.read_text())
    return {"experiment": "cliffside_video_1", "created_at": _now()}


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


def main() -> None:
    missing = [(name, p) for name, p, *_ in CLIP_SPECS if not p.exists()]
    if missing:
        fail(
            "Not all seven real clips exist yet:\n"
            + "\n".join(f"  - {name}: {p}" for name, p in missing)
            + "\nRun each stage's own script (approved individually) before this step."
        )

    print("=" * 70)
    print("CLIFFSIDE VIDEO #1 - FINAL ASSEMBLY - NO API CALLS, NO SPEND")
    print("=" * 70)

    accelerated_paths: list[Path] = []
    per_clip_report = []
    for i, (name, source, trim_start, trim_end, factor) in enumerate(CLIP_SPECS, 1):
        print(f"\n[{i}/{len(CLIP_SPECS)}] {name}: trim [{trim_start}, {trim_end or 'end'}], accelerate {factor:g}x")
        trimmed_path = FINAL_DIR / f"{name}_trimmed.mp4"
        accel_path = FINAL_DIR / f"{name}_final.mp4"

        working_source = source
        if trim_start > 0.0 or trim_end is not None:
            try:
                trim_video(source, trimmed_path, start=trim_start, end=trim_end)
            except VideoAssemblyError as e:
                fail(f"{name}: trim failed: {e}")
            working_source = trimmed_path
            print(f"      trimmed -> {trimmed_path}")

        try:
            accelerate_video(working_source, accel_path, factor=factor)
        except VideoAssemblyError as e:
            fail(f"{name}: acceleration failed: {e}")
        print(f"      accelerated -> {accel_path}")

        finished_duration = _ffprobe_duration(accel_path)
        per_clip_report.append({"name": name, "source": str(source), "trim_start": trim_start,
                                 "trim_end": trim_end, "accel_factor": factor,
                                 "finished_seconds": round(finished_duration, 2)})
        accelerated_paths.append(accel_path)

    print(f"\n[{len(CLIP_SPECS) + 1}/{len(CLIP_SPECS) + 1}] Concatenating all {len(accelerated_paths)} clips into the final visual master...")
    try:
        concatenate_videos(accelerated_paths, FINAL_VISUAL_MASTER_PATH)
    except VideoAssemblyError as e:
        fail(f"Final concatenation failed: {e}")

    total_duration = _ffprobe_duration(FINAL_VISUAL_MASTER_PATH)

    manifest = load_manifest()
    manifest["final_assembly"] = {
        "clips": per_clip_report,
        "final_visual_master_path": str(FINAL_VISUAL_MASTER_PATH),
        "final_duration_seconds": round(total_duration, 2),
        "target_range_seconds": [TARGET_MIN_SECONDS, TARGET_MAX_SECONDS],
        "completed_at": _now(),
    }
    save_manifest(manifest)

    print("\n" + "=" * 70)
    print("FINAL ASSEMBLY DONE - no API calls were made.")
    print("=" * 70)
    print(f"Final visual master: {FINAL_VISUAL_MASTER_PATH}")
    print(f"Final duration:      {total_duration:.2f}s  (target {TARGET_MIN_SECONDS:.0f}-{TARGET_MAX_SECONDS:.0f}s)")
    print(f"Manifest:            {MANIFEST_PATH}")

    if not (TARGET_MIN_SECONDS <= total_duration <= TARGET_MAX_SECONDS):
        print(
            f"\nNOTE: {total_duration:.2f}s is outside the {TARGET_MIN_SECONDS:.0f}-{TARGET_MAX_SECONDS:.0f}s "
            "target. Adjust TRIM_SPECS/accel factors in CLIP_SPECS above and re-run - free, local, instant."
        )

    print("\nPer-clip breakdown:")
    for c in per_clip_report:
        print(f"  {c['name']}: {c['finished_seconds']}s (trim [{c['trim_start']}, {c['trim_end'] or 'end'}], {c['accel_factor']:g}x)")

    print("\nReview cliffside_video_1_final_visual.mp4 against:")
    print("  - pacing builds through construction, eases slightly for the Reveal")
    print("  - each cut reads as time passing / work continuing, not a different structure")
    print("  - coastal scenery stays visually important throughout")
    print("  - no dead motion left in - if a clip still drags, tighten its trim/factor and re-run")


if __name__ == "__main__":
    main()
