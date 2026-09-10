#!/usr/bin/env python3
"""FORMA VIDEO #2 - SHOT 1: OPENING + SITE PREP.

Only runnable after the site reference image is generated AND approved.
Starting image is site_reference.jpg directly (already a still image -
no frame extraction needed).

Visual-only, no audio. Brief beauty beat on the untouched site, then a
compact tracked mini-dozer sweeps a frontier clearing ~70-80% of the
build pad. No structure appears.

Makes exactly ONE Wan 3.0 video call. No retries. Does NOT chain to Shot
2 - a separate script, run only after this clip is reviewed and approved.

Usage:
    python -m scripts.run_alpine_video_2_shot1_opening_prep
    python -m scripts.run_alpine_video_2_shot1_opening_prep --yes
"""
import dataclasses
import json
import sys
import time

from app.config import settings
from app.providers.base import ProviderJobState, VideoGenerationRequest, VideoProviderError
from app.providers.video.fal import WAN_3_0_STANDARD, FalVideoProvider
from scripts.run_alpine_video_2_common import (
    ASPECT_RATIO,
    LOCATION_BIBLE,
    MANIFEST_PATH,
    OUTPUT_DIR,
    RESOLUTION,
    enforce_budget,
    fail,
    load_manifest,
    now,
    save_manifest,
)
from scripts.run_alpine_video_2_site_reference import SITE_REFERENCE_PATH

MAX_SPEND_USD = 0.35
DURATION_SECONDS = 7.0
POLL_INTERVAL_SECONDS = 3
MAX_WAIT_SECONDS = 300

SHOT1_RAW_PATH = OUTPUT_DIR / "shot1_opening_prep_raw.mp4"
JOB_STATE_PATH = OUTPUT_DIR / "shot1_last_job.json"

PROMPT = (
    "Vertical 9:16, realistic documentary-style footage. Wide environmental establishing shot "
    "at approximately human chest/eye height, near-horizontal axis. Fixed camera position, no "
    "movement, no angle change.\n\n"
    f"The site is {LOCATION_BIBLE}, completely untouched at first - no structure, no builder "
    "action visible for the opening moment. Then a compact tracked mini-dozer with a wide "
    "grading blade, already aligned at the edge of the intended build pad with the blade down, "
    "drives steadily forward, pushing loose rock and debris ahead of it into one coherent ridge. "
    "Behind the blade, the ground reads visibly cleaner and flatter; ahead of it, the rough "
    "ground remains untouched until the machine reaches it. By the end of the clip, "
    "approximately 70 to 80 percent of the intended build pad reads as cleared and leveled - "
    "one clear frontier: cleared pad behind, machine/blade in the middle, rough site ahead. No "
    "structure of any kind appears. The lake, mountains, and shoreline remain a major visual "
    "element throughout, never reduced to background scenery. No posing, no presenter behavior."
)

WAN_CONFIG = dataclasses.replace(WAN_3_0_STANDARD, extra_payload={"duration": 7})


def main() -> None:
    skip_confirm = "--yes" in sys.argv[1:]

    key_preview = f"{settings.fal_api_key[:6]}..." if settings.fal_api_key else None
    print(f"FAL_API_KEY loaded from .env: {'yes (' + key_preview + ')' if key_preview else 'NO'}")
    if not settings.fal_api_key:
        fail("FAL_API_KEY is not set. Add FAL_API_KEY=your_key_here to your .env file and try again.")

    if not SITE_REFERENCE_PATH.exists():
        fail(
            f"{SITE_REFERENCE_PATH} not found - the site reference image has not been generated "
            "yet. Run scripts/run_alpine_video_2_site_reference.py first."
        )

    print(f"\nUpstream file found: {SITE_REFERENCE_PATH}")
    approval = input(
        "Have you reviewed and approved site_reference.jpg? Type 'yes' to confirm before "
        "proceeding (anything else stops here, nothing generated): "
    ).strip().lower()
    if approval != "yes":
        print("Stopped - site reference was not confirmed as approved. Nothing was generated.")
        sys.exit(0)

    video_provider = FalVideoProvider(WAN_CONFIG)
    video_request = VideoGenerationRequest(
        prompt=PROMPT,
        reference_image_path=str(SITE_REFERENCE_PATH),
        aspect_ratio=ASPECT_RATIO,
        duration_seconds=DURATION_SECONDS,
        extra_params={"resolution": RESOLUTION},
    )
    video_cost = video_provider.estimate_cost(video_request)

    print("=" * 70)
    print("FORMA VIDEO #2 - SHOT 1 (OPENING + SITE PREP) - THIS WILL SPEND REAL MONEY")
    print("=" * 70)
    print(f"Video model: {WAN_CONFIG.submit_path}  ({RESOLUTION}, {ASPECT_RATIO}, {DURATION_SECONDS:.0f}s)")
    print(f"Source image: {SITE_REFERENCE_PATH}")
    print(f"\nVideo prompt:\n  {PROMPT}")
    print(f"\nEstimated cost: ${video_cost:.4f}")
    print(f"Hard cap:       ${MAX_SPEND_USD:.2f}")
    print("=" * 70)

    if video_cost > MAX_SPEND_USD:
        fail(f"Estimated cost ${video_cost:.4f} exceeds the ${MAX_SPEND_USD:.2f} cap. Nothing was generated.")
    enforce_budget(video_cost)

    if not skip_confirm:
        answer = input(f"\nType 'yes' to spend up to ${video_cost:.4f} and proceed: ").strip().lower()
        if answer != "yes":
            print("Cancelled. Nothing was generated.")
            sys.exit(0)

    manifest = load_manifest()
    manifest["shot1"] = {
        "video_model": WAN_CONFIG.submit_path,
        "resolution": RESOLUTION,
        "aspect_ratio": ASPECT_RATIO,
        "duration_seconds": DURATION_SECONDS,
        "video_prompt": PROMPT,
        "start_frame_path": str(SITE_REFERENCE_PATH),
        "max_spend_usd": MAX_SPEND_USD,
        "estimated_cost_usd": video_cost,
        "raw_video_path": None,
        "actual_cost_usd": None,
        "completed_at": None,
    }
    save_manifest(manifest)

    print(f"\nSubmitting Shot 1 video generation job (Wan 3.0 standard, {RESOLUTION})...")
    t0 = time.monotonic()
    try:
        submitted = video_provider.submit_video_job(video_request)
    except VideoProviderError as e:
        fail(f"Video submission failed: {e}")
    print(f"      Submitted. Provider job id: {submitted.provider_job_id}")

    JOB_STATE_PATH.write_text(
        json.dumps({"provider_job_id": submitted.provider_job_id, "meta": submitted.meta}, indent=2)
    )
    print(f"      Job state saved to: {JOB_STATE_PATH}")

    print("      Polling for completion (no retries on error - any failure stops here)...")
    result = None
    while True:
        elapsed = time.monotonic() - t0
        if elapsed > MAX_WAIT_SECONDS:
            fail(
                f"Gave up after {elapsed:.0f}s (job {submitted.provider_job_id} may still complete "
                "and be billed on fal.ai's side). We did not retry or resubmit.\n"
                f"      To recover: python -m scripts.recover_fal_video_job {submitted.provider_job_id}"
            )
        try:
            result = video_provider.get_job_status(submitted.provider_job_id, meta=submitted.meta)
        except VideoProviderError as e:
            fail(
                f"Status check failed: {e}\n"
                f"      To recover: python -m scripts.recover_fal_video_job {submitted.provider_job_id}"
            )
        if result.status == ProviderJobState.PROCESSING:
            print(f"      ...still processing ({elapsed:.0f}s elapsed)")
            time.sleep(POLL_INTERVAL_SECONDS)
            continue
        break

    if result.status == ProviderJobState.FAILED:
        fail(f"Provider reported generation failure: {result.error_message}")

    print(f"      Completed in {time.monotonic() - t0:.1f}s")

    try:
        video_provider.download_result(submitted.provider_job_id, result.output_url, str(SHOT1_RAW_PATH))
    except VideoProviderError as e:
        fail(
            f"Download failed (generation already billed): {e}\n"
            f"      To recover: python -m scripts.recover_fal_video_job {submitted.provider_job_id}"
        )

    actual_cost = result.actual_cost_usd if result.actual_cost_usd is not None else submitted.estimated_cost_usd
    manifest["shot1"]["raw_video_path"] = str(SHOT1_RAW_PATH)
    manifest["shot1"]["actual_cost_usd"] = actual_cost
    manifest["shot1"]["completed_at"] = now()
    save_manifest(manifest)

    print("\n" + "=" * 70)
    print("SHOT 1 DONE - stopping completely, as required.")
    print("=" * 70)
    print(f"Raw:      {SHOT1_RAW_PATH}")
    print(f"Cost:     ${actual_cost:.4f}")
    print(f"Manifest: {MANIFEST_PATH}")
    print("\nSTOP HERE. Review shot1_opening_prep_raw.mp4 against:")
    print("  1. beauty beat reads clearly before the machine starts")
    print("  2. one clear sweeping frontier: cleared pad | machine/blade | rough site")
    print("  3. ~70-80% of the pad cleared by the end - no structure appears")
    print("  4. lake/mountains/shoreline remain a major visual element")
    print("\nDo NOT run Shot 2 until you have reviewed and approved this clip.")


if __name__ == "__main__":
    main()
