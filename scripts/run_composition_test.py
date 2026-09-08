#!/usr/bin/env python3
"""COMPOSITION EXPERIMENT: prove that a FRESHLY GENERATED base action image
can get the builder/camera relationship right (observational angle, no eye
contact, working posture) BEFORE spending anything on mechanical hand/tool
correction or video interpolation.

This is a narrower, earlier gate than V2A - V2A tried to fix the
builder/camera relationship by EDITING an already front-facing image and
that didn't work (edit models make small local corrections; a full
pose/camera reorientation is a global compositional change, actively
suppressed by "change as little else as possible" instructions). This
script tests the fix instead: generate the composition correctly from
scratch, so the follow-up edit pass (if this succeeds) only has to do local
mechanical corrections on an already-correctly-composed image.

Makes exactly ONE call - fal-ai/nano-banana-pro's text-to-image endpoint
(NANO_BANANA_PRO_GENERATE in app/providers/image/fal.py), not the /edit
endpoint used by V2A. No reference image is used or needed - this is a
from-scratch generation, not an edit of the bake-off's image, precisely
because the bake-off image's composition is what's being replaced.

This script does not edit anything and does not generate video. It stops
after the one image so it can be manually reviewed against the composition
success criteria (see the printed checklist at the end) before any further
spend.

Safety, same pattern as every other real-call script in this repo:
  - Exactly 1 image-generation call. No loop, no retry, no auto-regeneration.
  - Total cost checked against MAX_SPEND_USD BEFORE the call; one
    "type yes" confirmation gates the run.
  - manifest.json records the exact prompt, cost, and output path.

Usage (from the repo root, with FAL_API_KEY set in your .env):
    python -m scripts.run_composition_test
    python -m scripts.run_composition_test --yes
"""
import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

from app.config import settings
from app.providers.base import ImageGenerationRequest, ImageProviderError
from app.providers.image.fal import NANO_BANANA_PRO_GENERATE, FalImageProvider

MAX_SPEND_USD = 0.20

OUTPUT_DIR = Path(__file__).resolve().parent.parent / "data" / "fal_composition_test"
MANIFEST_PATH = OUTPUT_DIR / "manifest.json"

# Continuity identity clause woven into the user's composition prompt
# (kept as close to verbatim as possible - composition/gaze/camera
# instructions are the whole point of this experiment and must not be
# diluted by identity detail).
COMPOSITION_TEST_PROMPT = (
    "Vertical 9:16 candid documentary-style construction footage. A rugged male builder, "
    "approximately mid-40s, with slightly messy dark hair, short beard/stubble, and a medium "
    "athletic build, wearing worn jeans, a plain work shirt with no visible logo or branding, "
    "and brown work boots, is actively preparing to cut a timber board with a circular saw "
    "while building a small timber cabin on a dramatic ocean cliff at golden hour. Camera is "
    "positioned behind and approximately 45-70 degrees to one side of the builder, producing a "
    "natural three-quarter-rear/side view. He is completely absorbed in the work and unaware of "
    "the camera. His head and eyes are directed downward toward the saw blade and marked cut "
    "line, never toward the viewer. His torso leans naturally toward the work surface and his "
    "feet are planted in a realistic working stance. The circular saw, timber board, both "
    "hands, and cutting area remain clearly visible and are not obscured by his body. The "
    "partially constructed timber cabin - a completed timber floor deck and partial wall "
    "framing already in place - occupies substantial space in the frame and clearly reads as "
    "an active construction site. The dramatic ocean and cliff remain visible around the "
    "worksite. Natural candid worksite composition, as though a second person casually filmed "
    "him working. No eye contact, no posing, no centered hero composition, no presenter stance, "
    "no commercial construction advertisement, no fashion photography."
)

SUCCESS_CRITERIA = [
    "Builder is clearly NOT looking at the camera",
    "Gaze is directed at the work (saw/cut line), not the viewer",
    "Side / three-quarter-rear observational angle reads immediately",
    "Body posture looks like someone actually working, not standing/posing",
    "Saw and timber interaction area is clearly visible (not obscured)",
    "Composition does not resemble an advertisement or hero portrait",
    "Cabin reads as the active project, not merely a background prop",
    "Landscape (ocean/cliff) remains visually compelling",
    "Recurring builder identity remains recognizable (build, clothing, hair/beard)",
    "(Mechanical saw perfection is NOT a pass/fail criterion here - that's the next stage)",
]


def fail(message: str) -> None:
    print(f"\nSTOPPED: {message}")
    print(f"No retry, no further generation - the script is exiting now. Manifest: {MANIFEST_PATH}")
    sys.exit(1)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def save_manifest(manifest: dict) -> None:
    MANIFEST_PATH.parent.mkdir(parents=True, exist_ok=True)
    MANIFEST_PATH.write_text(json.dumps(manifest, indent=2))


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Composition test: 1 Nano Banana Pro text-to-image call for an observational, non-posed base action frame."
    )
    parser.add_argument("--yes", action="store_true", help="Skip the 'type yes' confirmation prompt")
    args = parser.parse_args()

    key_preview = f"{settings.fal_api_key[:6]}..." if settings.fal_api_key else None
    print(f"FAL_API_KEY loaded from .env: {'yes (' + key_preview + ')' if key_preview else 'NO'}")
    if not settings.fal_api_key:
        fail("FAL_API_KEY is not set. Add FAL_API_KEY=your_key_here to your .env file and try again.")

    provider = FalImageProvider(NANO_BANANA_PRO_GENERATE)
    request = ImageGenerationRequest(
        prompt=COMPOSITION_TEST_PROMPT, extra_params={"aspect_ratio": "9:16", "resolution": "1K"}
    )
    cost = provider.estimate_cost(request)

    print("=" * 70)
    print("COMPOSITION TEST - THIS WILL SPEND REAL MONEY")
    print("=" * 70)
    print(f"Model: {NANO_BANANA_PRO_GENERATE.model_id}  (text-to-image, not /edit - no input image used)")
    print(f"\nPrompt:\n  {COMPOSITION_TEST_PROMPT}")
    print(f"\nEstimated cost: ${cost:.4f}")
    print(f"Hard cap:       ${MAX_SPEND_USD:.2f}")
    print("Rules: exactly 1 image-generation call, no edit calls, no video calls, no retries.")
    print("=" * 70)

    if cost > MAX_SPEND_USD:
        fail(f"Estimated cost ${cost:.4f} exceeds the ${MAX_SPEND_USD:.2f} cap. Nothing was generated.")

    if not args.yes:
        answer = input(f"\nType 'yes' to spend up to ${cost:.4f} and proceed: ").strip().lower()
        if answer != "yes":
            print("Cancelled. Nothing was generated.")
            sys.exit(0)

    manifest = {
        "created_at": _now(),
        "experiment": "composition_test",
        "model": NANO_BANANA_PRO_GENERATE.model_id,
        "prompt": COMPOSITION_TEST_PROMPT,
        "max_spend_usd": MAX_SPEND_USD,
        "estimated_cost_usd": cost,
        "output_path": None,
        "actual_cost_usd": None,
        "completed_at": None,
    }
    save_manifest(manifest)

    dest = OUTPUT_DIR / "action_base_frame.jpg"
    print(f"\n[generate] Requesting composition base frame -> {dest.name} ...")
    try:
        result = provider.generate_image(request, str(dest))
    except ImageProviderError as e:
        fail(f"generation failed: {e}")
    print(f"           Done -> {dest} (${result.cost_usd:.4f})")

    manifest["output_path"] = str(dest)
    manifest["actual_cost_usd"] = result.cost_usd
    manifest["completed_at"] = _now()
    save_manifest(manifest)

    print("\n" + "=" * 70)
    print("DONE - 1 image generated. No edit or video call was made.")
    print("=" * 70)
    print(f"action_base_frame: {dest}")
    print(f"Actual cost: ${result.cost_usd:.4f}")
    print(f"Manifest: {MANIFEST_PATH}")
    print("\nSTOP HERE. Review this image against the composition checklist:")
    for item in SUCCESS_CRITERIA:
        print(f"  - {item}")
    print("\nDo not run any edit or video-generation step until you've reviewed and approved")
    print("this frame - this script will not regenerate or fix it automatically.")


if __name__ == "__main__":
    main()
