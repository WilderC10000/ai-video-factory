#!/usr/bin/env python3
"""CLIFFSIDE VIDEO #1, PART 2 - JUMP CUT 1: COMPLETE WALL FRAMING.

Only runnable after Shot 1 (Wall Framing mechanism) has been generated
AND approved - requires framing_raw.mp4 to already exist, and
additionally asks you to explicitly confirm you've reviewed and approved
it before spending anything. framing_raw.mp4 is only ever read, never
modified.

This edit represents several hours of elapsed construction time (per the
FORMA jump-cut grammar): it advances ONLY the framing phase to
completion - all four wall frames, a simple roof skeleton - while
preserving the 12ft x 16ft footprint, ~8ft wall height, site, and
lighting. No glass or siding yet; those are Shot 2's and Jump Cut 2's
job.

Makes exactly ONE Nano Banana Pro EDIT call ($0.15). No video call of
any kind. No retries. Does NOT chain to Shot 2 (Glass/Door) - that is a
separate script, run only after this stage's own output is reviewed and
approved.

Usage (from the repo root, with FAL_API_KEY set in your .env, and
framing_raw.mp4 already generated and reviewed):
    python -m scripts.run_cliffside_video_1_part2_framing_edit
    python -m scripts.run_cliffside_video_1_part2_framing_edit --yes   (skips only the cost confirmation - the upstream-approval confirmation always runs)
"""
import json
import sys
from datetime import datetime, timezone

from app.config import settings
from app.providers.base import ImageEditRequest, ImageProviderError
from app.providers.image.fal import NANO_BANANA_PRO_EDIT, FalImageProvider
from app.services.frame_extraction import FrameExtractionError, extract_last_frame
from scripts.run_cliffside_video_1_part2_framing import FRAMING_RAW_PATH
from scripts.run_cliffside_video_1_rough_assembly import MANIFEST_PATH, OUTPUT_DIR

MAX_SPEND_USD = 0.15  # flat rate, zero margin

FRAMING_LAST_FRAME_PATH = OUTPUT_DIR / "framing_real_last_frame.jpg"
FRAMING_COMPLETE_EDIT_PATH = OUTPUT_DIR / "framing_complete_edit.jpg"

EDIT_PROMPT = (
    "This is an intentional editorial jump cut - the same construction project, filmed again "
    "some time later, with the wall framing phase now substantially further along - not a "
    "different or redesigned cabin. Keep the underlying structure exactly as it is: the same "
    "approximately 12 by 16 foot platform footprint, the same deck, the same site, cliff, "
    "boulder, ocean, and coastline geometry, the same builder (identity, clothing, pose intent), "
    "and the same lighting direction. Shift the camera only slightly - approximately 15 to 20 "
    "degrees around the site - to a nearby, modestly different viewpoint. Advance the framing: "
    "complete all four wall frames of the cabin at the same approximately 12 by 16 foot footprint "
    "and approximately 8 foot wall height, with evenly spaced vertical timber studs matching the "
    "spacing already established, a clear rectangular door opening on one side wall, and large "
    "framed window/glass openings on the ocean-facing wall. Add only the minimum roof skeleton "
    "needed to read as a simple shallow gable or mono-pitch roof frame, with its peak reaching "
    "approximately 10 to 11 feet - no finished roof surface, no shingles or panels yet. Do not "
    "install any glass, door, or siding yet. Do not change the platform size or the cabin's "
    "footprint. Do not add a second story, balconies, or any extra rooms or wings."
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

    if not FRAMING_RAW_PATH.exists():
        fail(
            f"{FRAMING_RAW_PATH} not found - Shot 1 (Wall Framing) has not been generated yet. "
            "Run scripts/run_cliffside_video_1_part2_framing.py first."
        )

    print(f"\nUpstream file found: {FRAMING_RAW_PATH}")
    approval = input(
        "Have you reviewed and approved framing_raw.mp4? Type 'yes' to confirm before proceeding "
        "(anything else stops here, nothing generated): "
    ).strip().lower()
    if approval != "yes":
        print("Stopped - Wall Framing was not confirmed as approved. Nothing was generated.")
        sys.exit(0)

    print("\n[1/2] Extracting the real last frame of framing_raw.mp4 locally (no API call)...")
    try:
        extract_last_frame(FRAMING_RAW_PATH, FRAMING_LAST_FRAME_PATH)
    except FrameExtractionError as e:
        fail(f"Frame extraction failed: {e}")
    print(f"      Done -> {FRAMING_LAST_FRAME_PATH} (framing_raw.mp4 was only read, never modified)")

    image_provider = FalImageProvider(NANO_BANANA_PRO_EDIT)
    edit_request = ImageEditRequest(prompt=EDIT_PROMPT, reference_image_paths=[str(FRAMING_LAST_FRAME_PATH)])
    cost = image_provider.estimate_edit_cost()

    print("=" * 70)
    print("CLIFFSIDE VIDEO #1 - PART 2 - JUMP CUT 1 (FRAMING COMPLETE) - THIS WILL SPEND REAL MONEY")
    print("=" * 70)
    print(f"Model: {NANO_BANANA_PRO_EDIT.model_id}  (image edit, real Wall Framing pixels as input)")
    print(f"Source image: {FRAMING_LAST_FRAME_PATH}")
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
    manifest["framing_complete_edit"] = {
        "image_model": NANO_BANANA_PRO_EDIT.model_id,
        "source_frame_path": str(FRAMING_LAST_FRAME_PATH),
        "edit_prompt": EDIT_PROMPT,
        "max_spend_usd": MAX_SPEND_USD,
        "estimated_cost_usd": cost,
        "output_path": None,
        "actual_cost_usd": None,
        "completed_at": None,
    }
    save_manifest(manifest)

    print(f"\n[2/2] Requesting framing-completion edit -> {FRAMING_COMPLETE_EDIT_PATH.name} ...")
    try:
        result = image_provider.edit_image(edit_request, str(FRAMING_COMPLETE_EDIT_PATH))
    except ImageProviderError as e:
        fail(f"Edit failed: {e}")
    print(f"      Done -> {FRAMING_COMPLETE_EDIT_PATH} (${result.cost_usd:.4f})")

    manifest["framing_complete_edit"]["output_path"] = str(FRAMING_COMPLETE_EDIT_PATH)
    manifest["framing_complete_edit"]["actual_cost_usd"] = result.cost_usd
    manifest["framing_complete_edit"]["completed_at"] = _now()
    save_manifest(manifest)

    print("\n" + "=" * 70)
    print("JUMP CUT 1 (FRAMING COMPLETE) DONE - stopping completely, as required.")
    print("=" * 70)
    print(f"Framing-complete edit: {FRAMING_COMPLETE_EDIT_PATH}")
    print(f"Actual cost:           ${result.cost_usd:.4f}")
    print(f"Manifest:              {MANIFEST_PATH}")
    print("\nSTOP HERE. Review framing_complete_edit.jpg against:")
    print("  1. all four wall frames complete, same ~12x16ft footprint, same ~8ft wall height")
    print("  2. evenly spaced studs, clear door opening, framed window openings on ocean side")
    print("  3. simple roof skeleton present, peak ~10-11ft - no finished roof surface")
    print("  4. no glass, no siding installed yet")
    print("  5. camera change modest (~15-20 degrees), platform/site/lighting preserved")
    print("\nDo NOT run Shot 2 (Glass/Door) until you have reviewed and approved this edit.")
    print("That is scripts/run_cliffside_video_1_part2_glass.py - a separate script.")


if __name__ == "__main__":
    main()
