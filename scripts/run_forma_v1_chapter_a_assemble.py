#!/usr/bin/env python3
"""FORMA VIDEO #1 - CHAPTER A, STAGE A4: LOCAL ASSEMBLY.

Only runnable after all three of Chapter A's raw clips (Hook, Site Prep
Clip 1, Site Prep Clip 2) have been generated. Pure local ffmpeg tooling -
NO API calls, NO FAL_API_KEY needed, NO spend of any kind.

Accelerates each raw clip individually via the existing
app.services.video_assembly.accelerate_video(), then concatenates the
three accelerated clips into chapter_a_combined_preview.mp4 via the
existing concatenate_videos() - the same "accelerate each clip, then
concatenate the accelerated versions" order already validated in
Validation Test #3, not concatenate-then-accelerate.

RETUNED for the FORMA Phase 1 (audience-growth) ~31s cut of FORMA Video
#1: Chapter A's finished-seconds budget was deliberately shrunk from
~9.1s to ~5.0s so the freed screen time could go to Foundation and
Decking instead (the actual build stages) rather than the Hook/Prep
setup - "don't compromise on the timelapse" refers to keeping the build
chapters unhurried, which this frees room for:
  Hook:   4s raw / 4.0x -> 1.0s finished
  Prep 1: 7s raw / 3.5x -> 2.0s finished
  Prep 2: 8s raw / 4.0x -> 2.0s finished
  (sum: 5.0s finished - unchanged raw footage, unchanged cost, purely a
  free local re-tune of these factors)
These are easily adjustable by editing the *_FACTOR constants below and
re-running this script - it's a free, local, instantly-repeatable step,
so there's no need to get the factors exactly right on the first pass.

None of the raw clips are ever overwritten - accelerate_video() itself
refuses to write to its own input path, and each accelerated file gets
its own distinct filename.

Usage (from the repo root - no FAL_API_KEY needed):
    python -m scripts.run_forma_v1_chapter_a_assemble
"""
import json
import sys
from datetime import datetime, timezone

from app.services.video_assembly import VideoAssemblyError, accelerate_video, concatenate_videos
from scripts.run_forma_v1_chapter_a_hook import HOOK_RAW_PATH, MANIFEST_PATH, OUTPUT_DIR
from scripts.run_forma_v1_chapter_a_prep1 import PREP1_RAW_PATH
from scripts.run_forma_v1_chapter_a_prep2 import PREP2_RAW_PATH

HOOK_FACTOR = 4.0
PREP1_FACTOR = 3.5
PREP2_FACTOR = 4.0

HOOK_ACCEL_PATH = OUTPUT_DIR / "hook_accelerated.mp4"
PREP1_ACCEL_PATH = OUTPUT_DIR / "site_prep_clip1_accelerated.mp4"
PREP2_ACCEL_PATH = OUTPUT_DIR / "site_prep_clip2_accelerated.mp4"
COMBINED_PREVIEW_PATH = OUTPUT_DIR / "chapter_a_combined_preview.mp4"


def fail(message: str) -> None:
    print(f"\nSTOPPED: {message}")
    sys.exit(1)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def load_manifest() -> dict:
    if MANIFEST_PATH.exists():
        return json.loads(MANIFEST_PATH.read_text())
    return {"experiment": "forma_video_1_chapter_a", "created_at": _now()}


def save_manifest(manifest: dict) -> None:
    MANIFEST_PATH.parent.mkdir(parents=True, exist_ok=True)
    MANIFEST_PATH.write_text(json.dumps(manifest, indent=2))


def main() -> None:
    missing = [p for p in (HOOK_RAW_PATH, PREP1_RAW_PATH, PREP2_RAW_PATH) if not p.exists()]
    if missing:
        fail(
            "Not all three Chapter A raw clips exist yet:\n"
            + "\n".join(f"  - {p}" for p in missing)
            + "\nRun Stages A1, A2, and A3 (each approved individually) before this step."
        )

    print("=" * 70)
    print("FORMA VIDEO #1 - CHAPTER A - STAGE A4 (LOCAL ASSEMBLY) - NO API CALLS, NO SPEND")
    print("=" * 70)

    print(f"\n[1/4] Accelerating Hook ({HOOK_FACTOR:g}x)...")
    try:
        accelerate_video(HOOK_RAW_PATH, HOOK_ACCEL_PATH, factor=HOOK_FACTOR)
    except VideoAssemblyError as e:
        fail(f"Hook acceleration failed: {e}")
    print(f"      -> {HOOK_ACCEL_PATH}")

    print(f"\n[2/4] Accelerating Site Prep Clip 1 ({PREP1_FACTOR:.3f}x)...")
    try:
        accelerate_video(PREP1_RAW_PATH, PREP1_ACCEL_PATH, factor=PREP1_FACTOR)
    except VideoAssemblyError as e:
        fail(f"Site Prep Clip 1 acceleration failed: {e}")
    print(f"      -> {PREP1_ACCEL_PATH}")

    print(f"\n[3/4] Accelerating Site Prep Clip 2 ({PREP2_FACTOR:.3f}x)...")
    try:
        accelerate_video(PREP2_RAW_PATH, PREP2_ACCEL_PATH, factor=PREP2_FACTOR)
    except VideoAssemblyError as e:
        fail(f"Site Prep Clip 2 acceleration failed: {e}")
    print(f"      -> {PREP2_ACCEL_PATH}")

    print(f"\n[4/4] Concatenating Hook + Prep 1 + Prep 2 (accelerated) into the combined preview...")
    try:
        concatenate_videos([HOOK_ACCEL_PATH, PREP1_ACCEL_PATH, PREP2_ACCEL_PATH], COMBINED_PREVIEW_PATH)
    except VideoAssemblyError as e:
        fail(f"Concatenation failed: {e}")
    print(f"      -> {COMBINED_PREVIEW_PATH}")

    manifest = load_manifest()
    manifest["assembly"] = {
        "hook_factor": HOOK_FACTOR,
        "prep1_factor": PREP1_FACTOR,
        "prep2_factor": PREP2_FACTOR,
        "hook_accelerated_path": str(HOOK_ACCEL_PATH),
        "prep1_accelerated_path": str(PREP1_ACCEL_PATH),
        "prep2_accelerated_path": str(PREP2_ACCEL_PATH),
        "combined_preview_path": str(COMBINED_PREVIEW_PATH),
        "completed_at": _now(),
    }
    save_manifest(manifest)

    print("\n" + "=" * 70)
    print("STAGE A4 DONE - Chapter A locally assembled. No API calls were made.")
    print("=" * 70)
    print(f"Combined preview: {COMBINED_PREVIEW_PATH}")
    print(f"Manifest:         {MANIFEST_PATH}")
    print("\nReview chapter_a_combined_preview.mp4 as one continuous ~5s piece:")
    print("  - reads as one escalating chapter, not three disconnected clips")
    print("  - Hook's quick establishing beat, then Site Prep's accelerated progress")
    print("  - no visible seam/discontinuity between clips")
    print("  - intentionally tight: this budget was shrunk to give Foundation/Decking more room")


if __name__ == "__main__":
    main()
