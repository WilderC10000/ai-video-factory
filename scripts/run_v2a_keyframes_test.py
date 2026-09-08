#!/usr/bin/env python3
"""ATOMIC-ACTION EXPERIMENT V2A: prove we can create MECHANICALLY CORRECT
circular-saw start/end keyframes, before spending anything on animating
them (that's V2B, a separate, later, human-gated step).

V2A does NOT generate video. It does NOT call Wan FLF2V or Kling O1. It
makes exactly 2 image-EDIT calls (Nano Banana Pro Edit -
NANO_BANANA_PRO_EDIT in app/providers/image/fal.py) against the existing
bake-off reference image, producing two candidate keyframes:

    saw_start_frame.jpg - blade at/just beginning the cut
    saw_end_frame.jpg   - same physical setup, cut visibly progressed

The objective is mechanical believability, not prettiness: correct timber
support, correct saw base-plate contact, blade aligned with the cut,
plausible hand grip and stance, no extra/fused fingers, everything else
(builder identity, cabin, landscape, lighting, board) held unchanged. A
human (you) inspects both images after this script exits and decides
whether they're good enough to animate - this script does not make that
call, and does not proceed to any video generation regardless of outcome.

Design choice, stated explicitly so it's easy to override: the end frame
is edited FROM the start frame's own output (not independently from the
original bake-off image), so the two keyframes share one continuous
physical configuration rather than two separately-invented ones - the same
"propagate forward, don't reinvent" principle already used for last-frame
propagation elsewhere in this project. Both edits still only cost $0.15
each; chaining doesn't add a paid call.

Safety, same pattern as every other real-call script in this repo:
  - Exactly 2 image-edit calls. Zero video calls. No loop that could ever
    submit a 3rd image edit or any video generation.
  - Total cost checked against MAX_SPEND_USD BEFORE any call; one
    "type yes" confirmation gates the whole run.
  - No automatic retries - any failure (including "the model produced
    something clearly wrong") stops the script immediately. This script
    NEVER auto-regenerates a bad frame - per instruction, a bad frame
    means you stop and decide next steps, not that the script retries.
  - manifest.json records both edits' exact prompt, cost, and output path.

Usage (from the repo root, with FAL_API_KEY set in your .env, AFTER
scripts/run_bakeoff_test.py has already been run at least once so its
reference image and manifest exist):
    python -m scripts.run_v2a_keyframes_test
    python -m scripts.run_v2a_keyframes_test --yes
"""
import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

from app.config import settings
from app.providers.base import ImageEditRequest, ImageProviderError
from app.providers.image.fal import NANO_BANANA_PRO_EDIT, FalImageProvider

MAX_SPEND_USD = 0.35

BAKEOFF_DIR = Path(__file__).resolve().parent.parent / "data" / "fal_bakeoff_test"
BAKEOFF_MANIFEST_PATH = BAKEOFF_DIR / "manifest.json"

OUTPUT_DIR = Path(__file__).resolve().parent.parent / "data" / "fal_v2a_keyframes_test"
MANIFEST_PATH = OUTPUT_DIR / "manifest.json"

# Shared correctness checklist embedded in both prompts, worded as edit
# instructions (Nano Banana Pro Edit takes a prompt + existing image(s), not
# a from-scratch description) - kept identical between the two calls except
# for what physically differs (cut not started vs. cut progressed).
_UNCHANGED_CLAUSE = (
    "Keep the builder's face, hair, beard, clothing, and body build exactly as shown. Keep the "
    "cabin's existing floor platform and partial wall framing, the ocean-cliff landscape, the "
    "golden-hour lighting, and the board's size and position exactly as shown. Keep the vertical "
    "9:16 composition."
)

START_FRAME_PROMPT = (
    "Edit this photo to correct the circular-saw cutting setup so it is mechanically believable, "
    "changing as little else as possible. The timber board must be fully and stably supported "
    "across the sawhorses. The circular saw's base plate must sit flat and flush against the top "
    "surface of the board, with the blade guard visible and the blade aligned exactly along the "
    "intended cut line, just beginning to touch the wood (the cut has not started yet - no kerf, "
    "no sawdust). The builder's dominant hand grips the saw's rear trigger handle naturally, "
    "finger on or near the trigger; his other hand is positioned safely on the saw's front "
    "auxiliary handle or well clear of the blade path - never overlapping or merging with the "
    "blade or the board. His stance is a plausible, grounded working posture with realistic "
    "weight distribution, both feet visible and correctly placed, exactly five fingers per hand, "
    "no extra or fused fingers, no distorted or duplicated hand/tool geometry. " + _UNCHANGED_CLAUSE
)

END_FRAME_PROMPT = (
    "Edit this photo to show the same circular-saw cut, but with the cut now visibly progressed "
    "partway through the timber board, changing as little else as possible. The saw's base plate "
    "remains flat and flush against the board, blade still aligned along the same cut line, now "
    "partway into the wood with a visible kerf (cut slot) and a light scatter of fresh sawdust on "
    "and around the board. The builder's hand positions, grip, and stance must match exactly - "
    "dominant hand on the trigger handle, other hand safely on the front handle or clear of the "
    "blade path, exactly five fingers per hand, no extra or fused fingers, no distorted or "
    "duplicated hand/tool geometry. " + _UNCHANGED_CLAUSE
)


def fail(message: str) -> None:
    print(f"\nSTOPPED: {message}")
    print(f"No retry, no further generation - the script is exiting now. Manifest: {MANIFEST_PATH}")
    sys.exit(1)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def save_manifest(manifest: dict) -> None:
    MANIFEST_PATH.parent.mkdir(parents=True, exist_ok=True)
    MANIFEST_PATH.write_text(json.dumps(manifest, indent=2))


def load_reused_reference_image() -> str:
    """Same manifest-driven reuse pattern as run_atomic_cut_test.py - reads
    the path out of the bake-off's own manifest.json rather than hard-coding
    it, so this can only reuse an image a real bake-off run actually
    produced."""
    if not BAKEOFF_MANIFEST_PATH.exists():
        fail(
            f"Bake-off manifest not found at {BAKEOFF_MANIFEST_PATH}. This experiment reuses "
            "its reference image - run scripts/run_bakeoff_test.py first."
        )
    bakeoff_manifest = json.loads(BAKEOFF_MANIFEST_PATH.read_text())
    ref = bakeoff_manifest.get("reference_image")
    if not ref or not ref.get("image_path"):
        fail(f"Bake-off manifest at {BAKEOFF_MANIFEST_PATH} has no reference_image recorded.")
    image_path = Path(ref["image_path"])
    if not image_path.exists() or image_path.stat().st_size == 0:
        fail(f"Reused reference image not found (or empty) at {image_path}.")
    return str(image_path)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="V2A: 2 Nano Banana Pro Edit calls to produce mechanically-correct saw start/end keyframes."
    )
    parser.add_argument("--yes", action="store_true", help="Skip the 'type yes' confirmation prompt")
    args = parser.parse_args()

    key_preview = f"{settings.fal_api_key[:6]}..." if settings.fal_api_key else None
    print(f"FAL_API_KEY loaded from .env: {'yes (' + key_preview + ')' if key_preview else 'NO'}")
    if not settings.fal_api_key:
        fail("FAL_API_KEY is not set. Add FAL_API_KEY=your_key_here to your .env file and try again.")

    image_path = load_reused_reference_image()
    provider = FalImageProvider(NANO_BANANA_PRO_EDIT)
    per_call_cost = provider.estimate_edit_cost()
    total_cost = round(per_call_cost * 2, 4)

    print("=" * 70)
    print("V2A: SAW START/END KEYFRAME EXPERIMENT - THIS WILL SPEND REAL MONEY")
    print("=" * 70)
    print(f"Base reference image (bake-off, reused): {image_path}")
    print(f"\nStart-frame edit prompt:\n  {START_FRAME_PROMPT}")
    print(f"\nEnd-frame edit prompt (applied to the start frame's own output):\n  {END_FRAME_PROMPT}")
    print(f"\nModel: {NANO_BANANA_PRO_EDIT.model_id}  (${per_call_cost:.4f}/image, standard resolution, num_images=1)")
    print(f"Estimated cost: 2 x ${per_call_cost:.4f} = ${total_cost:.4f}")
    print(f"Hard cap:       ${MAX_SPEND_USD:.2f}")
    print("Rules: exactly 2 image-edit calls, zero video calls, no retries, no auto-regeneration of a bad frame.")
    print("=" * 70)

    if total_cost > MAX_SPEND_USD:
        fail(f"Estimated cost ${total_cost:.4f} exceeds the ${MAX_SPEND_USD:.2f} cap. Nothing was generated.")

    if not args.yes:
        answer = input(f"\nType 'yes' to spend up to ${total_cost:.4f} and proceed: ").strip().lower()
        if answer != "yes":
            print("Cancelled. Nothing was generated.")
            sys.exit(0)

    manifest = {
        "created_at": _now(),
        "experiment": "v2a_saw_keyframes",
        "base_reference_image_path": image_path,
        "reused_from_bakeoff_manifest": str(BAKEOFF_MANIFEST_PATH),
        "model": NANO_BANANA_PRO_EDIT.model_id,
        "max_spend_usd": MAX_SPEND_USD,
        "estimated_total_cost_usd": total_cost,
        "frames": [],
        "actual_total_cost_usd": None,
    }
    save_manifest(manifest)

    # --- Start frame: edited from the base bake-off reference image --------
    start_path = OUTPUT_DIR / "saw_start_frame.jpg"
    print(f"\n[start] Editing base reference image -> {start_path.name} ...")
    try:
        start_result = provider.edit_image(
            ImageEditRequest(prompt=START_FRAME_PROMPT, reference_image_paths=[image_path]), str(start_path)
        )
    except ImageProviderError as e:
        fail(f"start frame edit failed: {e}")
    print(f"        Done -> {start_path} (${start_result.cost_usd:.4f})")
    manifest["frames"].append(
        {
            "label": "saw_start_frame",
            "prompt": START_FRAME_PROMPT,
            "source_image_path": image_path,
            "output_path": str(start_path),
            "cost_usd": start_result.cost_usd,
            "completed_at": _now(),
        }
    )
    save_manifest(manifest)

    # --- End frame: edited from the start frame's own output, not the base -
    end_path = OUTPUT_DIR / "saw_end_frame.jpg"
    print(f"\n[end]   Editing start frame -> {end_path.name} ...")
    try:
        end_result = provider.edit_image(
            ImageEditRequest(prompt=END_FRAME_PROMPT, reference_image_paths=[str(start_path)]), str(end_path)
        )
    except ImageProviderError as e:
        fail(f"end frame edit failed: {e}")
    print(f"        Done -> {end_path} (${end_result.cost_usd:.4f})")
    manifest["frames"].append(
        {
            "label": "saw_end_frame",
            "prompt": END_FRAME_PROMPT,
            "source_image_path": str(start_path),
            "output_path": str(end_path),
            "cost_usd": end_result.cost_usd,
            "completed_at": _now(),
        }
    )

    actual_total = round(sum(f["cost_usd"] for f in manifest["frames"]), 4)
    manifest["actual_total_cost_usd"] = actual_total
    save_manifest(manifest)

    print("\n" + "=" * 70)
    print("DONE - 2 image edits only. No video was generated.")
    print("=" * 70)
    print(f"saw_start_frame: {start_path}")
    print(f"saw_end_frame:   {end_path}")
    print(f"Total actual cost: ${actual_total:.4f}")
    print(f"Full manifest: {MANIFEST_PATH}")
    print("\nSTOP HERE. Inspect both images by eye against the mechanical-correctness checklist")
    print("(saw base plate flat on the board, blade aligned with the cut, believable grip and")
    print("stance, exactly five fingers per hand, no merged hand/tool geometry). Do not run any")
    print("V2B video-generation step until you've reviewed and approved these frames - if either")
    print("is physically wrong, this script will not fix or regenerate it automatically.")


if __name__ == "__main__":
    main()
