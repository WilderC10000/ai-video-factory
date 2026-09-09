#!/usr/bin/env python3
"""Segment 1A START-FRAME CANDIDATE V2: composition-only regeneration.

The original segment_1a_start_frame.jpg was rejected on review: the camera
was pitched too far downward, so foreground ground/vegetation dominated the
vertical frame while the dramatic ocean/cliff environment was compressed
into the upper background. FORMA's visual identity requires the dramatic
environment to be a major retention element alongside the transformation,
not a background afterthought - so this needed a real composition fix, not
a minor tweak.

This script changes ONLY the camera/composition clause. Everything else
that was never in question - builder identity/clothing, site geometry,
golden-hour lighting, the boulder/access-path landmarks, and the S0
"completely untouched" construction state - is imported directly from
scripts/run_full_video_segment_1a_test.py (SITE_BIBLE,
SEGMENT_1A_START_STATE_S0), not retyped, so it is byte-identical to the
original and cannot silently drift.

New composition (replaces the old wide-environmental-but-downward-pitched
clause): camera at approximately human chest/eye height, near-horizontal
axis (not elevated and angled down), horizon clearly visible, ~40-50% of
the frame's upper portion showcasing the ocean/horizon/coastline, the
builder occupying a smaller share of the frame than before, foreground
worksite/vegetation still clearly visible, and explicit front-to-back
depth (worksite -> builder -> cliff/coast -> ocean/horizon).

Makes exactly ONE Nano Banana Pro Generate call ($0.15, text-to-image, no
source image - same mechanism as scripts/run_composition_test.py). Saves
to a NEW candidate path - segment_1a_start_frame_v2_candidate.jpg - and
does NOT touch or overwrite the original (rejected) segment_1a_start_
frame.jpg. Writes its own separate manifest
(candidate_v2_manifest.json) rather than modifying the segment's main
manifest.json, since that file's video_path/video_cost_usd fields track
the segment's one official, eventually-approved image - not a rejected
candidate or an under-review one.

No video call is made here. This script stops after the one image so it
can be manually reviewed against the new composition requirements before
any further spend.

Safety, same pattern as every other real-call script in this repo:
  - Exactly 1 image-generation call. No loop, no retry, no other API call.
  - Hard cap set exactly equal to the computed cost ($0.15) - zero margin.
  - A single "type yes" confirmation gates the one call.

Usage (from the repo root, with FAL_API_KEY set in your .env):
    python -m scripts.run_full_video_segment_1a_image_v2_test
    python -m scripts.run_full_video_segment_1a_image_v2_test --yes
"""
import json
import sys
from datetime import datetime, timezone

from app.config import settings
from app.providers.base import ImageGenerationRequest, ImageProviderError
from app.providers.image.fal import NANO_BANANA_PRO_GENERATE, FalImageProvider
from scripts.run_full_video_segment_1a_test import OUTPUT_DIR, SEGMENT_1A_START_STATE_S0, SITE_BIBLE

MAX_SPEND_USD = 0.15

CANDIDATE_IMAGE_PATH = OUTPUT_DIR / "segment_1a_start_frame_v2_candidate.jpg"
CANDIDATE_MANIFEST_PATH = OUTPUT_DIR / "candidate_v2_manifest.json"

# Replaces the original (rejected) wide-environmental-but-downward-pitched
# camera clause. Every requirement from the rejection feedback is encoded
# explicitly rather than left implicit, since composition is exactly what
# failed last time.
CAMERA_ESTABLISHING_V2 = (
    "Camera view: a wide environmental establishing shot taken from approximately human chest/eye "
    "height, with the camera axis close to horizontal rather than elevated and angled downward. "
    "The horizon is clearly visible. Roughly the upper 40-50% of the frame showcases the dramatic "
    "coastal landscape - open ocean, horizon, sky, and, where composition permits, glimpses of "
    "distant coastline or cliff geography rather than only open water. The remaining lower portion "
    "of the frame contains the builder and the untouched worksite, with enough foreground ground "
    "and vegetation visible to clearly read as material that will be cleared; the builder occupies "
    "a noticeably smaller portion of the frame than in a close or elevated shot, positioned further "
    "back within the scene rather than filling it. The composition shows clear depth from front to "
    "back: foreground worksite, then the builder, then the cliff edge and coastline, then the ocean "
    "and horizon beyond. Candid, fixed-camera construction-documentary feeling, not a posed or hero "
    "composition."
)

BUILDER_ACTION_V2 = (
    "The builder stands within this wide view, naturally preparing a brush-cutter, his attention "
    "and gaze directed toward the vegetation and work area ahead of him - not toward the camera. "
    "No eye contact, no portrait pose, no presenter stance."
)

IMAGE_PROMPT_V2 = f"{SITE_BIBLE} {SEGMENT_1A_START_STATE_S0} {CAMERA_ESTABLISHING_V2} {BUILDER_ACTION_V2}"


def fail(message: str) -> None:
    print(f"\nSTOPPED: {message}")
    print(f"No retry, no further generation - the script is exiting now. Manifest: {CANDIDATE_MANIFEST_PATH}")
    sys.exit(1)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def save_manifest(manifest: dict) -> None:
    CANDIDATE_MANIFEST_PATH.parent.mkdir(parents=True, exist_ok=True)
    CANDIDATE_MANIFEST_PATH.write_text(json.dumps(manifest, indent=2))


def main() -> None:
    skip_confirm = "--yes" in sys.argv[1:]

    key_preview = f"{settings.fal_api_key[:6]}..." if settings.fal_api_key else None
    print(f"FAL_API_KEY loaded from .env: {'yes (' + key_preview + ')' if key_preview else 'NO'}")
    if not settings.fal_api_key:
        fail("FAL_API_KEY is not set. Add FAL_API_KEY=your_key_here to your .env file and try again.")

    provider = FalImageProvider(NANO_BANANA_PRO_GENERATE)
    request = ImageGenerationRequest(
        prompt=IMAGE_PROMPT_V2, extra_params={"aspect_ratio": "9:16", "resolution": "1K"}
    )
    cost = provider.estimate_cost(request)

    print("=" * 70)
    print("SEGMENT 1A START-FRAME CANDIDATE V2 - THIS WILL SPEND REAL MONEY")
    print("=" * 70)
    print(f"Model: {NANO_BANANA_PRO_GENERATE.model_id}  (text-to-image, no source image)")
    print("Original segment_1a_start_frame.jpg is NOT touched or overwritten by this run.")
    print(f"\nPrompt:\n  {IMAGE_PROMPT_V2}")
    print(f"\nEstimated cost: ${cost:.4f}")
    print(f"Hard cap:       ${MAX_SPEND_USD:.2f}")
    print("Rules: exactly 1 image call, no video call, no retries, no other segment.")
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
        "experiment": "full_video_segment_1a_start_frame_v2_candidate",
        "segment_id": "1A",
        "image_model": NANO_BANANA_PRO_GENERATE.model_id,
        "image_prompt": IMAGE_PROMPT_V2,
        "max_spend_usd": MAX_SPEND_USD,
        "estimated_cost_usd": cost,
        "image_path": None,
        "actual_cost_usd": None,
        "completed_at": None,
        "rejected_original_image_path": str(OUTPUT_DIR / "segment_1a_start_frame.jpg"),
        "rejection_reason": (
            "Camera pitched too far downward; foreground ground/vegetation dominated the frame "
            "while the ocean/cliff environment was compressed into the upper background."
        ),
    }
    save_manifest(manifest)

    print(f"\n[generate] Requesting segment 1A start-frame candidate V2 -> {CANDIDATE_IMAGE_PATH.name} ...")
    try:
        result = provider.generate_image(request, str(CANDIDATE_IMAGE_PATH))
    except ImageProviderError as e:
        fail(f"generation failed: {e}")
    print(f"           Done -> {CANDIDATE_IMAGE_PATH} (${result.cost_usd:.4f})")

    manifest["image_path"] = str(CANDIDATE_IMAGE_PATH)
    manifest["actual_cost_usd"] = result.cost_usd
    manifest["completed_at"] = _now()
    save_manifest(manifest)

    print("\n" + "=" * 70)
    print("DONE - 1 candidate image generated. No video call was made.")
    print("=" * 70)
    print(f"Candidate image: {CANDIDATE_IMAGE_PATH}")
    print(f"Actual cost: ${result.cost_usd:.4f}")
    print(f"Manifest: {CANDIDATE_MANIFEST_PATH}")
    print("\nSTOP HERE. Review this candidate against the new composition requirements:")
    print("  - camera at roughly chest/eye height, near-horizontal axis (not downward-pitched)")
    print("  - horizon clearly visible")
    print("  - ~40-50% of frame shows ocean/horizon/sky/coastline")
    print("  - builder occupies noticeably less of the frame than the rejected image")
    print("  - foreground worksite/vegetation still clearly visible")
    print("  - clear depth: foreground worksite -> builder -> cliff/coast -> ocean/horizon")
    print("  - builder facing/looking toward the work area, not the camera; no posing")
    print("\nDo not generate any video until this candidate (or a further revision) is approved.")


if __name__ == "__main__":
    main()
