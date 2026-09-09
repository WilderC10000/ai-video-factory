#!/usr/bin/env python3
"""CAMERA-TRANSITION EDIT VALIDATION TEST.

Tests the single mechanism the revised FORMA Video #1 camera-transition
plan depends on: can NANO_BANANA_PRO_EDIT perform a CONSERVATIVE camera
nudge (~20-30 degrees) on a real generated frame, while preserving the
existing structure - rather than the large-swing rotations attempted
earlier in this project (via fresh text-to-image generation, which failed
at Segment 3) or the kind of "change as little else as possible" local-
only edits this same endpoint has reliably done before (V2A, the
mechanical start/end frame tests). A conservative camera change is a
middle ground this project has never actually tested.

Source image is the REAL, literal last frame of the approved cliff-cabin
Segment 2 video (data/fal_full_video_segment_2/segment_2.mp4), extracted
locally via the existing extract_last_frame() - pure ffmpeg, free, no API
call. Segment 2's video file is only ever READ, never modified. This
frame was deliberately chosen (by the user) because it already contains
real structural complexity (an expanded floor platform, joists, posts)
that makes this a meaningful test of whether the edit endpoint preserves
geometry, not just a trivial case.

Makes exactly ONE Nano Banana Pro EDIT call ($0.15). No video call of any
kind - this test is purely about whether the still-image transition holds
up, before any video generation is attempted from it. No retries. Does
not touch or modify Segments 1A, 1B, 2, or 3, or any Validation Test #1/
#2/#3 output - segment_2.mp4 is only read. Does not touch FORMA Video #1
in any way - this is a pure mechanism test using existing, already-paid-
for cliff-cabin footage.

Safety, same pattern as every other real-call script in this repo:
  - Exactly 1 image-edit call. No retry, no video call, no other segment.
  - Hard cap set exactly equal to the flat edit price ($0.15) - zero
    margin, since Nano Banana Pro Edit bills a flat rate regardless of
    input/output size.

Usage (from the repo root, with FAL_API_KEY set in your .env, ffmpeg on
PATH, and data/fal_full_video_segment_2/segment_2.mp4 present):
    python -m scripts.run_camera_transition_edit_test
    python -m scripts.run_camera_transition_edit_test --yes
"""
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

from app.config import settings
from app.providers.base import ImageEditRequest, ImageProviderError
from app.providers.image.fal import NANO_BANANA_PRO_EDIT, FalImageProvider
from app.services.frame_extraction import FrameExtractionError, extract_last_frame

MAX_SPEND_USD = 0.15  # flat rate, zero margin

REPO_ROOT = Path(__file__).resolve().parent.parent
SEGMENT_2_VIDEO_PATH = REPO_ROOT / "data" / "fal_full_video_segment_2" / "segment_2.mp4"  # READ ONLY - never modified

OUTPUT_DIR = REPO_ROOT / "data" / "fal_camera_transition_edit_test"
SOURCE_FRAME_PATH = OUTPUT_DIR / "segment_2_real_last_frame.jpg"
OUTPUT_IMAGE_PATH = OUTPUT_DIR / "camera_transition_edit.jpg"
MANIFEST_PATH = OUTPUT_DIR / "manifest.json"

EDIT_PROMPT = (
    "Shift the camera position moderately - approximately 20 to 30 degrees around the site - to "
    "a nearby three-quarter viewpoint, as if a second camera had been placed a short distance "
    "away rather than in the exact same spot. Keep every element of the scene exactly as it "
    "currently appears: the same timber platform with the same proportions, the same joist "
    "spacing and layout, the same foundation posts in the same positions, the same builder (same "
    "identity, clothing, and pose intent), the same large flat grey boulder, the same cliff and "
    "coastline geometry, and the same golden-hour lighting direction. Do not add any new "
    "construction - no walls, no roof, no additional joists or boards beyond what is already "
    "present. Do not remove or alter anything already visible. This is purely a camera position "
    "change, not a redesign or rebuild of the scene."
)


def fail(message: str) -> None:
    print(f"\nSTOPPED: {message}")
    print("No retry, no further generation - the script is exiting now.")
    sys.exit(1)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def save_manifest(manifest: dict) -> None:
    MANIFEST_PATH.parent.mkdir(parents=True, exist_ok=True)
    MANIFEST_PATH.write_text(json.dumps(manifest, indent=2))


def main() -> None:
    skip_confirm = "--yes" in sys.argv[1:]

    key_preview = f"{settings.fal_api_key[:6]}..." if settings.fal_api_key else None
    print(f"FAL_API_KEY loaded from .env: {'yes (' + key_preview + ')' if key_preview else 'NO'}")
    if not settings.fal_api_key:
        fail("FAL_API_KEY is not set. Add FAL_API_KEY=your_key_here to your .env file and try again.")

    if not SEGMENT_2_VIDEO_PATH.exists():
        fail(
            f"Approved Segment 2 video not found at {SEGMENT_2_VIDEO_PATH} - nothing to extract from. "
            "This file only exists after running scripts/run_full_video_segment_2_resume_video_test.py "
            "for real; it is never created or modified by this script."
        )

    print(f"\n[1/2] Extracting the real last frame of {SEGMENT_2_VIDEO_PATH.name} locally (no API call)...")
    try:
        extract_last_frame(SEGMENT_2_VIDEO_PATH, SOURCE_FRAME_PATH)
    except FrameExtractionError as e:
        fail(f"Frame extraction failed: {e}")
    print(f"      Done -> {SOURCE_FRAME_PATH} (Segment 2's own video file was only read, never modified)")

    image_provider = FalImageProvider(NANO_BANANA_PRO_EDIT)
    edit_request = ImageEditRequest(prompt=EDIT_PROMPT, reference_image_paths=[str(SOURCE_FRAME_PATH)])
    cost = image_provider.estimate_edit_cost()

    print("=" * 70)
    print("CAMERA-TRANSITION EDIT TEST - THIS WILL SPEND REAL MONEY")
    print("=" * 70)
    print(f"Model: {NANO_BANANA_PRO_EDIT.model_id}  (image edit, real Segment 2 pixels as input)")
    print(f"Source image: {SOURCE_FRAME_PATH}")
    print(f"\nEdit prompt:\n  {EDIT_PROMPT}")
    print(f"\nEstimated cost: ${cost:.4f}")
    print(f"Hard cap:       ${MAX_SPEND_USD:.2f}")
    print("Rules: exactly 1 image-edit call, no video call, no retries, no other segment.")
    print("=" * 70)

    if cost > MAX_SPEND_USD:
        fail(f"Estimated cost ${cost:.4f} exceeds the ${MAX_SPEND_USD:.2f} cap. Nothing was generated.")

    if not skip_confirm:
        answer = input(f"\nType 'yes' to spend up to ${cost:.4f} and proceed: ").strip().lower()
        if answer != "yes":
            print("Cancelled. Nothing was generated.")
            sys.exit(0)

    manifest = {
        "created_at": _now(),
        "experiment": "camera_transition_edit_test",
        "source_segment2_video": str(SEGMENT_2_VIDEO_PATH),
        "source_frame_path": str(SOURCE_FRAME_PATH),
        "image_model": NANO_BANANA_PRO_EDIT.model_id,
        "edit_prompt": EDIT_PROMPT,
        "max_spend_usd": MAX_SPEND_USD,
        "estimated_cost_usd": cost,
        "output_path": None,
        "actual_cost_usd": None,
        "completed_at": None,
    }
    save_manifest(manifest)

    print(f"\n[2/2] Requesting camera-transition edit -> {OUTPUT_IMAGE_PATH.name} ...")
    try:
        result = image_provider.edit_image(edit_request, str(OUTPUT_IMAGE_PATH))
    except ImageProviderError as e:
        fail(f"Edit failed: {e}")
    print(f"      Done -> {OUTPUT_IMAGE_PATH} (${result.cost_usd:.4f})")

    manifest["output_path"] = str(OUTPUT_IMAGE_PATH)
    manifest["actual_cost_usd"] = result.cost_usd
    manifest["completed_at"] = _now()
    save_manifest(manifest)

    print("\n" + "=" * 70)
    print("DONE - 1 edit generated. No video call was made.")
    print("Segments 1A, 1B, 2, and 3, and Validation Tests #1-3, were not touched (all only read).")
    print("=" * 70)
    print(f"Source frame (real Segment 2 pixels): {SOURCE_FRAME_PATH}")
    print(f"Camera-transition edit:               {OUTPUT_IMAGE_PATH}")
    print(f"Actual cost: ${result.cost_usd:.4f}")
    print(f"Manifest: {MANIFEST_PATH}")
    print("\nSTOP HERE. Compare the edit against the source frame for:")
    print("  1. Clearly reads as the same physical structure from a slightly different angle")
    print("  2. Platform proportions remain consistent")
    print("  3. Joist layout and corner/post positions remain believable and materially consistent")
    print("  4. Major environmental landmarks (boulder, coastline, cliff) stay in correct relative positions")
    print("  5. Builder identity remains consistent")
    print("  6. No new structural elements appear")
    print("  7. No obvious AI reconstruction that would break continuity in a timelapse")
    print("\nThis is a pure mechanism test - it does not affect FORMA Video #1 planning either way")
    print("until you've reviewed the result.")


if __name__ == "__main__":
    main()
