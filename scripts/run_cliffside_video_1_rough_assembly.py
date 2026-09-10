#!/usr/bin/env python3
"""CLIFFSIDE FORMA VIDEO #1 - ROUGH ASSEMBLY OF ALREADY-APPROVED FOOTAGE.

Pure local FFmpeg. NO API calls, NO FAL_API_KEY needed, NO spend of any
kind. Safe to run first, before any new paid generation.

Following the pivot to make the cliffside cabin build FORMA's first real
posted video (the waterfall cave concept is now a later project), this
script answers a simple question for free: how much of the 30-32s Phase 1
target is already covered by footage that is APPROVED, LOCKED, and
already paid for?

Accelerates each of the four existing real clips individually, then
concatenates them in story order into one rough preview - the "existing
material" portion of the final video, before any new Framing/Finishing/
Reveal generation is added on top:

  1. Segment 1A   (segment_1a.mp4,               6s raw / 1.5x -> 4.0s)
     - starter platform being built, coastal establishing shot
  2. Segment 1B   (segment_1b.mp4,                8s raw / 2.0x -> 4.0s)
     - foundation piers, staged materials, floor joists installed
  3. Segment 2    (segment_2.mp4,                12s raw / 2.2x -> 5.5s)
     - platform expands ~4x to full scale, new elevated camera angle
  4. Construction Frontier Test (construction_frontier_raw.mp4,
                                  10s raw / 2.5x -> 4.0s)
     - decking operation begins, right-to-left, same camera as Segment 2

None of these four source files are ever modified - accelerate_video()
refuses to write to its own input path, and each accelerated file gets
its own distinct filename under this script's own output directory.

Factors are easily adjustable by editing the *_FACTOR constants below and
re-running - a free, local, instantly-repeatable step. Total ~17.5s from
existing material; the remaining ~13-14s (Framing, Finishing, Reveal) is
new generation not yet built.

Usage (from the repo root - no FAL_API_KEY needed, but the four source
files must already exist from prior real runs of their own scripts):
    python -m scripts.run_cliffside_video_1_rough_assembly
"""
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

from app.services.video_assembly import VideoAssemblyError, accelerate_video, concatenate_videos
from scripts.run_full_video_segment_1a_resume_video_test import VIDEO_PATH as SEGMENT_1A_PATH
from scripts.run_full_video_segment_1b_resume_video_test import VIDEO_PATH as SEGMENT_1B_PATH
from scripts.run_full_video_segment_2_resume_video_test import VIDEO_PATH as SEGMENT_2_PATH
from scripts.run_construction_frontier_test import RAW_VIDEO_PATH as DECKING_RAW_PATH

REPO_ROOT = Path(__file__).resolve().parent.parent
OUTPUT_DIR = REPO_ROOT / "data" / "cliffside_video_1"
MANIFEST_PATH = OUTPUT_DIR / "manifest.json"

SEGMENT_1A_FACTOR = 1.5
SEGMENT_1B_FACTOR = 2.0
SEGMENT_2_FACTOR = 2.2
DECKING_FACTOR = 2.5

SEGMENT_1A_ACCEL_PATH = OUTPUT_DIR / "01_segment_1a_accelerated.mp4"
SEGMENT_1B_ACCEL_PATH = OUTPUT_DIR / "02_segment_1b_accelerated.mp4"
SEGMENT_2_ACCEL_PATH = OUTPUT_DIR / "03_segment_2_accelerated.mp4"
DECKING_ACCEL_PATH = OUTPUT_DIR / "04_decking_accelerated.mp4"
ROUGH_ASSEMBLY_PATH = OUTPUT_DIR / "rough_assembly_preview.mp4"


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


def main() -> None:
    sources = [
        (SEGMENT_1A_PATH, "Segment 1A"),
        (SEGMENT_1B_PATH, "Segment 1B"),
        (SEGMENT_2_PATH, "Segment 2"),
        (DECKING_RAW_PATH, "Construction Frontier Test (decking)"),
    ]
    missing = [(p, label) for p, label in sources if not p.exists()]
    if missing:
        fail(
            "Not all four already-approved source clips exist yet:\n"
            + "\n".join(f"  - {label}: {p}" for p, label in missing)
            + "\nEach must already exist from a prior real run of its own script."
        )

    print("=" * 70)
    print("CLIFFSIDE FORMA VIDEO #1 - ROUGH ASSEMBLY - NO API CALLS, NO SPEND")
    print("=" * 70)

    print(f"\n[1/5] Accelerating Segment 1A ({SEGMENT_1A_FACTOR:g}x)...")
    try:
        accelerate_video(SEGMENT_1A_PATH, SEGMENT_1A_ACCEL_PATH, factor=SEGMENT_1A_FACTOR)
    except VideoAssemblyError as e:
        fail(f"Segment 1A acceleration failed: {e}")
    print(f"      -> {SEGMENT_1A_ACCEL_PATH}")

    print(f"\n[2/5] Accelerating Segment 1B ({SEGMENT_1B_FACTOR:g}x)...")
    try:
        accelerate_video(SEGMENT_1B_PATH, SEGMENT_1B_ACCEL_PATH, factor=SEGMENT_1B_FACTOR)
    except VideoAssemblyError as e:
        fail(f"Segment 1B acceleration failed: {e}")
    print(f"      -> {SEGMENT_1B_ACCEL_PATH}")

    print(f"\n[3/5] Accelerating Segment 2 ({SEGMENT_2_FACTOR:g}x)...")
    try:
        accelerate_video(SEGMENT_2_PATH, SEGMENT_2_ACCEL_PATH, factor=SEGMENT_2_FACTOR)
    except VideoAssemblyError as e:
        fail(f"Segment 2 acceleration failed: {e}")
    print(f"      -> {SEGMENT_2_ACCEL_PATH}")

    print(f"\n[4/5] Accelerating Construction Frontier Test decking clip ({DECKING_FACTOR:g}x)...")
    try:
        accelerate_video(DECKING_RAW_PATH, DECKING_ACCEL_PATH, factor=DECKING_FACTOR)
    except VideoAssemblyError as e:
        fail(f"Decking clip acceleration failed: {e}")
    print(f"      -> {DECKING_ACCEL_PATH}")

    print("\n[5/5] Concatenating Segment 1A + 1B + 2 + Decking (accelerated) into the rough preview...")
    try:
        concatenate_videos(
            [SEGMENT_1A_ACCEL_PATH, SEGMENT_1B_ACCEL_PATH, SEGMENT_2_ACCEL_PATH, DECKING_ACCEL_PATH],
            ROUGH_ASSEMBLY_PATH,
        )
    except VideoAssemblyError as e:
        fail(f"Concatenation failed: {e}")
    print(f"      -> {ROUGH_ASSEMBLY_PATH}")

    manifest = load_manifest()
    manifest["rough_assembly"] = {
        "segment_1a_factor": SEGMENT_1A_FACTOR,
        "segment_1b_factor": SEGMENT_1B_FACTOR,
        "segment_2_factor": SEGMENT_2_FACTOR,
        "decking_factor": DECKING_FACTOR,
        "rough_assembly_path": str(ROUGH_ASSEMBLY_PATH),
        "completed_at": _now(),
    }
    save_manifest(manifest)

    print("\n" + "=" * 70)
    print("ROUGH ASSEMBLY DONE - no API calls were made, nothing was spent.")
    print("=" * 70)
    print(f"Rough preview: {ROUGH_ASSEMBLY_PATH}")
    print(f"Manifest:      {MANIFEST_PATH}")
    print("\nThis covers only the EXISTING-material portion of the final ~30-32s video")
    print("(target ~17.5s here). Framing, Finishing, and the Reveal are new generation,")
    print("not included in this preview - review this first to confirm the pacing/feel")
    print("of the already-approved footage before spending anything new.")
    print("\nReview against:")
    print("  - reads as one continuous, accelerating transformation, not four separate clips")
    print("  - each cut feels like time passed and work continued, not a different structure")
    print("  - coastal scenery stays a major visual element throughout, not background")
    print("  - pacing builds - starts clear/legible, gets faster as decking begins")


if __name__ == "__main__":
    main()
