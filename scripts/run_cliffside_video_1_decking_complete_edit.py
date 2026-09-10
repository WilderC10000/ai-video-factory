#!/usr/bin/env python3
"""CLIFFSIDE VIDEO #1, PART 2 - STAGE C0: DECKING-COMPLETION EDIT.

Precondition for Part 2's Framing shot: Part 1's rough assembly ends with
the Construction Frontier Test's real decking clip, which shows the
right-to-left decking operation still in progress (some boards installed,
some joists still exposed). Framing cannot begin from a floor that isn't
finished, so this stage performs the "DEMONSTRATE -> JUMP CUT" jump cut
that completes the decking phase, per the FORMA jump-cut grammar and the
compound-edit mechanism already validated in isolation by
scripts/run_edit_advance_completion_test.py - here applied for real
production use, on the actual confirmed-existing source (the Construction
Frontier Test's own real last frame), not that test's own validation
source.

Only runnable after the Construction Frontier Test's real raw output
(construction_frontier_raw.mp4) exists - this script requires it, and
additionally asks you to explicitly confirm you've reviewed and approved
it (a separate confirmation from the cost confirmation below) before it
spends anything. construction_frontier_raw.mp4 is only ever read, never
modified.

Makes exactly ONE Nano Banana Pro EDIT call ($0.15). No video call of any
kind. No retries. Does NOT chain to Part 2's Framing shot - that is a
separate script, run only after this stage's own output is reviewed and
approved.

Usage (from the repo root, with FAL_API_KEY set in your .env, and
construction_frontier_raw.mp4 already generated and reviewed):
    python -m scripts.run_cliffside_video_1_decking_complete_edit
    python -m scripts.run_cliffside_video_1_decking_complete_edit --yes   (skips only the cost confirmation - the upstream-approval confirmation always runs)
"""
import json
import sys
from datetime import datetime, timezone

from app.config import settings
from app.providers.base import ImageEditRequest, ImageProviderError
from app.providers.image.fal import NANO_BANANA_PRO_EDIT, FalImageProvider
from app.services.frame_extraction import FrameExtractionError, extract_last_frame
from scripts.run_cliffside_video_1_rough_assembly import MANIFEST_PATH, OUTPUT_DIR
from scripts.run_construction_frontier_test import RAW_VIDEO_PATH as DECKING_RAW_PATH

MAX_SPEND_USD = 0.15  # flat rate, zero margin

DECKING_LAST_FRAME_PATH = OUTPUT_DIR / "decking_real_last_frame.jpg"
DECKING_COMPLETE_EDIT_PATH = OUTPUT_DIR / "decking_complete_edit.jpg"

EDIT_PROMPT = (
    "This is an intentional editorial jump cut - the same construction project, filmed again "
    "some time later, with the same decking phase now fully completed - not a different or "
    "redesigned version of the build. Keep the underlying structure exactly as it is: the same "
    "platform proportions, the same foundation posts and perimeter beams in the same positions, "
    "the same joist layout, the same builder (same identity, clothing, and pose intent), the "
    "same site, cliff, boulder, and coastline geometry, and the same lighting direction. Shift "
    "the camera only slightly - approximately 15 to 20 degrees around the site - to a nearby, "
    "modestly different viewpoint. Advance ONLY the decking: complete every remaining exposed "
    "joist with the same style and spacing of deck boards already visible, so the entire "
    "platform now reads as a fully decked floor with no exposed joists remaining. Do not change "
    "the platform's size or shape, do not move or add any posts or beams, do not alter the site "
    "or landscape, and do not begin or imply any next construction phase - no wall studs, no "
    "framing, no roof, no glass. This is purely completing the decking phase and a small camera "
    "nudge, not inventing new construction."
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
    return {"experiment": "cliffside_video_1", "created_at": _now()}


def save_manifest(manifest: dict) -> None:
    MANIFEST_PATH.parent.mkdir(parents=True, exist_ok=True)
    MANIFEST_PATH.write_text(json.dumps(manifest, indent=2))


def main() -> None:
    skip_confirm = "--yes" in sys.argv[1:]

    key_preview = f"{settings.fal_api_key[:6]}..." if settings.fal_api_key else None
    print(f"FAL_API_KEY loaded from .env: {'yes (' + key_preview + ')' if key_preview else 'NO'}")
    if not settings.fal_api_key:
        fail("FAL_API_KEY is not set. Add FAL_API_KEY=your_key_here to your .env file and try again.")

    if not DECKING_RAW_PATH.exists():
        fail(
            f"{DECKING_RAW_PATH} not found - the Construction Frontier Test has not been "
            "generated yet. Run scripts/run_construction_frontier_test.py first."
        )

    print(f"\nUpstream file found: {DECKING_RAW_PATH}")
    approval = input(
        "Have you reviewed and approved construction_frontier_raw.mp4? Type 'yes' to confirm "
        "before proceeding (anything else stops here, nothing generated): "
    ).strip().lower()
    if approval != "yes":
        print("Stopped - the decking clip was not confirmed as approved. Nothing was generated.")
        sys.exit(0)

    print("\n[1/2] Extracting the real last frame of construction_frontier_raw.mp4 locally (no API call)...")
    try:
        extract_last_frame(DECKING_RAW_PATH, DECKING_LAST_FRAME_PATH)
    except FrameExtractionError as e:
        fail(f"Frame extraction failed: {e}")
    print(f"      Done -> {DECKING_LAST_FRAME_PATH} (construction_frontier_raw.mp4 was only read, never modified)")

    image_provider = FalImageProvider(NANO_BANANA_PRO_EDIT)
    edit_request = ImageEditRequest(prompt=EDIT_PROMPT, reference_image_paths=[str(DECKING_LAST_FRAME_PATH)])
    cost = image_provider.estimate_edit_cost()

    print("=" * 70)
    print("CLIFFSIDE VIDEO #1 - PART 2 - STAGE C0 (DECKING-COMPLETION EDIT) - THIS WILL SPEND REAL MONEY")
    print("=" * 70)
    print(f"Model: {NANO_BANANA_PRO_EDIT.model_id}  (image edit, real Construction Frontier Test pixels as input)")
    print(f"Source image: {DECKING_LAST_FRAME_PATH}")
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
    manifest["decking_complete_edit"] = {
        "image_model": NANO_BANANA_PRO_EDIT.model_id,
        "source_frame_path": str(DECKING_LAST_FRAME_PATH),
        "edit_prompt": EDIT_PROMPT,
        "max_spend_usd": MAX_SPEND_USD,
        "estimated_cost_usd": cost,
        "output_path": None,
        "actual_cost_usd": None,
        "completed_at": None,
    }
    save_manifest(manifest)

    print(f"\n[2/2] Requesting decking-completion edit -> {DECKING_COMPLETE_EDIT_PATH.name} ...")
    try:
        result = image_provider.edit_image(edit_request, str(DECKING_COMPLETE_EDIT_PATH))
    except ImageProviderError as e:
        fail(f"Edit failed: {e}")
    print(f"      Done -> {DECKING_COMPLETE_EDIT_PATH} (${result.cost_usd:.4f})")

    manifest["decking_complete_edit"]["output_path"] = str(DECKING_COMPLETE_EDIT_PATH)
    manifest["decking_complete_edit"]["actual_cost_usd"] = result.cost_usd
    manifest["decking_complete_edit"]["completed_at"] = _now()
    save_manifest(manifest)

    print("\n" + "=" * 70)
    print("STAGE C0 (DECKING-COMPLETION EDIT) DONE - stopping completely, as required.")
    print("=" * 70)
    print(f"Decking-complete edit: {DECKING_COMPLETE_EDIT_PATH}")
    print(f"Actual cost:           ${result.cost_usd:.4f}")
    print(f"Manifest:              {MANIFEST_PATH}")
    print("\nSTOP HERE. Review decking_complete_edit.jpg against:")
    print("  1. same physical platform/structure clearly preserved")
    print("  2. the entire floor now reads as fully decked - no exposed joists remaining")
    print("  3. camera change is modest (~15-20 degrees) and believable")
    print("  4. major geometry/landmarks (platform, posts, boulder, coastline) remain consistent")
    print("  5. no next-phase elements appear (no studs, framing, roof, or glass)")
    print("\nDo NOT run the Framing shot until you have reviewed and approved this edit.")
    print("Framing is scripts/run_cliffside_video_1_part2_framing.py - a separate script.")


if __name__ == "__main__":
    main()
