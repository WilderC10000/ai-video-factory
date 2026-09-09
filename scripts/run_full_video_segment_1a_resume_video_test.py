#!/usr/bin/env python3
"""RESUME Segment 1A: video-only completion from the already-approved
start-frame image.

scripts/run_full_video_segment_1a_test.py's mandatory review gate worked
exactly as designed - it stopped after the $0.15 image call and before the
$0.30 video call, and the resulting image was reviewed and approved. This
script does NOT regenerate that image and does NOT call Nano Banana Pro at
all. It reuses the existing, approved
`data/fal_full_video_segment_1a/segment_1a_start_frame.jpg` exactly as-is
and makes ONLY the remaining Wan 3.0 480p 6-second video call from it.

The video prompt is imported directly from run_full_video_segment_1a_test
(VIDEO_PROMPT) - not retyped - so it is byte-identical to the already-
approved prompt, then has exactly one additional sentence appended (the
user's requested extra emphasis: the builder's attention moves immediately
and fully onto the clearing task, and he must not look toward the camera).
Nothing else about the approved prompt is changed. The video model config
(WAN_3_0_SEGMENT_1A, a local duration=6 variant of WAN_3_0_STANDARD),
resolution, aspect ratio, and duration are all imported from that same
module, not redefined, so this resume call is guaranteed identical to what
was already approved in every respect except the one requested addition.

Safety, same pattern as every other real-call script in this repo:
  - Exactly 1 video-generation call. No image call, no retry, no other
    segment.
  - Hard cap set exactly equal to the computed video cost ($0.30) - zero
    margin, since Wan 3.0's per-second billing is exactly precomputable.
  - The existing manifest.json (from the interrupted first run) is loaded,
    checked (image already recorded, video not yet recorded, image file
    exists on disk), and then updated in place with the video result -
    never overwritten or regenerated for the image fields.
  - Any failure (submission, status check, or download) stops immediately
    via fail() with the exact error and, where relevant, the
    recover_fal_video_job.py hint - no automatic retry or resubmission.

Usage (from the repo root, with FAL_API_KEY set in your .env):
    python -m scripts.run_full_video_segment_1a_resume_video_test
    python -m scripts.run_full_video_segment_1a_resume_video_test --yes
"""
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

from app.config import settings
from app.providers.base import ProviderJobState, VideoGenerationRequest, VideoProviderError
from app.providers.video.fal import FalVideoProvider
from scripts.run_full_video_segment_1a_test import (
    ASPECT_RATIO,
    DURATION_SECONDS,
    MANIFEST_PATH,
    OUTPUT_DIR,
    RESOLUTION,
    SEGMENT_ID,
    VIDEO_PROMPT,
    WAN_3_0_SEGMENT_1A,
)

MAX_SPEND_USD = 0.30  # video only - the image was already generated and paid for
POLL_INTERVAL_SECONDS = 3
MAX_WAIT_SECONDS = 300  # 5 minutes; see the timeout message below if this is hit

# Exactly the approved prompt (imported, not retyped) plus one additional
# sentence - the only change requested: reinforce that the builder's
# attention moves fully onto the task and he must not look at the camera.
VIDEO_PROMPT_WITH_EMPHASIS = (
    VIDEO_PROMPT
    + " His attention moves immediately and fully onto the clearing task ahead of him - he must not "
    "look toward the camera at any point during this clip."
)

IMAGE_PATH = OUTPUT_DIR / "segment_1a_start_frame.jpg"
VIDEO_PATH = OUTPUT_DIR / "segment_1a.mp4"
JOB_STATE_PATH = OUTPUT_DIR / "last_job.json"


def fail(message: str) -> None:
    print(f"\nSTOPPED: {message}")
    print("No retry, no further generation - the script is exiting now.")
    sys.exit(1)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def main() -> None:
    skip_confirm = "--yes" in sys.argv[1:]

    key_preview = f"{settings.fal_api_key[:6]}..." if settings.fal_api_key else None
    print(f"FAL_API_KEY loaded from .env: {'yes (' + key_preview + ')' if key_preview else 'NO'}")
    if not settings.fal_api_key:
        fail("FAL_API_KEY is not set. Add FAL_API_KEY=your_key_here to your .env file and try again.")

    if not MANIFEST_PATH.exists():
        fail(f"No existing manifest found at {MANIFEST_PATH} - nothing to resume from.")
    manifest = json.loads(MANIFEST_PATH.read_text())

    if not IMAGE_PATH.exists():
        fail(f"Approved start-frame image not found at {IMAGE_PATH} - nothing to resume from.")
    if manifest.get("image_path") != str(IMAGE_PATH):
        fail(f"manifest.json's image_path does not match {IMAGE_PATH} - refusing to guess. Check the file by hand.")
    if manifest.get("video_path"):
        fail(
            f"manifest.json already records a completed video ({manifest['video_path']}) - "
            "this segment appears already done. Refusing to generate a second video for it."
        )

    print(f"Reusing already-approved image: {IMAGE_PATH} (not regenerated, no Nano Banana Pro call)")

    video_provider = FalVideoProvider(WAN_3_0_SEGMENT_1A)
    video_request = VideoGenerationRequest(
        prompt=VIDEO_PROMPT_WITH_EMPHASIS,
        reference_image_path=str(IMAGE_PATH),
        aspect_ratio=ASPECT_RATIO,
        duration_seconds=DURATION_SECONDS,
        extra_params={"resolution": RESOLUTION},
    )
    video_cost = video_provider.estimate_cost(video_request)

    print("=" * 70)
    print(f"FULL VIDEO #1 - SEGMENT {SEGMENT_ID} - RESUME (VIDEO ONLY) - THIS WILL SPEND REAL MONEY")
    print("=" * 70)
    print(f"Video model: {WAN_3_0_SEGMENT_1A.submit_path}  ({RESOLUTION}, {ASPECT_RATIO}, {DURATION_SECONDS:.0f}s)")
    print(f"Source image (already approved, reused as-is): {IMAGE_PATH}")
    print(f"\nVideo prompt (approved prompt + 1 added emphasis sentence):\n  {VIDEO_PROMPT_WITH_EMPHASIS}")
    print(f"\nEstimated cost: ${video_cost:.4f} (video only - no image call)")
    print(f"Hard cap:       ${MAX_SPEND_USD:.2f}")
    print("Rules: exactly 1 video call, no image call, no retries, no other segment.")
    print("=" * 70)

    if video_cost > MAX_SPEND_USD:
        fail(f"Estimated cost ${video_cost:.4f} exceeds the ${MAX_SPEND_USD:.2f} cap. Nothing was generated.")

    if not skip_confirm:
        answer = input(f"\nType 'yes' to spend up to ${video_cost:.4f} and proceed: ").strip().lower()
        if answer != "yes":
            print("Cancelled. Nothing was generated.")
            sys.exit(0)

    print(f"\n[1/1] Submitting segment {SEGMENT_ID} video generation job (Wan 3.0 standard, {RESOLUTION})...")
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
        video_provider.download_result(submitted.provider_job_id, result.output_url, str(VIDEO_PATH))
    except VideoProviderError as e:
        fail(
            f"Download failed (generation already succeeded and was billed, but the local save failed): {e}\n"
            f"      To retry just the download without spending anything again, run:\n"
            f"      python -m scripts.recover_fal_video_job {submitted.provider_job_id}"
        )

    actual_video_cost = result.actual_cost_usd if result.actual_cost_usd is not None else submitted.estimated_cost_usd

    manifest["video_prompt"] = VIDEO_PROMPT_WITH_EMPHASIS
    manifest["video_path"] = str(VIDEO_PATH)
    manifest["video_cost_usd"] = actual_video_cost
    manifest["actual_cost_usd"] = round((manifest.get("image_cost_usd") or 0.0) + actual_video_cost, 4)
    manifest["completed_at"] = _now()
    MANIFEST_PATH.write_text(json.dumps(manifest, indent=2))

    print("\n" + "=" * 70)
    print(f"DONE - segment {SEGMENT_ID} video completed from the already-approved image.")
    print("=" * 70)
    print(f"Start-frame image (unchanged): {IMAGE_PATH}")
    print(f"Segment clip:                  {VIDEO_PATH}")
    print(f"Video cost: ${actual_video_cost:.4f}   Total segment cost: ${manifest['actual_cost_usd']:.4f}")
    print(f"Manifest: {MANIFEST_PATH}")
    print("\nSTOP HERE. Review segment_1a.mp4 against:")
    print("  - first 1.5-2s clearly reads as untouched/raw, no structure")
    print("  - clearing progresses via obvious hard jumps, not continuous real-time motion")
    print("  - builder's attention moves immediately onto the task; never looks toward camera")
    print("  - ends on a fully cleared, still-unbuilt site (no stakes/materials yet)")
    print("  - ocean/wind/cloud motion reads as alive")
    print("\nDo not build segment 1B until this segment is reviewed and approved.")


if __name__ == "__main__":
    main()
