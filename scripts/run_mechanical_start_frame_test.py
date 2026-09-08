#!/usr/bin/env python3
"""MECHANICAL STILL-IMAGE TEST: can Nano Banana Pro Edit locally correct the
circular-saw physics of the APPROVED composition frame
(data/fal_composition_test/action_base_frame.jpg) without destroying the
composition itself?

This is the next gate after the composition test, not a repeat of V2A.
V2A's mistake was editing an already front-facing image while also asking
for mechanical corrections - this script tests the opposite, narrower
question on a composition that's already correct: can an edit pass fix
ONLY the saw/hand/board mechanics while leaving everything else (camera
angle, body orientation, gaze, posture, cabin, landscape, lighting,
framing, clothing) untouched?

Makes exactly ONE Nano Banana Pro Edit call (NANO_BANANA_PRO_EDIT in
app/providers/image/fal.py - the same capability V2A used, no new adapter
code needed) against the approved composition frame. Produces ONLY a
corrected start frame - no end frame, no video. Success requires BOTH:
  A. Mechanical improvement (base plate flush, blade aligned, plausible
     grip, five fingers per hand, hands clear of the blade path, board
     properly supported).
  B. Preservation of the approved candid composition (camera angle, body
     orientation, downward gaze, posture, cabin, landscape, lighting,
     framing, clothing all unchanged).
A result that improves the saw but breaks the composition is a FAILURE,
not a partial success - this script makes no judgment about that itself;
it produces one image for a human to inspect against both criteria.

Safety, same pattern as every other real-call script in this repo:
  - Exactly 1 image-edit call. No end-frame call, no video call, no loop
    that could ever submit a 2nd of anything.
  - Total cost checked against MAX_SPEND_USD BEFORE the call; one
    "type yes" confirmation gates it.
  - No automatic retries, no automatic regeneration of a bad result.
  - manifest.json records the exact prompt, cost, and output path.

Usage (from the repo root, with FAL_API_KEY set in your .env, AFTER
scripts/run_composition_test.py has already been run and its frame
approved):
    python -m scripts.run_mechanical_start_frame_test
    python -m scripts.run_mechanical_start_frame_test --yes
"""
import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

from app.config import settings
from app.providers.base import ImageEditRequest, ImageProviderError
from app.providers.image.fal import NANO_BANANA_PRO_EDIT, FalImageProvider

MAX_SPEND_USD = 0.20

COMPOSITION_DIR = Path(__file__).resolve().parent.parent / "data" / "fal_composition_test"
COMPOSITION_MANIFEST_PATH = COMPOSITION_DIR / "manifest.json"

OUTPUT_DIR = Path(__file__).resolve().parent.parent / "data" / "fal_mechanical_start_test"
MANIFEST_PATH = OUTPUT_DIR / "manifest.json"

MECHANICAL_CORRECTION_PROMPT = (
    "Make ONLY the following precise mechanical corrections to the circular-saw setup in this "
    "photo; do not change anything else in the image. The saw's base plate must sit flat and "
    "fully seated against the top surface of the timber board, not floating or tilted. The "
    "blade must be aligned with a plausible, visible cut line on the board. The builder's grip "
    "must be realistic: dominant hand naturally on the saw's rear trigger handle, other hand "
    "safely on the front auxiliary handle or clearly clear of the blade path - never overlapping "
    "or merging with the blade, the board, or the other hand. Both hands must be anatomically "
    "correct with exactly five fingers each, no extra, missing, or fused fingers, no distorted "
    "or duplicated hand/tool geometry. The timber board must be fully and stably supported. The "
    "overall spatial relationship between the builder's body, the saw, and the work surface must "
    "read as physically believable - like a real person actually positioned to make this cut.\n\n"
    "Do not change anything else. Preserve exactly as shown: the camera's position and angle "
    "(three-quarter-rear/side observational viewpoint), the builder's body orientation, his "
    "downward gaze toward the saw and cut line (he must not look toward the camera), his overall "
    "working posture and torso lean, the cabin's geometry and construction state, the ocean-cliff "
    "landscape, the golden-hour lighting, the framing and composition, and the builder's clothing "
    "and appearance. Do not turn him toward the viewer. Do not make this look posed or staged."
)

SUCCESS_CRITERIA = [
    "A. MECHANICAL: saw base plate flat/flush on the board",
    "A. MECHANICAL: blade aligned with a plausible cut line",
    "A. MECHANICAL: realistic grip, five fingers per hand, hands clear of the blade path",
    "A. MECHANICAL: board properly supported, believable body/saw/work-surface relationship",
    "B. COMPOSITION: camera position/angle UNCHANGED (three-quarter-rear/side)",
    "B. COMPOSITION: builder orientation and downward gaze UNCHANGED (no eye contact)",
    "B. COMPOSITION: working posture/torso lean UNCHANGED",
    "B. COMPOSITION: cabin geometry, landscape, lighting, framing, clothing UNCHANGED",
    "BOTH A and B must hold - a saw fix that breaks the composition is a FAILURE",
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


def load_approved_composition_frame() -> str:
    """Reads the approved base frame's path out of the composition test's
    own manifest.json, so this can only ever operate on an image that test
    actually produced - never a hard-coded or guessed path."""
    if not COMPOSITION_MANIFEST_PATH.exists():
        fail(
            f"Composition manifest not found at {COMPOSITION_MANIFEST_PATH}. This experiment "
            "requires the approved action_base_frame.jpg - run scripts/run_composition_test.py first."
        )
    composition_manifest = json.loads(COMPOSITION_MANIFEST_PATH.read_text())
    output_path = composition_manifest.get("output_path")
    if not output_path:
        fail(f"Composition manifest at {COMPOSITION_MANIFEST_PATH} has no output_path recorded.")
    image_path = Path(output_path)
    if not image_path.exists() or image_path.stat().st_size == 0:
        fail(f"Approved composition frame not found (or empty) at {image_path}.")
    return str(image_path)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Mechanical still-image test: 1 Nano Banana Pro Edit call to fix saw physics on the approved composition frame, start frame only."
    )
    parser.add_argument("--yes", action="store_true", help="Skip the 'type yes' confirmation prompt")
    args = parser.parse_args()

    key_preview = f"{settings.fal_api_key[:6]}..." if settings.fal_api_key else None
    print(f"FAL_API_KEY loaded from .env: {'yes (' + key_preview + ')' if key_preview else 'NO'}")
    if not settings.fal_api_key:
        fail("FAL_API_KEY is not set. Add FAL_API_KEY=your_key_here to your .env file and try again.")

    base_frame_path = load_approved_composition_frame()
    provider = FalImageProvider(NANO_BANANA_PRO_EDIT)
    cost = provider.estimate_edit_cost()

    print("=" * 70)
    print("MECHANICAL STILL-IMAGE TEST - THIS WILL SPEND REAL MONEY")
    print("=" * 70)
    print(f"Approved composition frame (source, unchanged on disk): {base_frame_path}")
    print(f"\nEdit prompt:\n  {MECHANICAL_CORRECTION_PROMPT}")
    print(f"\nModel: {NANO_BANANA_PRO_EDIT.model_id}")
    print(f"Estimated cost: ${cost:.4f}")
    print(f"Hard cap:       ${MAX_SPEND_USD:.2f}")
    print("Rules: exactly 1 edit call, START FRAME ONLY (no end frame), no video calls, no retries.")
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
        "experiment": "mechanical_start_frame_test",
        "source_composition_frame_path": base_frame_path,
        "reused_from_composition_manifest": str(COMPOSITION_MANIFEST_PATH),
        "model": NANO_BANANA_PRO_EDIT.model_id,
        "prompt": MECHANICAL_CORRECTION_PROMPT,
        "max_spend_usd": MAX_SPEND_USD,
        "estimated_cost_usd": cost,
        "output_path": None,
        "actual_cost_usd": None,
        "completed_at": None,
    }
    save_manifest(manifest)

    dest = OUTPUT_DIR / "mechanical_start_frame.jpg"
    print(f"\n[edit] Correcting saw mechanics on the approved composition frame -> {dest.name} ...")
    try:
        result = provider.edit_image(
            ImageEditRequest(prompt=MECHANICAL_CORRECTION_PROMPT, reference_image_paths=[base_frame_path]), str(dest)
        )
    except ImageProviderError as e:
        fail(f"edit failed: {e}")
    print(f"       Done -> {dest} (${result.cost_usd:.4f})")

    manifest["output_path"] = str(dest)
    manifest["actual_cost_usd"] = result.cost_usd
    manifest["completed_at"] = _now()
    save_manifest(manifest)

    print("\n" + "=" * 70)
    print("DONE - 1 edit made. No end frame, no video call.")
    print("=" * 70)
    print(f"mechanical_start_frame: {dest}")
    print(f"Actual cost: ${result.cost_usd:.4f}")
    print(f"Manifest: {MANIFEST_PATH}")
    print("\nSTOP HERE. Review this image against BOTH success criteria - a saw fix that")
    print("breaks the composition is a FAILURE even if the mechanics improved:")
    for item in SUCCESS_CRITERIA:
        print(f"  - {item}")
    print("\nDo not create an end frame or run any video-generation step until you've")
    print("reviewed and approved this start frame - this script will not regenerate it")
    print("automatically.")


if __name__ == "__main__":
    main()
