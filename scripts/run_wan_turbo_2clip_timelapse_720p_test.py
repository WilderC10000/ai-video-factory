#!/usr/bin/env python3
"""WAN TURBO 720p 2-CLIP TIMELAPSE TEST: a controlled, apples-to-apples
comparison against the already-completed 480p 2-clip test - the ONLY
intended variable is resolution (480p -> 720p, $0.05 -> $0.10 per clip).
Everything else (source image, two-clip structure, last-frame propagation,
prompts, camera/builder behavior, frame count) is held identical.

`CLIP_1_PROMPT` and `CLIP_2_PROMPT` are imported directly from
`scripts.run_wan_turbo_2clip_timelapse_test` (the 480p script) rather than
retyped here, so the two experiments are guaranteed to use byte-identical
prompt text - the whole point of a controlled comparison would be
undermined by a copy-paste drift between the two.

Re-verified before writing this script: `fal-ai/wan/v2.2-a14b/image-to-video/turbo`
at 720p is $0.10/video flat (matches this project's existing
`WAN_TURBO.price_by_resolution["720p"]` - no config change needed). The
`num_frames` behavior (81-100 inclusive, default 81, >81 billing at
1.25x) already pinned in `WAN_TURBO`'s config applies the same way
regardless of resolution tier, so `num_frames: 81` still keeps this at
the flat rate.

Clip 1: generated from the already-approved
`data/fal_mechanical_start_test/mechanical_start_frame.jpg` - identical
source to the 480p test.

Clip 2: generated from clip 1's OWN LAST FRAME, extracted locally with
ffmpeg (`app/services/frame_extraction.extract_last_frame`) - not a new
image generation, same continuity method as the 480p test.

Outputs land in their own dedicated directory
(`data/fal_wan_turbo_2clip_720p_timelapse_test/`) so the 480p results are
never overwritten - both remain on disk for direct side-by-side review.

Safety, same pattern as every other real-call script in this repo:
  - Exactly 2 video calls, 81 frames each, 720p - hard-coded. Zero
    image-generation calls (clip 2's source is a local ffmpeg frame
    extraction, not an API call).
  - Total cost ($0.20 - two flat, deterministic $0.10 charges) checked
    against MAX_SPEND_USD before either call; one "type yes" confirmation
    gates the whole run.
  - No automatic retries - any failure stops the script immediately,
    printing a `recover_fal_video_job.py <job_id>` hint for any clip
    already submitted.
  - manifest.json records both clips' exact prompt, cost, job id, and
    output path, plus the extracted mid-sequence frame and the final
    concatenated review file.

Usage (from the repo root, with FAL_API_KEY set in your .env and ffmpeg
on PATH, AFTER scripts/run_mechanical_start_frame_test.py has already
been run and its frame approved):
    python -m scripts.run_wan_turbo_2clip_timelapse_720p_test
    python -m scripts.run_wan_turbo_2clip_timelapse_720p_test --yes
"""
import argparse
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

from app.config import settings
from app.providers.base import ProviderJobState, VideoGenerationRequest, VideoProviderError
from app.providers.video.fal import WAN_TURBO, FalVideoProvider
from app.services.frame_extraction import FrameExtractionError, extract_last_frame
from app.services.video_assembly import VideoAssemblyError, concatenate_videos
from scripts.run_wan_turbo_2clip_timelapse_test import CLIP_1_PROMPT, CLIP_2_PROMPT, SUCCESS_CRITERIA

MAX_SPEND_USD = 0.20  # two flat $0.10 charges - deterministic, zero margin needed
ASPECT_RATIO = "9:16"
RESOLUTION = "720p"  # the ONLY intended difference from the 480p test
NUM_FRAMES = 81  # ~5.06s @ 16fps each - identical to the 480p test
POLL_INTERVAL_SECONDS = 3
MAX_WAIT_SECONDS = 180

SOURCE_DIR = Path(__file__).resolve().parent.parent / "data" / "fal_mechanical_start_test"
SOURCE_MANIFEST_PATH = SOURCE_DIR / "manifest.json"

OUTPUT_DIR = Path(__file__).resolve().parent.parent / "data" / "fal_wan_turbo_2clip_720p_timelapse_test"
MANIFEST_PATH = OUTPUT_DIR / "manifest.json"


def fail(message: str) -> None:
    print(f"\nSTOPPED: {message}")
    print(f"No retry, no alternate model - the script is exiting now. Manifest: {MANIFEST_PATH}")
    sys.exit(1)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def save_manifest(manifest: dict) -> None:
    MANIFEST_PATH.parent.mkdir(parents=True, exist_ok=True)
    MANIFEST_PATH.write_text(json.dumps(manifest, indent=2))


def load_clip1_source_image() -> str:
    """Same reuse pattern as the 480p test - reads the approved mechanical
    start frame's path out of its own manifest.json."""
    if not SOURCE_MANIFEST_PATH.exists():
        fail(
            f"Source manifest not found at {SOURCE_MANIFEST_PATH}. This experiment reuses the "
            "approved mechanical_start_frame.jpg - run scripts/run_mechanical_start_frame_test.py first."
        )
    source_manifest = json.loads(SOURCE_MANIFEST_PATH.read_text())
    output_path = source_manifest.get("output_path")
    if not output_path:
        fail(f"Manifest at {SOURCE_MANIFEST_PATH} has no output_path recorded.")
    image_path = Path(output_path)
    if not image_path.exists() or image_path.stat().st_size == 0:
        fail(f"Approved source image not found (or empty) at {image_path}.")
    return str(image_path)


def generate_one_clip(provider: FalVideoProvider, label: str, prompt: str, source_image_path: str, video_path: Path):
    """Submit + poll + download exactly one clip. Returns (submitted, actual_cost_usd).
    Calls fail() (exits) on any error - no retries."""
    request = VideoGenerationRequest(
        prompt=prompt,
        reference_image_path=source_image_path,
        aspect_ratio=ASPECT_RATIO,
        extra_params={"resolution": RESOLUTION},
    )

    print(f"\n[{label}] Submitting (source: {source_image_path})...")
    t_submit = time.monotonic()
    try:
        submitted = provider.submit_video_job(request)
    except VideoProviderError as e:
        fail(f"{label}: submission failed: {e}")
    print(f"        Submitted. Provider job id: {submitted.provider_job_id} "
          f"(estimated ${submitted.estimated_cost_usd:.4f})")

    print(f"        Polling (no retries on error - any failure stops the whole script)...")
    result = None
    while True:
        elapsed = time.monotonic() - t_submit
        if elapsed > MAX_WAIT_SECONDS:
            fail(
                f"{label}: gave up after {elapsed:.0f}s waiting (job may still complete and be "
                f"billed on fal.ai's side - check https://fal.ai/dashboard/billing). To check on "
                f"it later without spending anything again, run:\n"
                f"      python -m scripts.recover_fal_video_job {submitted.provider_job_id}"
            )
        try:
            result = provider.get_job_status(submitted.provider_job_id, meta=submitted.meta)
        except VideoProviderError as e:
            fail(
                f"{label}: status check failed: {e}\n"
                f"      To check on it later without spending anything again, run:\n"
                f"      python -m scripts.recover_fal_video_job {submitted.provider_job_id}"
            )
        if result.status == ProviderJobState.PROCESSING:
            print(f"        ...still processing ({elapsed:.0f}s elapsed)")
            time.sleep(POLL_INTERVAL_SECONDS)
            continue
        break

    if result.status == ProviderJobState.FAILED:
        fail(f"{label}: provider reported generation failure: {result.error_message}")

    try:
        provider.download_result(submitted.provider_job_id, result.output_url, str(video_path))
    except VideoProviderError as e:
        fail(
            f"{label}: download failed (already billed, only the local save failed): {e}\n"
            f"      To retry just the download, run:\n"
            f"      python -m scripts.recover_fal_video_job {submitted.provider_job_id}"
        )

    actual_cost = result.actual_cost_usd if result.actual_cost_usd is not None else submitted.estimated_cost_usd
    print(f"        Completed -> {video_path} (${actual_cost:.4f})")
    return submitted, actual_cost


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Wan Turbo 720p 2-clip timelapse test: controlled comparison against the 480p 2-clip test."
    )
    parser.add_argument("--yes", action="store_true", help="Skip the 'type yes' confirmation prompt")
    args = parser.parse_args()

    key_preview = f"{settings.fal_api_key[:6]}..." if settings.fal_api_key else None
    print(f"FAL_API_KEY loaded from .env: {'yes (' + key_preview + ')' if key_preview else 'NO'}")
    if not settings.fal_api_key:
        fail("FAL_API_KEY is not set. Add FAL_API_KEY=your_key_here to your .env file and try again.")

    clip1_source_path = load_clip1_source_image()
    provider = FalVideoProvider(WAN_TURBO)
    per_clip_cost = provider.estimate_cost(
        VideoGenerationRequest(prompt="p", extra_params={"resolution": RESOLUTION})
    )
    total_cost = round(per_clip_cost * 2, 4)

    clip1_path = OUTPUT_DIR / "clip1.mp4"
    clip2_path = OUTPUT_DIR / "clip2.mp4"
    extracted_frame_path = OUTPUT_DIR / "clip1_last_frame.jpg"
    combined_path = OUTPUT_DIR / "combined_review.mp4"

    print("=" * 70)
    print("WAN TURBO 720p 2-CLIP TIMELAPSE TEST - THIS WILL SPEND REAL MONEY")
    print("=" * 70)
    print("Controlled comparison against the completed 480p 2-clip test - only resolution differs.")
    print(f"\nClip 1 source (reused, $0 image cost): {clip1_source_path}")
    print(f"\nClip 1 prompt (identical to the 480p test):\n  {CLIP_1_PROMPT}")
    print(f"\nClip 2 source: clip 1's own last frame, extracted locally with ffmpeg (no image call)")
    print(f"\nClip 2 prompt (identical to the 480p test):\n  {CLIP_2_PROMPT}")
    print(f"\nModel: {WAN_TURBO.submit_path}   Resolution: {RESOLUTION}   num_frames: {NUM_FRAMES} each")
    print("Audio: none (this endpoint has no native audio capability)")
    print(f"\nEstimated cost: 2 x ${per_clip_cost:.4f} = ${total_cost:.4f}")
    print(f"Hard cap:       ${MAX_SPEND_USD:.2f}")
    print("Rules: exactly 2 video calls, 0 image calls, 0 retries, 0 alternate models.")
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
        "experiment": "wan_turbo_2clip_720p_timelapse",
        "compared_against": "wan_turbo_2clip_timelapse (480p)",
        "model": WAN_TURBO.submit_path,
        "resolution": RESOLUTION,
        "num_frames": NUM_FRAMES,
        "aspect_ratio": ASPECT_RATIO,
        "max_spend_usd": MAX_SPEND_USD,
        "estimated_total_cost_usd": total_cost,
        "clip1": {
            "source_image_path": clip1_source_path,
            "reused_from_manifest": str(SOURCE_MANIFEST_PATH),
            "prompt": CLIP_1_PROMPT,
            "video_path": None,
            "provider_job_id": None,
            "actual_cost_usd": None,
        },
        "clip1_last_frame_path": None,
        "clip2": {
            "source_image_path": None,
            "prompt": CLIP_2_PROMPT,
            "video_path": None,
            "provider_job_id": None,
            "actual_cost_usd": None,
        },
        "combined_review_path": None,
        "actual_total_cost_usd": None,
        "completed_at": None,
    }
    save_manifest(manifest)

    # --- Clip 1 ---------------------------------------------------------
    submitted1, cost1 = generate_one_clip(provider, "clip1", CLIP_1_PROMPT, clip1_source_path, clip1_path)
    manifest["clip1"]["video_path"] = str(clip1_path)
    manifest["clip1"]["provider_job_id"] = submitted1.provider_job_id
    manifest["clip1"]["actual_cost_usd"] = cost1
    save_manifest(manifest)

    # --- Extract clip 1's last frame locally (no API call) --------------
    print(f"\n[extract] Extracting clip 1's last frame -> {extracted_frame_path.name} (local ffmpeg, $0)...")
    try:
        extract_last_frame(clip1_path, extracted_frame_path)
    except FrameExtractionError as e:
        fail(f"frame extraction from clip1 failed: {e}")
    print(f"          Done -> {extracted_frame_path}")
    manifest["clip1_last_frame_path"] = str(extracted_frame_path)
    manifest["clip2"]["source_image_path"] = str(extracted_frame_path)
    save_manifest(manifest)

    # --- Clip 2 -----------------------------------------------------------
    submitted2, cost2 = generate_one_clip(
        provider, "clip2", CLIP_2_PROMPT, str(extracted_frame_path), clip2_path
    )
    manifest["clip2"]["video_path"] = str(clip2_path)
    manifest["clip2"]["provider_job_id"] = submitted2.provider_job_id
    manifest["clip2"]["actual_cost_usd"] = cost2
    save_manifest(manifest)

    # --- Concatenate for review (local ffmpeg, $0) -----------------------
    print(f"\n[concat] Concatenating clip1 + clip2 -> {combined_path.name} (local ffmpeg, $0)...")
    try:
        concatenate_videos([clip1_path, clip2_path], combined_path)
    except VideoAssemblyError as e:
        fail(f"concatenation failed (both clips already generated and billed, only the review file failed): {e}")
    print(f"         Done -> {combined_path}")

    actual_total = round(cost1 + cost2, 4)
    manifest["combined_review_path"] = str(combined_path)
    manifest["actual_total_cost_usd"] = actual_total
    manifest["completed_at"] = _now()
    save_manifest(manifest)

    print("\n" + "=" * 70)
    print("DONE - 2 clips generated and concatenated. No further generation will happen automatically.")
    print("=" * 70)
    print(f"clip1:            {clip1_path}  (${cost1:.4f})")
    print(f"clip1_last_frame: {extracted_frame_path}")
    print(f"clip2:            {clip2_path}  (${cost2:.4f})")
    print(f"combined_review:  {combined_path}")
    print(f"Total actual cost: ${actual_total:.4f}")
    print(f"Manifest: {MANIFEST_PATH}")
    print("\nCompare this combined_review.mp4 directly against")
    print("data/fal_wan_turbo_2clip_timelapse_test/combined_review.mp4 (the 480p version).")
    print("Question to answer: does $0.10 instead of $0.05 buy enough visible improvement to")
    print("make 720p the production workhorse tier? Review against the success criteria:")
    for item in SUCCESS_CRITERIA:
        print(f"  - {item}")


if __name__ == "__main__":
    main()
