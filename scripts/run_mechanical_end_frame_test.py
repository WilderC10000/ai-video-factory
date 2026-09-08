#!/usr/bin/env python3
"""MECHANICAL END-FRAME TEST: create ONE mechanically plausible END keyframe
from the already-approved `mechanical_start_frame.jpg`, showing the same
continuous circular-saw cut progressed further along - NOT a new action,
NOT board separation, NOT a camera/composition change.

This is the narrowest possible next gate: can Nano Banana Pro Edit produce
a second frame that is (a) visibly further along the same cut and (b)
still the same scene, camera, builder, and board as the approved start
frame? Success here means we'd have two visually consistent, mechanically
plausible ENDPOINTS of the same physical action - the actual prerequisite
for a first/last-frame video-interpolation test (a separate, later,
explicitly gated experiment - NOT this script).

Deliberately narrow, per instruction: the board stays rigid and fully
supported throughout - no cutting-through, no separation, no sagging waste
side. That failure mode (rigid-body break-apart) is intentionally deferred
to its own future atomic-action test, not conflated with this one. This
script does not animate anything and does not call any video endpoint.

Makes exactly ONE Nano Banana Pro Edit call (NANO_BANANA_PRO_EDIT in
app/providers/image/fal.py - same capability the start-frame test used,
no new adapter code needed) against the approved mechanical start frame.

Safety, same pattern as every other real-call script in this repo:
  - Exactly 1 image-edit call. No video call, no loop that could ever
    submit a 2nd of anything.
  - Total cost checked against MAX_SPEND_USD BEFORE the call; one
    "type yes" confirmation gates it.
  - No automatic retries, no automatic regeneration of a bad result.
  - manifest.json records the exact prompt, cost, and output path.

Usage (from the repo root, with FAL_API_KEY set in your .env, AFTER
scripts/run_mechanical_start_frame_test.py has already been run and its
frame approved):
    python -m scripts.run_mechanical_end_frame_test
    python -m scripts.run_mechanical_end_frame_test --yes
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

START_FRAME_DIR = Path(__file__).resolve().parent.parent / "data" / "fal_mechanical_start_test"
START_FRAME_MANIFEST_PATH = START_FRAME_DIR / "manifest.json"

OUTPUT_DIR = Path(__file__).resolve().parent.parent / "data" / "fal_mechanical_end_test"
MANIFEST_PATH = OUTPUT_DIR / "manifest.json"

END_FRAME_PROMPT = (
    "Edit this photo to show the same continuous circular-saw cut progressed further along the "
    "same cut path, approximately 40-60% further than shown, changing as little else as "
    "possible. The saw has physically advanced along the same cut line; the blade remains "
    "aligned with that same cut, and the base plate remains flat and fully seated against the "
    "timber board. The builder's arms and hands may shift only as naturally required to have "
    "advanced the saw this far - grip, stance, and body position otherwise match the start "
    "frame. A visible kerf and light natural sawdust around the active cut should make the "
    "progression obvious. The timber board remains rigid, fully supported, and exactly the same "
    "size and position as shown - it has NOT been cut through, broken apart, separated, or "
    "changed in shape or dimensions in any way. Do not introduce any second action, do not "
    "change or add any tool, do not turn the builder toward the camera, do not move the camera "
    "or change the framing, do not redesign the scene, and do not add cinematic lighting or "
    "camera effects.\n\n"
    "Preserve exactly as shown: the camera's position and angle (three-quarter-rear/side "
    "observational viewpoint), the builder's body orientation, his downward gaze toward the saw "
    "and cut line (he must not look toward the camera), his overall working posture, the "
    "builder's identity, clothing, and appearance, the saw's identity and appearance, the "
    "cabin's geometry and construction state, the ocean-cliff landscape, the golden-hour "
    "lighting, and the framing and composition."
)

SUCCESS_CRITERIA = [
    "PROGRESSION: cut visibly ~40-60% further along than the start frame",
    "PROGRESSION: saw/blade advanced along the SAME cut line, base plate still seated",
    "PROGRESSION: visible kerf and natural sawdust make the progression obvious",
    "RIGIDITY: board is rigid, fully supported, unchanged size/shape - NOT cut through or separated",
    "RIGIDITY: no sagging, no waste-side movement, no break-apart",
    "UNCHANGED: camera position/angle, framing, composition",
    "UNCHANGED: builder orientation, downward gaze (no eye contact), posture",
    "UNCHANGED: builder identity/clothing, saw identity/appearance",
    "UNCHANGED: cabin geometry, landscape, lighting",
    "NO new action, no tool change, no cinematic effects, no scene redesign",
    "BOTH progression AND preservation must hold - either failing alone is a FAILURE",
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


def load_approved_mechanical_start_frame() -> str:
    """Reads the approved start frame's path out of the mechanical
    start-frame test's own manifest.json, so this can only ever operate on
    an image that test actually produced - never a hard-coded or guessed
    path."""
    if not START_FRAME_MANIFEST_PATH.exists():
        fail(
            f"Mechanical start-frame manifest not found at {START_FRAME_MANIFEST_PATH}. This "
            "experiment requires the approved mechanical_start_frame.jpg - run "
            "scripts/run_mechanical_start_frame_test.py first."
        )
    start_manifest = json.loads(START_FRAME_MANIFEST_PATH.read_text())
    output_path = start_manifest.get("output_path")
    if not output_path:
        fail(f"Manifest at {START_FRAME_MANIFEST_PATH} has no output_path recorded.")
    image_path = Path(output_path)
    if not image_path.exists() or image_path.stat().st_size == 0:
        fail(f"Approved mechanical start frame not found (or empty) at {image_path}.")
    return str(image_path)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Mechanical end-frame test: 1 Nano Banana Pro Edit call to progress the cut on the approved start frame."
    )
    parser.add_argument("--yes", action="store_true", help="Skip the 'type yes' confirmation prompt")
    args = parser.parse_args()

    key_preview = f"{settings.fal_api_key[:6]}..." if settings.fal_api_key else None
    print(f"FAL_API_KEY loaded from .env: {'yes (' + key_preview + ')' if key_preview else 'NO'}")
    if not settings.fal_api_key:
        fail("FAL_API_KEY is not set. Add FAL_API_KEY=your_key_here to your .env file and try again.")

    start_frame_path = load_approved_mechanical_start_frame()
    provider = FalImageProvider(NANO_BANANA_PRO_EDIT)
    cost = provider.estimate_edit_cost()

    print("=" * 70)
    print("MECHANICAL END-FRAME TEST - THIS WILL SPEND REAL MONEY")
    print("=" * 70)
    print(f"Approved mechanical start frame (source, unchanged on disk): {start_frame_path}")
    print(f"\nEdit prompt:\n  {END_FRAME_PROMPT}")
    print(f"\nModel: {NANO_BANANA_PRO_EDIT.model_id}")
    print(f"Estimated cost: ${cost:.4f}")
    print(f"Hard cap:       ${MAX_SPEND_USD:.2f}")
    print("Rules: exactly 1 edit call, no video calls, no retries.")
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
        "experiment": "mechanical_end_frame_test",
        "source_start_frame_path": start_frame_path,
        "reused_from_start_frame_manifest": str(START_FRAME_MANIFEST_PATH),
        "model": NANO_BANANA_PRO_EDIT.model_id,
        "prompt": END_FRAME_PROMPT,
        "max_spend_usd": MAX_SPEND_USD,
        "estimated_cost_usd": cost,
        "output_path": None,
        "actual_cost_usd": None,
        "completed_at": None,
    }
    save_manifest(manifest)

    dest = OUTPUT_DIR / "mechanical_end_frame.jpg"
    print(f"\n[edit] Progressing the cut on the approved start frame -> {dest.name} ...")
    try:
        result = provider.edit_image(
            ImageEditRequest(prompt=END_FRAME_PROMPT, reference_image_paths=[start_frame_path]), str(dest)
        )
    except ImageProviderError as e:
        fail(f"edit failed: {e}")
    print(f"       Done -> {dest} (${result.cost_usd:.4f})")

    manifest["output_path"] = str(dest)
    manifest["actual_cost_usd"] = result.cost_usd
    manifest["completed_at"] = _now()
    save_manifest(manifest)

    print("\n" + "=" * 70)
    print("DONE - 1 edit made. No video call.")
    print("=" * 70)
    print(f"mechanical_end_frame: {dest}")
    print(f"Actual cost: ${result.cost_usd:.4f}")
    print(f"Manifest: {MANIFEST_PATH}")
    print("\nSTOP HERE. Review this image against ALL criteria - progression alone or")
    print("preservation alone is not enough, both must hold:")
    for item in SUCCESS_CRITERIA:
        print(f"  - {item}")
    print("\nDo not design or run any video-interpolation step until you've reviewed and")
    print("approved this end frame alongside the start frame - this script will not")
    print("regenerate it automatically.")


if __name__ == "__main__":
    main()
