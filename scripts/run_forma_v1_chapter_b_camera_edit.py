#!/usr/bin/env python3
"""FORMA VIDEO #1 - CHAPTER B, STAGE B0: CAMERA TRANSITION EDIT.

Only runnable after Chapter A's Site Prep Clip 2 has been generated AND
approved (Chapter A as a whole is already fully approved) - this script
requires site_prep_clip2_raw.mp4 to already exist, and additionally asks
you to explicitly confirm you've reviewed and approved it (a separate
confirmation from the cost confirmation below) before it spends anything.
Same double-gate pattern as every other real-call script in this repo.

Uses the now-locked camera-transition rule: a conservative (~20-30
degree) NANO_BANANA_PRO_EDIT nudge conditioned on the literal real last
frame of the previous chapter - never a fresh text-to-image re-anchor.
Source image is the REAL last frame of site_prep_clip2_raw.mp4, extracted
locally via extract_last_frame() - pure ffmpeg, free, no API call.
site_prep_clip2_raw.mp4 is only ever read, never modified.

Makes exactly ONE Nano Banana Pro EDIT call ($0.15 flat rate). No video
call of any kind. No retries. Does NOT chain to Stage B1 (Foundation) -
that is a separate script, run only after this stage's own output is
reviewed and approved. Per explicit instruction: only after this edit is
approved should the Foundation video become eligible to run.

Usage (from the repo root, with FAL_API_KEY set in your .env, and
site_prep_clip2_raw.mp4 already generated and reviewed):
    python -m scripts.run_forma_v1_chapter_b_camera_edit
    python -m scripts.run_forma_v1_chapter_b_camera_edit --yes   (skips only the cost confirmation - the upstream-approval confirmation always runs)
"""
import json
import sys
from datetime import datetime, timezone

from app.config import settings
from app.providers.base import ImageEditRequest, ImageProviderError
from app.providers.image.fal import NANO_BANANA_PRO_EDIT, FalImageProvider
from app.services.frame_extraction import FrameExtractionError, extract_last_frame
from scripts.run_forma_v1_chapter_a_hook import REPO_ROOT
from scripts.run_forma_v1_chapter_a_prep2 import PREP2_RAW_PATH

MAX_SPEND_USD = 0.15  # flat rate, zero margin

OUTPUT_DIR = REPO_ROOT / "data" / "forma_video_1_chapter_b"
SOURCE_FRAME_PATH = OUTPUT_DIR / "prep2_real_last_frame.jpg"
CAMERA_B_EDIT_PATH = OUTPUT_DIR / "camera_b_edit.jpg"
MANIFEST_PATH = OUTPUT_DIR / "manifest.json"

EDIT_PROMPT = (
    "Shift the camera position moderately - approximately 20 to 30 degrees around the site - to "
    "a nearby three-quarter viewpoint, as if a second camera had been placed a short distance "
    "away rather than in the exact same spot. Keep every element of the scene exactly as it "
    "currently appears: the same fully cleared and leveled construction pad, the same single "
    "debris ridge in the same position, the same compact tracked skid-steer machine in the same "
    "position at the edge of the finished pad, the same cave overhang, waterfall, rocks, and "
    "vegetation, and the same ambient lighting direction. Do not add any construction of any "
    "kind - no foundation, no walls, no framing, no glass. Do not remove or alter anything "
    "already visible. This is purely a camera position change, not a redesign or rebuild of the "
    "scene."
)


def fail(message: str) -> None:
    print(f"\nSTOPPED: {message}")
    print("No retry, no further generation - the script is exiting now.")
    sys.exit(1)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def load_manifest() -> dict:
    if MANIFEST_PATH.exists():
        return json.loads(MANIFEST_PATH.read_text())
    return {"experiment": "forma_video_1_chapter_b", "created_at": _now()}


def save_manifest(manifest: dict) -> None:
    MANIFEST_PATH.parent.mkdir(parents=True, exist_ok=True)
    MANIFEST_PATH.write_text(json.dumps(manifest, indent=2))


def main() -> None:
    skip_confirm = "--yes" in sys.argv[1:]

    key_preview = f"{settings.fal_api_key[:6]}..." if settings.fal_api_key else None
    print(f"FAL_API_KEY loaded from .env: {'yes (' + key_preview + ')' if key_preview else 'NO'}")
    if not settings.fal_api_key:
        fail("FAL_API_KEY is not set. Add FAL_API_KEY=your_key_here to your .env file and try again.")

    if not PREP2_RAW_PATH.exists():
        fail(
            f"{PREP2_RAW_PATH} not found - Chapter A's Site Prep Clip 2 has not been generated "
            "yet. Run scripts/run_forma_v1_chapter_a_prep2.py first."
        )

    # Mandatory upstream-approval gate - NOT the same as the cost
    # confirmation below, and not skippable by --yes.
    print(f"\nUpstream file found: {PREP2_RAW_PATH}")
    approval = input(
        "Have you reviewed and approved site_prep_clip2_raw.mp4? Type 'yes' to confirm before "
        "proceeding (anything else stops here, nothing generated): "
    ).strip().lower()
    if approval != "yes":
        print("Stopped - Site Prep Clip 2 was not confirmed as approved. Nothing was generated.")
        sys.exit(0)

    print(f"\n[1/2] Extracting the real last frame of site_prep_clip2_raw.mp4 locally (no API call)...")
    try:
        extract_last_frame(PREP2_RAW_PATH, SOURCE_FRAME_PATH)
    except FrameExtractionError as e:
        fail(f"Frame extraction failed: {e}")
    print(f"      Done -> {SOURCE_FRAME_PATH} (site_prep_clip2_raw.mp4 was only read, never modified)")

    image_provider = FalImageProvider(NANO_BANANA_PRO_EDIT)
    edit_request = ImageEditRequest(prompt=EDIT_PROMPT, reference_image_paths=[str(SOURCE_FRAME_PATH)])
    cost = image_provider.estimate_edit_cost()

    print("=" * 70)
    print("FORMA VIDEO #1 - CHAPTER B - STAGE B0 (CAMERA TRANSITION EDIT) - THIS WILL SPEND REAL MONEY")
    print("=" * 70)
    print(f"Model: {NANO_BANANA_PRO_EDIT.model_id}  (image edit, real Prep 2 pixels as input)")
    print(f"Source image: {SOURCE_FRAME_PATH} (real extracted pixels from Prep 2's raw output)")
    print(f"\nEdit prompt:\n  {EDIT_PROMPT}")
    print(f"\nEstimated cost: ${cost:.4f}")
    print(f"Hard cap:       ${MAX_SPEND_USD:.2f}")
    print("Rules: exactly 1 image-edit call, no video call, no retries - this stage stops here.")
    print("=" * 70)

    if cost > MAX_SPEND_USD:
        fail(f"Estimated cost ${cost:.4f} exceeds the ${MAX_SPEND_USD:.2f} cap. Nothing was generated.")

    if not skip_confirm:
        answer = input(f"\nType 'yes' to spend up to ${cost:.4f} and proceed: ").strip().lower()
        if answer != "yes":
            print("Cancelled. Nothing was generated.")
            sys.exit(0)

    manifest = load_manifest()
    manifest["camera_b_edit"] = {
        "image_model": NANO_BANANA_PRO_EDIT.model_id,
        "source_frame_path": str(SOURCE_FRAME_PATH),
        "edit_prompt": EDIT_PROMPT,
        "max_spend_usd": MAX_SPEND_USD,
        "estimated_cost_usd": cost,
        "output_path": None,
        "actual_cost_usd": None,
        "completed_at": None,
    }
    save_manifest(manifest)

    print(f"\n[2/2] Requesting Camera B transition edit -> {CAMERA_B_EDIT_PATH.name} ...")
    try:
        result = image_provider.edit_image(edit_request, str(CAMERA_B_EDIT_PATH))
    except ImageProviderError as e:
        fail(f"Edit failed: {e}")
    print(f"      Done -> {CAMERA_B_EDIT_PATH} (${result.cost_usd:.4f})")

    manifest["camera_b_edit"]["output_path"] = str(CAMERA_B_EDIT_PATH)
    manifest["camera_b_edit"]["actual_cost_usd"] = result.cost_usd
    manifest["camera_b_edit"]["completed_at"] = _now()
    save_manifest(manifest)

    print("\n" + "=" * 70)
    print("STAGE B0 (CAMERA TRANSITION EDIT) DONE - stopping completely, as required.")
    print("=" * 70)
    print(f"Camera B edit: {CAMERA_B_EDIT_PATH}")
    print(f"Actual cost:   ${result.cost_usd:.4f}")
    print(f"Manifest:      {MANIFEST_PATH}")
    print("\nSTOP HERE. Review camera_b_edit.jpg against:")
    print("  - clearly reads as the same physical site from a nearby camera position")
    print("  - the cleared/leveled pad and the single debris ridge are preserved unchanged")
    print("  - the skid-steer machine is preserved in the same position")
    print("  - cave, waterfall, rocks, and vegetation remain consistent")
    print("  - no construction of any kind was added (no foundation, walls, framing, or glass)")
    print("  - no obvious AI reconstruction that would break continuity")
    print("\nDo NOT run Stage B1 (Foundation) until you have reviewed and approved this edit.")
    print("Stage B1 is scripts/run_forma_v1_chapter_b_foundation.py - a separate script, not run automatically.")


if __name__ == "__main__":
    main()
