#!/usr/bin/env python3
"""COMPOUND EDIT VALIDATION TEST: PHASE COMPLETION + CAMERA NUDGE.

Tests the mechanism FORMA's redesigned jump-cut architecture depends on:
can a single NANO_BANANA_PRO_EDIT call both (1) advance an already-visible
construction phase to its logical completion and (2) make a modest camera
nudge (~15-20 degrees), while preserving the underlying structure,
environment, builder identity, lighting, and proportions? This is a
bigger, compound ask than the camera-transition rule already validated
(scripts/run_camera_transition_edit_test.py), which only proved a
conservative angle change on an otherwise-UNCHANGED structure - it never
asked the edit to also complete construction. Nothing in FORMA's
architecture should rely on this compound behavior until it's tested.

Source image is the REAL, literal last frame of the cliff-cabin
Checkpoint Chain Test's own raw output
(data/fal_checkpoint_chain_test/clip_b_raw.mp4) - chosen deliberately
because it shows a partially-decked, exposed-joist floor (the real
right-to-left decking operation validated across Construction Frontier
Test + Checkpoint Chain Test), a clean, already-existing example of "a
partially completed but clearly recognizable construction phase" that
does not depend on any unfinished Waterfall Cave footage. Extracted
locally via the existing extract_last_frame() - pure ffmpeg, free, no API
call. clip_b_raw.mp4 is only ever READ, never modified.

Makes exactly ONE Nano Banana Pro EDIT call ($0.15). No video call of any
kind - this test is purely about whether the compound edit behavior holds
up, before any video generation is built around it. No retries. Does not
touch any cliff-cabin segment, Validation Test #1/#2/#3, the checkpoint
chain test's own output, or any FORMA Video #1 file - clip_b_raw.mp4 is
only read.

Safety, same pattern as every other real-call script in this repo:
  - Exactly 1 image-edit call. No retry, no video call, no other file.
  - Hard cap set exactly equal to the flat edit price ($0.15) - zero
    margin, since Nano Banana Pro Edit bills a flat rate regardless of
    input/output size.

Usage (from the repo root, with FAL_API_KEY set in your .env, ffmpeg on
PATH, and data/fal_checkpoint_chain_test/clip_b_raw.mp4 present):
    python -m scripts.run_edit_advance_completion_test
    python -m scripts.run_edit_advance_completion_test --yes
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
# READ ONLY - never modified. The real last frame of the cliff-cabin
# Checkpoint Chain Test's own raw output, chosen for its partially-decked,
# exposed-joist floor.
SOURCE_VIDEO_PATH = REPO_ROOT / "data" / "fal_checkpoint_chain_test" / "clip_b_raw.mp4"

OUTPUT_DIR = REPO_ROOT / "data" / "fal_edit_advance_completion_test"
SOURCE_FRAME_PATH = OUTPUT_DIR / "checkpoint_chain_real_last_frame.jpg"
OUTPUT_IMAGE_PATH = OUTPUT_DIR / "advanced_completion_edit.jpg"
MANIFEST_PATH = OUTPUT_DIR / "manifest.json"

EDIT_PROMPT = (
    "This is an intentional editorial jump cut - the same construction project, filmed again "
    "some time later, with the same decking phase now further along - not a different or "
    "redesigned version of the build. Keep the underlying structure exactly as it is: the same "
    "platform proportions, the same foundation posts and perimeter beams in the same positions, "
    "the same joist spacing and layout, the same builder (same identity, clothing, and pose "
    "intent), the same site, cliff, boulder, and coastline geometry, and the same lighting "
    "direction. Shift the camera only slightly - approximately 15 to 20 degrees around the site - "
    "to a nearby, modestly different viewpoint, as if a second camera had been placed a short "
    "distance away. Advance ONLY the decking: complete the remaining exposed joists with the same "
    "style and spacing of deck boards already visible, so the section of floor that was still "
    "exposed joists in the starting image now reads as fully decked, matching and continuing the "
    "boards already installed. Do not change the platform's size or shape, do not move or add any "
    "posts or beams, do not alter the site or landscape, and do not begin or imply any next "
    "construction phase - no walls, no roof, no glass, no framing beyond the existing joists. "
    "This is purely completing the current decking phase and a small camera nudge, not inventing "
    "new construction."
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

    if not SOURCE_VIDEO_PATH.exists():
        fail(
            f"Checkpoint Chain Test's raw clip not found at {SOURCE_VIDEO_PATH} - nothing to "
            "extract from. This file only exists after running scripts/run_checkpoint_chain_test.py "
            "for real; it is never created or modified by this script."
        )

    print(f"\n[1/2] Extracting the real last frame of {SOURCE_VIDEO_PATH.name} locally (no API call)...")
    try:
        extract_last_frame(SOURCE_VIDEO_PATH, SOURCE_FRAME_PATH)
    except FrameExtractionError as e:
        fail(f"Frame extraction failed: {e}")
    print(f"      Done -> {SOURCE_FRAME_PATH} ({SOURCE_VIDEO_PATH.name} was only read, never modified)")

    image_provider = FalImageProvider(NANO_BANANA_PRO_EDIT)
    edit_request = ImageEditRequest(prompt=EDIT_PROMPT, reference_image_paths=[str(SOURCE_FRAME_PATH)])
    cost = image_provider.estimate_edit_cost()

    print("=" * 70)
    print("COMPOUND EDIT VALIDATION TEST - THIS WILL SPEND REAL MONEY")
    print("=" * 70)
    print(f"Model: {NANO_BANANA_PRO_EDIT.model_id}  (image edit, real Checkpoint Chain Test pixels as input)")
    print(f"Source image: {SOURCE_FRAME_PATH}")
    print(f"\nEdit prompt:\n  {EDIT_PROMPT}")
    print(f"\nEstimated cost: ${cost:.4f}")
    print(f"Hard cap:       ${MAX_SPEND_USD:.2f}")
    print("Rules: exactly 1 image-edit call, no video call, no retries, no other file touched.")
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
        "experiment": "edit_advance_completion_test",
        "source_video": str(SOURCE_VIDEO_PATH),
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

    print(f"\n[2/2] Requesting compound (completion + camera nudge) edit -> {OUTPUT_IMAGE_PATH.name} ...")
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
    print("The Checkpoint Chain Test's own output was not touched (only read).")
    print("=" * 70)
    print(f"Source frame (real Checkpoint Chain Test pixels): {SOURCE_FRAME_PATH}")
    print(f"Compound edit result:                             {OUTPUT_IMAGE_PATH}")
    print(f"Actual cost: ${result.cost_usd:.4f}")
    print(f"Manifest: {MANIFEST_PATH}")
    print("\nSTOP HERE. Compare the edit against the source frame for:")
    print("  1. Same physical structure clearly preserved")
    print("  2. Only the intended construction phase (decking) advances")
    print("  3. Completion is spatially/logically consistent with the source")
    print("  4. Camera change remains modest (~15-20 degrees) and believable")
    print("  5. Major geometry/landmarks (platform, posts, boulder, coastline) remain consistent")
    print("  6. No next-phase elements appear (no walls, roof, glass, or new framing)")
    print("  7. The before/after pair would work as a natural jump cut in a fast timelapse")
    print("     (\"same project, some time later, same phase now completed\" - not a different build)")
    print("\nThis is a pure mechanism test - it does not commit FORMA Video #1's jump-cut")
    print("architecture either way until you've reviewed the result.")


if __name__ == "__main__":
    main()
