#!/usr/bin/env python3
"""FORMA VIDEO #2 - PRECONDITION: SITE REFERENCE IMAGE.

Establishes the canonical starting photo for Turquoise Alpine Lake ->
Modern Glass A-Frame Hideaway. Raw untouched site only - no structure, no
builder action. Everything downstream (all 8 shots) is either generated
directly from this image or from a real frame/edit descended from it, so
this is the single most important approval gate in the whole pipeline -
the same role Segment 1A's V1/V2 image played for the cliff-cabin project
(where a bad composition was caught here, before any video spend).

Makes exactly ONE Nano Banana Pro GENERATE call (text-to-image, no source
image - there is nothing to condition on yet). No video call. No retries.
Does NOT chain to Shot 1 - a separate script, run only after this image
is reviewed and approved.

Usage (from the repo root, with FAL_API_KEY set in your .env):
    python -m scripts.run_alpine_video_2_site_reference
    python -m scripts.run_alpine_video_2_site_reference --yes
"""
import sys

from app.config import settings
from app.providers.base import ImageGenerationRequest, ImageProviderError
from app.providers.image.fal import NANO_BANANA_PRO_GENERATE, FalImageProvider
from scripts.run_alpine_video_2_common import (
    ASPECT_RATIO,
    LOCATION_BIBLE,
    MANIFEST_PATH,
    OUTPUT_DIR,
    enforce_budget,
    fail,
    load_manifest,
    now,
    save_manifest,
)

MAX_SPEND_USD = 0.15  # flat rate, zero margin

SITE_REFERENCE_PATH = OUTPUT_DIR / "site_reference.jpg"

IMAGE_PROMPT = (
    "A wide vertical establishing photograph of " + LOCATION_BIBLE + ". "
    "The peninsula is empty and untouched - no structure, no construction materials, no "
    "builder visible yet. Realistic documentary photography style, not illustration or "
    "painting. The lake, mountains, and shoreline should occupy a major share of the frame - "
    "this location should be beautiful enough to stop scrolling on its own, before any "
    "construction begins."
)


def main() -> None:
    skip_confirm = "--yes" in sys.argv[1:]

    key_preview = f"{settings.fal_api_key[:6]}..." if settings.fal_api_key else None
    print(f"FAL_API_KEY loaded from .env: {'yes (' + key_preview + ')' if key_preview else 'NO'}")
    if not settings.fal_api_key:
        fail("FAL_API_KEY is not set. Add FAL_API_KEY=your_key_here to your .env file and try again.")

    image_provider = FalImageProvider(NANO_BANANA_PRO_GENERATE)
    image_request = ImageGenerationRequest(
        prompt=IMAGE_PROMPT, extra_params={"aspect_ratio": ASPECT_RATIO, "resolution": "1K"}
    )
    cost = image_provider.estimate_cost(image_request)

    print("=" * 70)
    print("FORMA VIDEO #2 - SITE REFERENCE IMAGE - THIS WILL SPEND REAL MONEY")
    print("=" * 70)
    print(f"Model: {NANO_BANANA_PRO_GENERATE.model_id}  (text-to-image, no source image)")
    print(f"\nImage prompt:\n  {IMAGE_PROMPT}")
    print(f"\nEstimated cost: ${cost:.4f}")
    print(f"Hard cap:       ${MAX_SPEND_USD:.2f}")
    print("Rules: exactly 1 image call, no video call, no retries - this stage stops here.")
    print("=" * 70)

    if cost > MAX_SPEND_USD:
        fail(f"Estimated cost ${cost:.4f} exceeds the ${MAX_SPEND_USD:.2f} cap. Nothing was generated.")
    enforce_budget(cost)

    if not skip_confirm:
        answer = input(f"\nType 'yes' to spend up to ${cost:.4f} and proceed: ").strip().lower()
        if answer != "yes":
            print("Cancelled. Nothing was generated.")
            sys.exit(0)

    manifest = load_manifest()
    manifest["site_reference"] = {
        "image_model": NANO_BANANA_PRO_GENERATE.model_id,
        "image_prompt": IMAGE_PROMPT,
        "max_spend_usd": MAX_SPEND_USD,
        "estimated_cost_usd": cost,
        "output_path": None,
        "actual_cost_usd": None,
        "completed_at": None,
    }
    save_manifest(manifest)

    print(f"\nRequesting site reference image -> {SITE_REFERENCE_PATH.name} ...")
    try:
        result = image_provider.generate_image(image_request, str(SITE_REFERENCE_PATH))
    except ImageProviderError as e:
        fail(f"Generation failed: {e}")
    print(f"      Done -> {SITE_REFERENCE_PATH} (${result.cost_usd:.4f})")

    manifest["site_reference"]["output_path"] = str(SITE_REFERENCE_PATH)
    manifest["site_reference"]["actual_cost_usd"] = result.cost_usd
    manifest["site_reference"]["completed_at"] = now()
    save_manifest(manifest)

    print("\n" + "=" * 70)
    print("SITE REFERENCE IMAGE DONE - stopping completely, as required.")
    print("=" * 70)
    print(f"Image:    {SITE_REFERENCE_PATH}")
    print(f"Cost:     ${result.cost_usd:.4f}")
    print(f"Manifest: {MANIFEST_PATH}")
    print("\nSTOP HERE. Review site_reference.jpg against:")
    print("  1. no structure, no materials, no builder action - completely untouched site")
    print("  2. lake color, mountain scale, shoreline, and light are as beautiful as intended")
    print("  3. environment reads as a major visual attraction on its own")
    print("  4. composition leaves room for the cabin to be built without redoing this image")
    print("\nDo NOT run Shot 1 until you have reviewed and approved this image.")
    print("Everything downstream depends on this being right.")


if __name__ == "__main__":
    main()
