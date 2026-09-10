#!/usr/bin/env python3
"""CLIFFSIDE VIDEO #1, PART 2 - JUMP CUT 2: FINISH CABIN EXTERIOR.

Only runnable after Shot 2 (Glass/Door mechanism) has been generated AND
approved - requires glass_raw.mp4 to already exist, and additionally asks
you to explicitly confirm you've reviewed and approved it before spending
anything. glass_raw.mp4 is only ever read, never modified.

This edit represents the remaining exterior work being completed: all
intended glass panels, the primary door, simple modern exterior cladding,
and a finished roof surface - while preserving the exact 12ft x 16ft
footprint, ~8ft wall height, ~10-11ft roof peak, and existing opening
positions. Compact and believable, never a mansion.

Makes exactly ONE Nano Banana Pro EDIT call ($0.15). No video call of
any kind. No retries. Does NOT chain to Shot 3 (Final Detail) - that is
a separate script, run only after this stage's own output is reviewed
and approved.

Usage (from the repo root, with FAL_API_KEY set in your .env, and
glass_raw.mp4 already generated and reviewed):
    python -m scripts.run_cliffside_video_1_part2_exterior_edit
    python -m scripts.run_cliffside_video_1_part2_exterior_edit --yes   (skips only the cost confirmation - the upstream-approval confirmation always runs)
"""
import json
import sys
from datetime import datetime, timezone

from app.config import settings
from app.providers.base import ImageEditRequest, ImageProviderError
from app.providers.image.fal import NANO_BANANA_PRO_EDIT, FalImageProvider
from app.services.frame_extraction import FrameExtractionError, extract_last_frame
from scripts.run_cliffside_video_1_part2_glass import GLASS_RAW_PATH
from scripts.run_cliffside_video_1_rough_assembly import MANIFEST_PATH, OUTPUT_DIR

MAX_SPEND_USD = 0.15  # flat rate, zero margin

GLASS_LAST_FRAME_PATH = OUTPUT_DIR / "glass_real_last_frame.jpg"
EXTERIOR_COMPLETE_EDIT_PATH = OUTPUT_DIR / "exterior_complete_edit.jpg"

EDIT_PROMPT = (
    "This is an intentional editorial jump cut - the same construction project, filmed again "
    "some time later, with the exterior now finished - not a different or redesigned cabin. Keep "
    "the underlying structure exactly as it is: the same approximately 12 by 16 foot footprint, "
    "the same approximately 8 foot wall height, the same roof peak around 10 to 11 feet, the same "
    "window and door opening positions, the same deck/platform, the same site, cliff, ocean, and "
    "coastline geometry, the same builder identity, and the same lighting direction. Shift the "
    "camera only slightly - approximately 15 to 20 degrees, or keep the same general direction if "
    "that better preserves the geometry. Complete the exterior: install all of the cabin's "
    "intended glass panels in the ocean-facing openings, install the primary door, apply a simple "
    "modern exterior cladding in a dark-stained timber or charcoal tone with natural wood accents "
    "and clean lines, and finish the roof surface. Keep the look premium but restrained - a "
    "compact, believable modern cliffside cabin, not a mansion. Do not add extra rooms, "
    "balconies, a second story, chimneys, solar panels, oversized overhangs, outdoor furniture, "
    "or decorative clutter. Do not change the platform size or the cabin's footprint."
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

    if not GLASS_RAW_PATH.exists():
        fail(
            f"{GLASS_RAW_PATH} not found - Shot 2 (Glass/Door) has not been generated yet. "
            "Run scripts/run_cliffside_video_1_part2_glass.py first."
        )

    print(f"\nUpstream file found: {GLASS_RAW_PATH}")
    approval = input(
        "Have you reviewed and approved glass_raw.mp4? Type 'yes' to confirm before proceeding "
        "(anything else stops here, nothing generated): "
    ).strip().lower()
    if approval != "yes":
        print("Stopped - Glass/Door was not confirmed as approved. Nothing was generated.")
        sys.exit(0)

    print("\n[1/2] Extracting the real last frame of glass_raw.mp4 locally (no API call)...")
    try:
        extract_last_frame(GLASS_RAW_PATH, GLASS_LAST_FRAME_PATH)
    except FrameExtractionError as e:
        fail(f"Frame extraction failed: {e}")
    print(f"      Done -> {GLASS_LAST_FRAME_PATH} (glass_raw.mp4 was only read, never modified)")

    image_provider = FalImageProvider(NANO_BANANA_PRO_EDIT)
    edit_request = ImageEditRequest(prompt=EDIT_PROMPT, reference_image_paths=[str(GLASS_LAST_FRAME_PATH)])
    cost = image_provider.estimate_edit_cost()

    print("=" * 70)
    print("CLIFFSIDE VIDEO #1 - PART 2 - JUMP CUT 2 (EXTERIOR COMPLETE) - THIS WILL SPEND REAL MONEY")
    print("=" * 70)
    print(f"Model: {NANO_BANANA_PRO_EDIT.model_id}  (image edit, real Glass/Door pixels as input)")
    print(f"Source image: {GLASS_LAST_FRAME_PATH}")
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
    manifest["exterior_complete_edit"] = {
        "image_model": NANO_BANANA_PRO_EDIT.model_id,
        "source_frame_path": str(GLASS_LAST_FRAME_PATH),
        "edit_prompt": EDIT_PROMPT,
        "max_spend_usd": MAX_SPEND_USD,
        "estimated_cost_usd": cost,
        "output_path": None,
        "actual_cost_usd": None,
        "completed_at": None,
    }
    save_manifest(manifest)

    print(f"\n[2/2] Requesting exterior-completion edit -> {EXTERIOR_COMPLETE_EDIT_PATH.name} ...")
    try:
        result = image_provider.edit_image(edit_request, str(EXTERIOR_COMPLETE_EDIT_PATH))
    except ImageProviderError as e:
        fail(f"Edit failed: {e}")
    print(f"      Done -> {EXTERIOR_COMPLETE_EDIT_PATH} (${result.cost_usd:.4f})")

    manifest["exterior_complete_edit"]["output_path"] = str(EXTERIOR_COMPLETE_EDIT_PATH)
    manifest["exterior_complete_edit"]["actual_cost_usd"] = result.cost_usd
    manifest["exterior_complete_edit"]["completed_at"] = _now()
    save_manifest(manifest)

    print("\n" + "=" * 70)
    print("JUMP CUT 2 (EXTERIOR COMPLETE) DONE - stopping completely, as required.")
    print("=" * 70)
    print(f"Exterior-complete edit: {EXTERIOR_COMPLETE_EDIT_PATH}")
    print(f"Actual cost:            ${result.cost_usd:.4f}")
    print(f"Manifest:               {MANIFEST_PATH}")
    print("\nSTOP HERE. Review exterior_complete_edit.jpg against:")
    print("  1. same ~12x16ft footprint, ~8ft wall height, ~10-11ft roof peak preserved")
    print("  2. all glass panels + primary door installed, positions consistent with framing")
    print("  3. dark-toned modern cladding + finished roof surface - compact, not a mansion")
    print("  4. no extra rooms/balconies/second story/chimneys/solar/clutter added")
    print("  5. platform, site, lighting, and builder identity preserved")
    print("\nDo NOT run Shot 3 (Final Detail) until you have reviewed and approved this edit.")
    print("That is scripts/run_cliffside_video_1_part2_final_detail.py - a separate script.")


if __name__ == "__main__":
    main()
