#!/usr/bin/env python3
"""ONE-SHOT real fal.ai test: exactly one FLUX schnell reference image, then
exactly one Wan 2.2 A14B Turbo (480p, 9:16) video generated from it.

Running this calls the real, PAID fal.ai API and spends real money (capped
below). It is a deliberately narrow, standalone script, separate from the
project/shot/database pipeline:

  - Talks directly to FalImageProvider / FalVideoProvider (app/providers/
    image/fal.py, app/providers/video/fal.py) - no new provider logic here.
  - No automatic retries anywhere. Any failure - image generation, video
    submission, a status check, or the download - stops the script
    immediately via fail(). Polling a still-PROCESSING job is normal
    async waiting, not a retry; it is capped by MAX_WAIT_SECONDS below.
  - Exactly one image and exactly one video. Nothing here calls itself
    again, and there is no regeneration path.
  - A hard spend cap (MAX_SPEND_USD) is checked BEFORE any network call.
  - No database writes - this is intentionally simpler than the full
    project pipeline; see scripts/seed_demo_project.py for that.

Usage (from the repo root, with FAL_API_KEY set in your .env):
    python -m scripts.run_first_fal_test
    python -m scripts.run_first_fal_test --yes     (skip the confirmation prompt)
"""
import json
import sys
import time
from pathlib import Path

from app.config import settings
from app.providers.base import (
    ImageGenerationRequest,
    ImageProviderError,
    ProviderJobState,
    VideoGenerationRequest,
    VideoProviderError,
)
from app.providers.image.fal import FLUX_SCHNELL, FalImageProvider
from app.providers.video.fal import WAN_TURBO, FalVideoProvider

MAX_SPEND_USD = 0.06
RESOLUTION = "480p"
ASPECT_RATIO = "9:16"
POLL_INTERVAL_SECONDS = 3
MAX_WAIT_SECONDS = 300  # 5 minutes; see the timeout message below if this is hit

PROMPT_STYLE = (
    "Casual viral construction footage, lone builder, dramatic natural setting, "
    "clear construction progress, realistic but not cinematic, phone/documentary feel."
)
IMAGE_PROMPT = (
    f"{PROMPT_STYLE} A lone construction worker beginning to dig a large pit in a "
    "rugged natural backyard landscape, overcast daylight, handheld phone-photo "
    "quality, slightly imperfect framing, vertical 9:16 composition."
)
VIDEO_PROMPT = (
    f"{PROMPT_STYLE} Handheld phone footage of the builder digging with a shovel, "
    "dirt and dust moving naturally, subtle camera shake, natural daylight, "
    "no cinematic camera moves."
)

OUTPUT_DIR = Path(__file__).resolve().parent.parent / "data" / "fal_test"
JOB_STATE_PATH = OUTPUT_DIR / "last_job.json"


def fail(message: str) -> None:
    print(f"\nSTOPPED: {message}")
    print("No retry, no second attempt - the script is exiting now.")
    sys.exit(1)


def main() -> None:
    skip_confirm = "--yes" in sys.argv[1:]

    key_preview = f"{settings.fal_api_key[:6]}..." if settings.fal_api_key else None
    print(f"FAL_API_KEY loaded from .env: {'yes (' + key_preview + ')' if key_preview else 'NO'}")
    if not settings.fal_api_key:
        fail("FAL_API_KEY is not set. Add FAL_API_KEY=your_key_here to your .env file and try again.")

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    image_path = OUTPUT_DIR / "reference_image.jpg"
    video_path = OUTPUT_DIR / "clip.mp4"

    image_provider = FalImageProvider(FLUX_SCHNELL)
    video_provider = FalVideoProvider(WAN_TURBO)

    image_request = ImageGenerationRequest(prompt=IMAGE_PROMPT, width=576, height=1024)
    image_cost = image_provider.estimate_cost(image_request)

    # No reference_image_path yet at this point (the image doesn't exist
    # until step 1 runs) - estimate_cost only needs resolution, so this is
    # enough to compute the pre-flight total before spending anything.
    cost_preview_request = VideoGenerationRequest(
        prompt=VIDEO_PROMPT, aspect_ratio=ASPECT_RATIO, extra_params={"resolution": RESOLUTION}
    )
    video_cost = video_provider.estimate_cost(cost_preview_request)
    total_cost = round(image_cost + video_cost, 4)

    print("=" * 70)
    print("ONE-SHOT REAL fal.ai TEST - THIS WILL SPEND REAL MONEY")
    print("=" * 70)
    print(f"Image model:    {FLUX_SCHNELL.model_id}")
    print(f"Video model:    {WAN_TURBO.submit_path}")
    print(f"Resolution:     {RESOLUTION}    Aspect ratio: {ASPECT_RATIO}")
    print(f"Image prompt:   {IMAGE_PROMPT}")
    print(f"Video prompt:   {VIDEO_PROMPT}")
    print(f"Estimated cost: ${image_cost:.4f} (image) + ${video_cost:.4f} (video) = ${total_cost:.4f}")
    print(f"Hard cap:       ${MAX_SPEND_USD:.2f}")
    print("Rules: exactly one image, exactly one video, no retries, stop on any failure.")
    print("=" * 70)

    if total_cost > MAX_SPEND_USD:
        fail(f"Estimated cost ${total_cost:.4f} exceeds the ${MAX_SPEND_USD:.2f} cap. Nothing was generated.")

    if not skip_confirm:
        answer = input(f"\nType 'yes' to spend up to ${total_cost:.4f} and proceed: ").strip().lower()
        if answer != "yes":
            print("Cancelled. Nothing was generated.")
            sys.exit(0)

    # --- Step 1: exactly one reference image --------------------------------
    print("\n[1/2] Generating reference image (FLUX schnell)...")
    t0 = time.monotonic()
    try:
        image_result = image_provider.generate_image(image_request, str(image_path))
    except ImageProviderError as e:
        fail(f"Image generation failed: {e}")
    image_seconds = time.monotonic() - t0
    print(f"      Done in {image_seconds:.1f}s -> {image_path}")
    print(f"      Image cost: ${image_result.cost_usd:.4f}")

    # --- Step 2: exactly one video, from that exact image -------------------
    print("\n[2/2] Submitting video generation job (Wan 2.2 A14B Turbo, 480p)...")
    video_request = VideoGenerationRequest(
        prompt=VIDEO_PROMPT,
        reference_image_path=str(image_path),
        aspect_ratio=ASPECT_RATIO,
        extra_params={"resolution": RESOLUTION},
    )
    t1 = time.monotonic()
    try:
        submitted = video_provider.submit_video_job(video_request)
    except VideoProviderError as e:
        fail(f"Video submission failed: {e}")
    print(f"      Submitted. Provider job id: {submitted.provider_job_id}")
    print(f"      Estimated video cost: ${submitted.estimated_cost_usd:.4f}")

    # Save the job id + fal.ai's own status/result URLs (from submitted.meta)
    # to disk immediately, BEFORE polling starts - this is what lets
    # recover_fal_video_job.py use the exact URLs fal.ai gave us (the robust
    # path) instead of reconstructing them, even if this script crashes on
    # the very next line.
    JOB_STATE_PATH.write_text(
        json.dumps({"provider_job_id": submitted.provider_job_id, "meta": submitted.meta}, indent=2)
    )
    print(f"      Job state saved to: {JOB_STATE_PATH} (used automatically by recover_fal_video_job.py)")

    print("      Polling for completion (no retries on error - any failure stops here)...")
    result = None
    while True:
        elapsed = time.monotonic() - t1
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

    video_seconds = time.monotonic() - t1

    if result.status == ProviderJobState.FAILED:
        fail(f"Provider reported generation failure: {result.error_message}")

    print(f"      Completed in {video_seconds:.1f}s")

    try:
        video_provider.download_result(submitted.provider_job_id, result.output_url, str(video_path))
    except VideoProviderError as e:
        fail(
            f"Download failed (generation already succeeded and was billed, but the local save failed): {e}\n"
            f"      To retry just the download without spending anything again, run:\n"
            f"      python -m scripts.recover_fal_video_job {submitted.provider_job_id}"
        )

    actual_video_cost = result.actual_cost_usd if result.actual_cost_usd is not None else submitted.estimated_cost_usd
    total_actual = round(image_result.cost_usd + actual_video_cost, 4)

    print("\n" + "=" * 70)
    print("DONE")
    print("=" * 70)
    print(f"Reference image: {image_path}")
    print(f"Video clip:      {video_path}")
    print(f"Image cost:      ${image_result.cost_usd:.4f}")
    print(
        f"Video cost:      ${actual_video_cost:.4f}  "
        f"(Wan Turbo bills a flat rate per resolution tier - this is fal.ai's advertised "
        f"{RESOLUTION} price, not a per-second calculation; confirm against "
        f"https://fal.ai/dashboard/billing for the definitive charge)"
    )
    print(f"Total cost:      ${total_actual:.4f}")
    print(f"Total wall time: {(image_seconds + video_seconds):.1f}s (image {image_seconds:.1f}s + video {video_seconds:.1f}s)")
    print("\nNo further generation will happen automatically.")
    print("Review the image and clip yourself, then decide on next steps.")


if __name__ == "__main__":
    main()
