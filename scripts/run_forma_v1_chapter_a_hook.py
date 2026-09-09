#!/usr/bin/env python3
"""FORMA VIDEO #1 - CHAPTER A, STAGE A1: HOOK.

First paid generation of FORMA Video #1 ("Waterfall Cave -> Glass
Hideaway") - the R&D phase (cliff-cabin segments 1A/1B/2/3 and Validation
Tests #1-3) is complete; this begins the actual production.

This is STAGE A1 ONLY. It makes exactly one Wan 3.0 video call (the Hook)
and then STOPS COMPLETELY - it does not extract a frame, does not
generate Site Prep Clip 1, and does not touch scripts/run_forma_v1_chapter_a_prep1.py
in any way. Per explicit instruction, Chapter A is deliberately NOT one
command that performs all three paid Wan calls automatically - a failed
or unapproved Hook must never be able to trigger a downstream paid
generation. Stage A2 (Prep 1) is a completely separate script, run only
after you have reviewed this stage's output and approved it yourself.

The starting image is YOUR OWN approved waterfall-cave reference photo,
placed at REFERENCE_IMAGE_PATH below - used directly, unmodified. No
Nano Banana Pro call of any kind happens in this stage. Per explicit
instruction, that photo (both the builder shown in it and the cave/
waterfall/rock/vegetation/composition/lighting) is now AUTHORITATIVE -
the written LOCATION_BIBLE/CAMERA_CLAUSE_A text below is a best-effort
description meant to match what's already in the photo, not a directive
to reshape it. No identity-correction edit is performed.

Per explicit instruction, this prompt is VISUAL-ONLY - no audio
instructions of any kind (no waterfall/wind/footsteps/tools/birds/
dialogue/narration/music language). Wan is run with no audio field
regardless; FORMA's sound design is an entirely separate, later
post-production layer (see the README's "Sound plan" notes).

LOCATION_BIBLE and CAMERA_CLAUSE_A defined here are the shared,
byte-identical text every later Chapter A script (Prep 1, Prep 2) imports
- this module is the single source of truth for both, the same pattern
used throughout the cliff-cabin production (e.g. segment 1A's SITE_BIBLE).

Safety, same pattern as every other real-call script in this repo:
  - Exactly 1 video-generation call. No image call, no retry, no chaining
    to any other stage.
  - Hard cap set exactly equal to the computed cost ($0.20) - zero
    margin, since Wan 3.0's per-second billing is exactly precomputable.
  - Job state saved to disk immediately after submission, before polling
    starts, so scripts/recover_fal_video_job.py can recover it.

Usage (from the repo root, with FAL_API_KEY set in your .env, and your
approved reference photo placed at REFERENCE_IMAGE_PATH):
    python -m scripts.run_forma_v1_chapter_a_hook
    python -m scripts.run_forma_v1_chapter_a_hook --yes
"""
import dataclasses
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

from app.config import settings
from app.providers.base import ProviderJobState, VideoGenerationRequest, VideoProviderError
from app.providers.video.fal import WAN_3_0_STANDARD, FalVideoProvider

MAX_SPEND_USD = 0.20  # video only - no image-generation call of any kind
RESOLUTION = "480p"
ASPECT_RATIO = "9:16"
DURATION_SECONDS = 4.0
POLL_INTERVAL_SECONDS = 3
MAX_WAIT_SECONDS = 300  # 5 minutes; see the timeout message below if this is hit

REPO_ROOT = Path(__file__).resolve().parent.parent
OUTPUT_DIR = REPO_ROOT / "data" / "forma_video_1_chapter_a"

# YOUR approved reference photo - placed here manually, used directly,
# never regenerated or modified by this script.
REFERENCE_IMAGE_PATH = OUTPUT_DIR / "canonical_reference_start_frame.jpg"

HOOK_RAW_PATH = OUTPUT_DIR / "hook_raw.mp4"
MANIFEST_PATH = OUTPUT_DIR / "manifest.json"
JOB_STATE_PATH = OUTPUT_DIR / "hook_last_job.json"

# Shared bible - imported unchanged by Stage A2/A3. Describes what the
# approved reference photo already shows; the photo's own pixels are
# authoritative, this text just needs to not contradict them.
LOCATION_BIBLE = (
    "A rugged male builder in his mid-40s, with slightly messy dark brown hair, a short dark "
    "beard/stubble, and a medium athletic build, wearing worn faded blue-grey jeans, a plain "
    "heather-grey crew-neck work shirt with no visible logo or branding, and brown leather work "
    "boots, at a site beneath a large natural rock overhang/shallow cave. A powerful waterfall "
    "crashes down just beside the cave mouth into a pool below, throwing visible mist into the "
    "air. Wet dark rock, moss, and ferns cling to the cave walls and surrounding terrain; a "
    "dramatic forested landscape recedes into the distance beyond the falls. Warm natural "
    "daylight, mist catching the light. Candid documentary/observational photography style, "
    "vertical 9:16."
)

# Fixed for the whole of Camera Chapter A (Hook + both Site Prep clips) -
# one camera angle, no movement, per the Camera Chapters rule.
CAMERA_CLAUSE_A = (
    "Camera view: a wide environmental establishing shot at approximately human chest/eye "
    "height, near-horizontal axis, taking in the full scale of the cave, the waterfall, and the "
    "surrounding landscape together, with the site occupying the foreground. Fixed camera "
    "position, no movement, no angle change."
)

# Visual-only - no audio instructions of any kind, per explicit instruction.
HOOK_PROMPT = (
    "Vertical 9:16, realistic documentary-style footage, near real-time pace - not a "
    f"time-lapse. {CAMERA_CLAUSE_A}\n\n"
    "The site is completely untouched - no structure, no materials, no construction of any "
    "kind. The builder is present at the edge of the site, setting down a tool and beginning to "
    "survey the ground ahead of him - he never looks toward the camera. The waterfall continues "
    "crashing down beside the cave with constant visible motion; mist drifts through the air; "
    "moss and ferns move slightly in the breeze. No posing, no presenter behavior, no "
    "commercial aesthetic."
)

# Local duration variant - does NOT mutate the shared module-level
# WAN_3_0_STANDARD or any cliff-cabin segment/test's own variant.
WAN_3_0_FORMA_V1_HOOK = dataclasses.replace(WAN_3_0_STANDARD, extra_payload={"duration": 4})


def fail(message: str) -> None:
    print(f"\nSTOPPED: {message}")
    print("No retry, no further generation - the script is exiting now.")
    sys.exit(1)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def load_manifest() -> dict:
    if MANIFEST_PATH.exists():
        return json.loads(MANIFEST_PATH.read_text())
    return {"experiment": "forma_video_1_chapter_a", "created_at": _now()}


def save_manifest(manifest: dict) -> None:
    MANIFEST_PATH.parent.mkdir(parents=True, exist_ok=True)
    MANIFEST_PATH.write_text(json.dumps(manifest, indent=2))


def main() -> None:
    skip_confirm = "--yes" in sys.argv[1:]

    key_preview = f"{settings.fal_api_key[:6]}..." if settings.fal_api_key else None
    print(f"FAL_API_KEY loaded from .env: {'yes (' + key_preview + ')' if key_preview else 'NO'}")
    if not settings.fal_api_key:
        fail("FAL_API_KEY is not set. Add FAL_API_KEY=your_key_here to your .env file and try again.")

    if not REFERENCE_IMAGE_PATH.exists():
        fail(
            f"Your approved reference photo was not found at {REFERENCE_IMAGE_PATH}. "
            "Place it there before running this stage - it is used directly as the Hook's "
            "starting image and is never generated or modified by this script."
        )

    video_provider = FalVideoProvider(WAN_3_0_FORMA_V1_HOOK)
    video_request = VideoGenerationRequest(
        prompt=HOOK_PROMPT,
        reference_image_path=str(REFERENCE_IMAGE_PATH),
        aspect_ratio=ASPECT_RATIO,
        duration_seconds=DURATION_SECONDS,
        extra_params={"resolution": RESOLUTION},
    )
    video_cost = video_provider.estimate_cost(video_request)

    print("=" * 70)
    print("FORMA VIDEO #1 - CHAPTER A - STAGE A1 (HOOK) - THIS WILL SPEND REAL MONEY")
    print("=" * 70)
    print(f"Video model: {WAN_3_0_FORMA_V1_HOOK.submit_path}  ({RESOLUTION}, {ASPECT_RATIO}, {DURATION_SECONDS:.0f}s)")
    print(f"Source image: {REFERENCE_IMAGE_PATH} (your approved photo, used as-is, no Nano Banana call)")
    print(f"\nVideo prompt:\n  {HOOK_PROMPT}")
    print(f"\nEstimated cost: ${video_cost:.4f}")
    print(f"Hard cap:       ${MAX_SPEND_USD:.2f}")
    print("Rules: exactly 1 video call, no retries, no chaining to Prep 1 - this stage stops here.")
    print("=" * 70)

    if video_cost > MAX_SPEND_USD:
        fail(f"Estimated cost ${video_cost:.4f} exceeds the ${MAX_SPEND_USD:.2f} cap. Nothing was generated.")

    if not skip_confirm:
        answer = input(f"\nType 'yes' to spend up to ${video_cost:.4f} and proceed: ").strip().lower()
        if answer != "yes":
            print("Cancelled. Nothing was generated.")
            sys.exit(0)

    manifest = load_manifest()
    manifest["hook"] = {
        "video_model": WAN_3_0_FORMA_V1_HOOK.submit_path,
        "resolution": RESOLUTION,
        "aspect_ratio": ASPECT_RATIO,
        "duration_seconds": DURATION_SECONDS,
        "video_prompt": HOOK_PROMPT,
        "reference_image_path": str(REFERENCE_IMAGE_PATH),
        "max_spend_usd": MAX_SPEND_USD,
        "estimated_cost_usd": video_cost,
        "raw_video_path": None,
        "actual_cost_usd": None,
        "completed_at": None,
    }
    save_manifest(manifest)

    print("\nSubmitting Hook video generation job (Wan 3.0 standard, {})...".format(RESOLUTION))
    t0 = time.monotonic()
    try:
        submitted = video_provider.submit_video_job(video_request)
    except VideoProviderError as e:
        fail(f"Video submission failed: {e}")
    print(f"      Submitted. Provider job id: {submitted.provider_job_id}")
    print(f"      Estimated video cost: ${submitted.estimated_cost_usd:.4f}")

    JOB_STATE_PATH.write_text(
        json.dumps({"provider_job_id": submitted.provider_job_id, "meta": submitted.meta}, indent=2)
    )
    print(f"      Job state saved to: {JOB_STATE_PATH} (used automatically by recover_fal_video_job.py)")

    print("      Polling for completion (no retries on error - any failure stops here)...")
    result = None
    while True:
        elapsed = time.monotonic() - t0
        if elapsed > MAX_WAIT_SECONDS:
            fail(
                f"Gave up after {elapsed:.0f}s waiting for the video (job {submitted.provider_job_id} "
                "may still complete and be billed on fal.ai's side even though we stopped watching it - "
                "check https://fal.ai/dashboard/billing). We did not retry or resubmit.\n"
                f"      To check on it later without spending anything again, run:\n"
                f"      python -m scripts.recover_fal_video_job {submitted.provider_job_id}"
            )
        try:
            result = video_provider.get_job_status(submitted.provider_job_id, meta=submitted.meta)
        except VideoProviderError as e:
            fail(
                f"Status check failed: {e}\n"
                f"      The job was already submitted (and may be billed) - to check on it later without\n"
                f"      spending anything again, run:\n"
                f"      python -m scripts.recover_fal_video_job {submitted.provider_job_id}"
            )

        if result.status == ProviderJobState.PROCESSING:
            print(f"      ...still processing ({elapsed:.0f}s elapsed)")
            time.sleep(POLL_INTERVAL_SECONDS)
            continue
        break

    video_seconds = time.monotonic() - t0

    if result.status == ProviderJobState.FAILED:
        fail(f"Provider reported generation failure: {result.error_message}")

    print(f"      Completed in {video_seconds:.1f}s")

    try:
        video_provider.download_result(submitted.provider_job_id, result.output_url, str(HOOK_RAW_PATH))
    except VideoProviderError as e:
        fail(
            f"Download failed (generation already succeeded and was billed, but the local save failed): {e}\n"
            f"      To retry just the download without spending anything again, run:\n"
            f"      python -m scripts.recover_fal_video_job {submitted.provider_job_id}"
        )

    actual_cost = result.actual_cost_usd if result.actual_cost_usd is not None else submitted.estimated_cost_usd

    manifest["hook"]["raw_video_path"] = str(HOOK_RAW_PATH)
    manifest["hook"]["actual_cost_usd"] = actual_cost
    manifest["hook"]["completed_at"] = _now()
    save_manifest(manifest)

    print("\n" + "=" * 70)
    print("STAGE A1 (HOOK) DONE - stopping completely, as required.")
    print("=" * 70)
    print(f"Hook raw clip: {HOOK_RAW_PATH}")
    print(f"Actual cost:   ${actual_cost:.4f}")
    print(f"Manifest:      {MANIFEST_PATH}")
    print("\nSTOP HERE. Review hook_raw.mp4 against:")
    print("  - reads as the same location as your approved reference photo")
    print("    (cave, waterfall, rock, vegetation, distant landscape all consistent)")
    print("  - waterfall/mist motion is visibly alive, not static")
    print("  - builder present, unposed, never looks toward camera")
    print("  - no construction of any kind begins yet")
    print("\nDo NOT run Stage A2 (Prep 1) until you have reviewed and approved this clip.")
    print("Stage A2 is scripts/run_forma_v1_chapter_a_prep1.py - a separate script, not run automatically.")


if __name__ == "__main__":
    main()
