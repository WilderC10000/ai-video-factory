#!/usr/bin/env python3
"""FORMA VIDEO #2 - SHOT 2: BASE + FLOOR STRUCTURE.

Only runnable after Shot 1 is generated AND approved. Starting image is
the REAL last frame of shot1_opening_prep_raw.mp4, extracted locally
(free, no API call) - same camera chapter as Shot 1, no edit needed.

Visual-only, no audio. Perimeter base beams + ~75% of floor joists
placed, one direction, matching Shot 1's frontier.

Makes exactly ONE Wan 3.0 video call. No retries. Does NOT chain to the
next edit - a separate script, run only after this clip is approved.

Usage:
    python -m scripts.run_alpine_video_2_shot2_base_floor
    python -m scripts.run_alpine_video_2_shot2_base_floor --yes
"""
import dataclasses
import json
import sys
import time

from app.config import settings
from app.providers.base import ProviderJobState, VideoGenerationRequest, VideoProviderError
from app.providers.video.fal import WAN_3_0_STANDARD, FalVideoProvider
from app.services.frame_extraction import FrameExtractionError, extract_last_frame
from scripts.run_alpine_video_2_common import (
    ASPECT_RATIO,
    MANIFEST_PATH,
    OUTPUT_DIR,
    RESOLUTION,
    enforce_budget,
    fail,
    load_manifest,
    now,
    save_manifest,
)
from scripts.run_alpine_video_2_shot1_opening_prep import SHOT1_RAW_PATH

MAX_SPEND_USD = 0.50
DURATION_SECONDS = 10.0
POLL_INTERVAL_SECONDS = 3
MAX_WAIT_SECONDS = 300

SHOT2_START_FRAME_PATH = OUTPUT_DIR / "shot2_start_frame.jpg"
SHOT2_RAW_PATH = OUTPUT_DIR / "shot2_base_floor_raw.mp4"
JOB_STATE_PATH = OUTPUT_DIR / "shot2_last_job.json"

CAMERA_CLAUSE = "Camera view: same fixed viewpoint as the previous shot, held completely steady. No camera movement, no angle change."

PROMPT = (
    "Vertical 9:16, realistic construction footage, documentary/observational style. "
    f"{CAMERA_CLAUSE} Continuing directly from the current state shown in the starting image.\n\n"
    "The build pad is cleared and leveled - no structure yet. The builder positions a horizontal "
    "perimeter base beam at the edge of the pad and secures it, then positions a floor joist "
    "perpendicular to it and secures that, then shifts to the next joist position immediately "
    "adjacent and repeats - advancing steadily in one continuous direction across the pad, "
    "matching the direction the site was cleared in. Materials come from a timber stack staged "
    "at the edge of the pad. By the end of the clip, the perimeter base is complete and "
    "approximately 70 to 80 percent of the floor joists are placed, still with a visible section "
    "of bare cleared pad ahead of the working frontier. No decking, no walls, no roof appear. "
    "The lake, mountains, and shoreline remain clearly visible and important throughout. No "
    "posing, no presenter behavior."
)

WAN_CONFIG = dataclasses.replace(WAN_3_0_STANDARD, extra_payload={"duration": 10})


def main() -> None:
    skip_confirm = "--yes" in sys.argv[1:]

    key_preview = f"{settings.fal_api_key[:6]}..." if settings.fal_api_key else None
    print(f"FAL_API_KEY loaded from .env: {'yes (' + key_preview + ')' if key_preview else 'NO'}")
    if not settings.fal_api_key:
        fail("FAL_API_KEY is not set. Add FAL_API_KEY=your_key_here to your .env file and try again.")

    if not SHOT1_RAW_PATH.exists():
        fail(f"{SHOT1_RAW_PATH} not found - Shot 1 has not been generated yet.")

    print(f"\nUpstream file found: {SHOT1_RAW_PATH}")
    approval = input(
        "Have you reviewed and approved shot1_opening_prep_raw.mp4? Type 'yes' to confirm before "
        "proceeding (anything else stops here, nothing generated): "
    ).strip().lower()
    if approval != "yes":
        print("Stopped - Shot 1 was not confirmed as approved. Nothing was generated.")
        sys.exit(0)

    print("\nExtracting the real last frame of shot1_opening_prep_raw.mp4 locally (no API call)...")
    try:
        extract_last_frame(SHOT1_RAW_PATH, SHOT2_START_FRAME_PATH)
    except FrameExtractionError as e:
        fail(f"Frame extraction failed: {e}")
    print(f"      Done -> {SHOT2_START_FRAME_PATH} (shot1_opening_prep_raw.mp4 was only read, never modified)")

    video_provider = FalVideoProvider(WAN_CONFIG)
    video_request = VideoGenerationRequest(
        prompt=PROMPT,
        reference_image_path=str(SHOT2_START_FRAME_PATH),
        aspect_ratio=ASPECT_RATIO,
        duration_seconds=DURATION_SECONDS,
        extra_params={"resolution": RESOLUTION},
    )
    video_cost = video_provider.estimate_cost(video_request)

    print("=" * 70)
    print("FORMA VIDEO #2 - SHOT 2 (BASE + FLOOR STRUCTURE) - THIS WILL SPEND REAL MONEY")
    print("=" * 70)
    print(f"Video model: {WAN_CONFIG.submit_path}  ({RESOLUTION}, {ASPECT_RATIO}, {DURATION_SECONDS:.0f}s)")
    print(f"Source image: {SHOT2_START_FRAME_PATH}")
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
    manifest["shot2"] = {
        "video_model": WAN_CONFIG.submit_path,
        "resolution": RESOLUTION,
        "aspect_ratio": ASPECT_RATIO,
        "duration_seconds": DURATION_SECONDS,
        "video_prompt": PROMPT,
        "start_frame_path": str(SHOT2_START_FRAME_PATH),
        "max_spend_usd": MAX_SPEND_USD,
        "estimated_cost_usd": video_cost,
        "raw_video_path": None,
        "actual_cost_usd": None,
        "completed_at": None,
    }
    save_manifest(manifest)

    print(f"\nSubmitting Shot 2 video generation job (Wan 3.0 standard, {RESOLUTION})...")
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
                f"Gave up after {elapsed:.0f}s. To recover: "
                f"python -m scripts.recover_fal_video_job {submitted.provider_job_id}"
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
        video_provider.download_result(submitted.provider_job_id, result.output_url, str(SHOT2_RAW_PATH))
    except VideoProviderError as e:
        fail(
            f"Download failed (generation already billed): {e}\n"
            f"      To recover: python -m scripts.recover_fal_video_job {submitted.provider_job_id}"
        )

    actual_cost = result.actual_cost_usd if result.actual_cost_usd is not None else submitted.estimated_cost_usd
    manifest["shot2"]["raw_video_path"] = str(SHOT2_RAW_PATH)
    manifest["shot2"]["actual_cost_usd"] = actual_cost
    manifest["shot2"]["completed_at"] = now()
    save_manifest(manifest)

    print("\n" + "=" * 70)
    print("SHOT 2 DONE - stopping completely, as required.")
    print("=" * 70)
    print(f"Raw:      {SHOT2_RAW_PATH}")
    print(f"Cost:     ${actual_cost:.4f}")
    print(f"Manifest: {MANIFEST_PATH}")
    print("\nSTOP HERE. Review shot2_base_floor_raw.mp4 against:")
    print("  1. ~70-80% of joists placed, one direction, matching Shot 1's frontier")
    print("  2. no decking, no walls, no roof appear")
    print("  3. lake/mountains/shoreline remain visually important")
    print("\nDo NOT run the next edit until you have reviewed and approved this clip.")


if __name__ == "__main__":
    main()
