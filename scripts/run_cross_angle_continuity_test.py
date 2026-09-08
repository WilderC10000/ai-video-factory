#!/usr/bin/env python3
"""CROSS-ANGLE CONTINUITY EXPERIMENT: before generating any video for the
full ~65-70s production, prove that two INDEPENDENTLY generated still images,
shot from two clearly different camera angles, can convincingly depict the
SAME builder, SAME cabin, SAME construction state, and SAME ocean-cliff
location.

This matters because the planned full video uses six different camera
positions across six segments. Last-frame propagation (the mechanism used to
keep continuity between clips at a FIXED camera angle) cannot itself change
the camera position - a fresh reference image must be generated for every
angle change, conditioned only on a shared text description (the "continuity
bible" below) plus an angle-specific framing instruction. This experiment
tests whether that mechanism can hold up at all, isolated from every other
variable (no video, no motion, no prompt drift from construction-progress
language) before it's relied on for six segments in a row.

Makes exactly TWO calls - fal-ai/nano-banana-pro's text-to-image endpoint
(NANO_BANANA_PRO_GENERATE in app/providers/image/fal.py). No source/reference
image is used for either call - both are fresh from-scratch generations, each
built from the same fixed continuity-bible text plus a different camera-angle
clause. No video generation of any kind happens in this script.

For this test, continuity is explicitly prioritized over beauty: the two
prompts intentionally over-specify shared landmarks (a distinctive boulder,
cabin dimensions, framing state, ocean orientation, lighting) so a human
reviewer can directly check whether those specific details actually match
between the two images.

Safety, same pattern as every other real-call script in this repo:
  - Exactly 2 image-generation calls. No loop, no retry, no auto-regeneration.
  - Total cost checked against MAX_SPEND_USD BEFORE either call; one
    "type yes" confirmation gates the whole run.
  - manifest.json records both prompts, both costs, and both output paths.

Usage (from the repo root, with FAL_API_KEY set in your .env):
    python -m scripts.run_cross_angle_continuity_test
    python -m scripts.run_cross_angle_continuity_test --yes
"""
import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

from app.config import settings
from app.providers.base import ImageGenerationRequest, ImageProviderError
from app.providers.image.fal import NANO_BANANA_PRO_GENERATE, FalImageProvider

MAX_SPEND_USD = 0.30

OUTPUT_DIR = Path(__file__).resolve().parent.parent / "data" / "fal_cross_angle_continuity_test"
MANIFEST_PATH = OUTPUT_DIR / "manifest.json"

# Fixed continuity bible - the same description of builder, cabin, terrain,
# and lighting is woven into BOTH prompts unchanged. Only the camera-angle
# clause differs between the two calls. This is deliberately over-specified
# (boulder position, exact wall-framing state, sun direction) so continuity
# between the two independently generated images can be directly checked.
CONTINUITY_BIBLE = (
    "A rugged male builder in his mid-40s, with slightly messy dark brown hair, a short dark "
    "beard/stubble, and a medium athletic build, wearing worn faded blue-grey jeans, a plain "
    "heather-grey crew-neck work shirt with no visible logo or branding, and brown leather work "
    "boots. He is building a small single-story timber cabin under construction on a flat rocky "
    "clifftop clearing. The cabin has a rectangular footprint roughly 5 meters wide by 4 meters "
    "deep, with eaves about 1.5 times the builder's standing height. The timber floor deck is "
    "fully complete and level. Wall framing is already built on two adjacent sides - one "
    "landward-facing side and one side-facing wall - using evenly spaced raw, unfinished, "
    "pale-yellow structural timber studs. The third side, facing the ocean, is completely open "
    "with no framing at all. There is no roof yet and no windows or doors yet. The clifftop "
    "clearing is roughly triangular, narrowing toward the cliff edge, which drops sharply about "
    "8-10 meters beyond the open ocean-facing side of the cabin; the ocean and horizon are "
    "visible directly beyond that open side. A distinctive large flat grey boulder sits near the "
    "rear corner of the platform, on the same side as the landward-facing framed wall. Sparse "
    "wind-bent low shrubs and scrub grass line the cliff edge, and a narrow dirt access path "
    "approaches from the landward side. The lighting is warm, low-angle, late-afternoon golden "
    "hour sunlight coming from the landward side of the cabin, casting long soft shadows. Candid "
    "documentary/observational photography style, vertical 9:16 aspect ratio."
)

IMAGE_1_ANGLE = (
    "Camera view: a wide three-quarter-rear observational angle, positioned behind and to one "
    "side of the builder, looking past him toward the open ocean-facing side of the structure - "
    "the shot shows the timber floor deck, both framed walls, the open ocean-facing side, the "
    "large flat grey boulder near the rear corner on the builder's side of the frame, and the "
    "ocean and cliff edge beyond. The builder is working naturally - handling a length of timber "
    "near the wall framing, his weight engaged in the task - facing away from the camera and "
    "never looking toward it. No posing, no presenter stance, no eye contact with the camera."
)

IMAGE_2_ANGLE = (
    "Camera view: an opposite-side three-quarter observational angle - positioned on the OTHER "
    "side of the structure from a companion shot, roughly diagonally across the platform from "
    "that position, looking across the floor deck toward the framed walls from this new "
    "direction. The shot still shows the open ocean-facing side and the ocean and cliff edge "
    "beyond, with the large flat grey boulder now appearing on the opposite side of the frame "
    "compared to a three-quarter-rear view, consistent with the camera having moved around to "
    "the other side of the same site. The builder is working naturally on the wall framing, body "
    "oriented toward his work, never looking toward the camera. No posing, no presenter stance, "
    "no eye contact with the camera."
)

IMAGE_1_PROMPT = f"{CONTINUITY_BIBLE} {IMAGE_1_ANGLE}"
IMAGE_2_PROMPT = f"{CONTINUITY_BIBLE} {IMAGE_2_ANGLE}"

COMPARISON_CHECKLIST = [
    "Builder identity/clothing consistent between both images",
    "Cabin dimensions/proportions consistent",
    "Framing geometry (which two sides are framed, which is open) consistent",
    "Door/window positions consistent (none yet, in both)",
    "Ocean direction consistent relative to the cabin",
    "Cliff/terrain geometry consistent",
    "Recognizable environmental landmarks (the boulder, access path, shrubs) consistent",
    "Lighting (golden-hour direction/color) consistent",
    "Overall impression: would a viewer immediately believe these are two cameras filming the same construction project?",
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
        description="Cross-angle continuity test: 2 Nano Banana Pro text-to-image calls, same continuity bible, two different camera angles."
    )
    parser.add_argument("--yes", action="store_true", help="Skip the 'type yes' confirmation prompt")
    args = parser.parse_args()

    key_preview = f"{settings.fal_api_key[:6]}..." if settings.fal_api_key else None
    print(f"FAL_API_KEY loaded from .env: {'yes (' + key_preview + ')' if key_preview else 'NO'}")
    if not settings.fal_api_key:
        fail("FAL_API_KEY is not set. Add FAL_API_KEY=your_key_here to your .env file and try again.")

    provider = FalImageProvider(NANO_BANANA_PRO_GENERATE)

    request_1 = ImageGenerationRequest(
        prompt=IMAGE_1_PROMPT, extra_params={"aspect_ratio": "9:16", "resolution": "1K"}
    )
    request_2 = ImageGenerationRequest(
        prompt=IMAGE_2_PROMPT, extra_params={"aspect_ratio": "9:16", "resolution": "1K"}
    )
    cost_1 = provider.estimate_cost(request_1)
    cost_2 = provider.estimate_cost(request_2)
    total_cost = cost_1 + cost_2

    print("=" * 70)
    print("CROSS-ANGLE CONTINUITY TEST - THIS WILL SPEND REAL MONEY")
    print("=" * 70)
    print(f"Model: {NANO_BANANA_PRO_GENERATE.model_id}  (text-to-image, not /edit - no input image used)")
    print(f"\nContinuity bible (shared by both prompts):\n  {CONTINUITY_BIBLE}")
    print(f"\nImage 1 angle clause (wide three-quarter-rear):\n  {IMAGE_1_ANGLE}")
    print(f"\nImage 2 angle clause (opposite-side three-quarter):\n  {IMAGE_2_ANGLE}")
    print(f"\nEstimated cost: image 1 ${cost_1:.4f} + image 2 ${cost_2:.4f} = ${total_cost:.4f}")
    print(f"Hard cap:       ${MAX_SPEND_USD:.2f}")
    print("Rules: exactly 2 image-generation calls, no edit calls, no video calls, no retries.")
    print("=" * 70)

    if total_cost > MAX_SPEND_USD:
        fail(f"Estimated total cost ${total_cost:.4f} exceeds the ${MAX_SPEND_USD:.2f} cap. Nothing was generated.")

    if not args.yes:
        answer = input(f"\nType 'yes' to spend up to ${total_cost:.4f} and proceed: ").strip().lower()
        if answer != "yes":
            print("Cancelled. Nothing was generated.")
            sys.exit(0)

    manifest = {
        "created_at": _now(),
        "experiment": "cross_angle_continuity_test",
        "model": NANO_BANANA_PRO_GENERATE.model_id,
        "continuity_bible": CONTINUITY_BIBLE,
        "max_spend_usd": MAX_SPEND_USD,
        "estimated_cost_usd": total_cost,
        "images": [],
        "actual_cost_usd": None,
        "completed_at": None,
    }
    save_manifest(manifest)

    dest_1 = OUTPUT_DIR / "angle_1_wide_three_quarter_rear.jpg"
    dest_2 = OUTPUT_DIR / "angle_2_opposite_three_quarter.jpg"

    print(f"\n[generate 1/2] Requesting wide three-quarter-rear view -> {dest_1.name} ...")
    try:
        result_1 = provider.generate_image(request_1, str(dest_1))
    except ImageProviderError as e:
        fail(f"generation of image 1 failed: {e}")
    print(f"               Done -> {dest_1} (${result_1.cost_usd:.4f})")

    manifest["images"].append(
        {
            "label": "angle_1_wide_three_quarter_rear",
            "prompt": IMAGE_1_PROMPT,
            "output_path": str(dest_1),
            "cost_usd": result_1.cost_usd,
        }
    )
    save_manifest(manifest)

    print(f"\n[generate 2/2] Requesting opposite-side three-quarter view -> {dest_2.name} ...")
    try:
        result_2 = provider.generate_image(request_2, str(dest_2))
    except ImageProviderError as e:
        fail(f"generation of image 2 failed: {e}")
    print(f"               Done -> {dest_2} (${result_2.cost_usd:.4f})")

    manifest["images"].append(
        {
            "label": "angle_2_opposite_three_quarter",
            "prompt": IMAGE_2_PROMPT,
            "output_path": str(dest_2),
            "cost_usd": result_2.cost_usd,
        }
    )
    manifest["actual_cost_usd"] = result_1.cost_usd + result_2.cost_usd
    manifest["completed_at"] = _now()
    save_manifest(manifest)

    print("\n" + "=" * 70)
    print("DONE - 2 images generated. No edit or video call was made.")
    print("=" * 70)
    print(f"angle_1_wide_three_quarter_rear: {dest_1}")
    print(f"angle_2_opposite_three_quarter:  {dest_2}")
    print(f"Actual total cost: ${manifest['actual_cost_usd']:.4f}")
    print(f"Manifest: {MANIFEST_PATH}")
    print("\nSTOP HERE. Compare the two images against this checklist:")
    for item in COMPARISON_CHECKLIST:
        print(f"  - {item}")
    print("\nDo not run any video-generation step until you've reviewed and approved")
    print("cross-angle continuity - this script will not regenerate or fix anything automatically.")


if __name__ == "__main__":
    main()
