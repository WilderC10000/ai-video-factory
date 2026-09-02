#!/usr/bin/env python3
"""Recover an ALREADY-SUBMITTED fal.ai video job by its provider job id -
checks its status and downloads the result if it's ready. This NEVER
submits a new generation job and NEVER re-generates the reference image;
it is strictly a check/download tool for a job that was already paid for,
meant for exactly this situation: scripts/run_first_fal_test.py (or a
future script built the same way) submitted a job successfully, printed
its provider job id, and then failed before it could download the result
(e.g. a status-check bug, a dropped connection, closing the terminal).

Usage (from the repo root, with FAL_API_KEY set in your .env):
    python -m scripts.recover_fal_video_job <provider_job_id>
    python -m scripts.recover_fal_video_job <provider_job_id> --standard   (only if the ORIGINAL job used Wan standard, not Turbo)
    python -m scripts.recover_fal_video_job <provider_job_id> --out path\to\clip.mp4

Safe to re-run: every run only checks status (free) and, if the job is
already COMPLETED, downloads it again. It never creates a new job, so
running it five times costs the same as running it once.
"""
import argparse
import sys
import time
from pathlib import Path

from app.config import settings
from app.providers.base import ProviderJobState, VideoProviderError
from app.providers.video.fal import WAN_STANDARD, WAN_TURBO, FalVideoProvider

POLL_INTERVAL_SECONDS = 3
MAX_WAIT_SECONDS = 300  # if hit, just re-run this same command again later

DEFAULT_OUTPUT_DIR = Path(__file__).resolve().parent.parent / "data" / "fal_test"


def fail(message: str) -> None:
    print(f"\nSTOPPED: {message}")
    print("No new job was submitted, and this script did not retry on its own.")
    sys.exit(1)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Check/download an already-submitted fal.ai video job. Never submits a new job."
    )
    parser.add_argument("provider_job_id", help="The fal.ai request id printed by the original submission")
    parser.add_argument(
        "--standard",
        action="store_true",
        help="The ORIGINAL job used Wan 2.2 A14B standard, not Turbo (only set this if that's what you actually ran)",
    )
    parser.add_argument(
        "--out", type=Path, default=None, help="Where to save the downloaded clip (default: data/fal_test/clip.mp4)"
    )
    args = parser.parse_args()

    model_config = WAN_STANDARD if args.standard else WAN_TURBO
    video_path = args.out or (DEFAULT_OUTPUT_DIR / "clip.mp4")

    key_preview = f"{settings.fal_api_key[:6]}..." if settings.fal_api_key else None
    print(f"FAL_API_KEY loaded from .env: {'yes (' + key_preview + ')' if key_preview else 'NO'}")
    if not settings.fal_api_key:
        fail("FAL_API_KEY is not set. Add FAL_API_KEY=your_key_here to your .env file and try again.")

    print("=" * 70)
    print("RECOVERING AN EXISTING fal.ai VIDEO JOB - no new job will be submitted")
    print("=" * 70)
    print(f"Provider job id: {args.provider_job_id}")
    print(f"Model:           {model_config.base_model_id}"
          + (f" (originally submitted via subpath {model_config.subpath!r})" if model_config.subpath else ""))
    print(f"Output path:     {video_path}")
    print("=" * 70)

    video_provider = FalVideoProvider(model_config)

    t0 = time.monotonic()
    result = None
    while True:
        elapsed = time.monotonic() - t0
        if elapsed > MAX_WAIT_SECONDS:
            fail(
                f"Gave up after {elapsed:.0f}s of checking. The job may still complete on fal.ai's side - "
                f"just re-run this exact same command later:\n"
                f"      python -m scripts.recover_fal_video_job {args.provider_job_id}"
                + (" --standard" if args.standard else "")
            )
        try:
            result = video_provider.get_job_status(args.provider_job_id)
        except VideoProviderError as e:
            fail(f"Status check failed: {e}")

        if result.status == ProviderJobState.PROCESSING:
            print(f"      ...still processing ({elapsed:.0f}s elapsed)")
            time.sleep(POLL_INTERVAL_SECONDS)
            continue
        break

    if result.status == ProviderJobState.FAILED:
        fail(f"Provider reported generation failure: {result.error_message}")

    print(f"Status: COMPLETED after {elapsed:.0f}s of checking.")

    try:
        video_provider.download_result(args.provider_job_id, result.output_url, str(video_path))
    except VideoProviderError as e:
        fail(
            f"Download failed (the video did complete and was already billed - only the local save "
            f"failed, safe to just re-run this same command to try the download again): {e}"
        )

    print("\n" + "=" * 70)
    print("DONE")
    print("=" * 70)
    print(f"Video saved to: {video_path}")
    if result.actual_cost_usd is not None:
        print(f"Cost reported by fal.ai: ${result.actual_cost_usd:.4f}")
    else:
        print(
            "fal.ai's response didn't include a per-request cost figure. Wan Turbo bills a flat "
            "$0.05 at 480p regardless (per fal.ai's own pricing) - confirm the exact charge at "
            "https://fal.ai/dashboard/billing."
        )


if __name__ == "__main__":
    main()
