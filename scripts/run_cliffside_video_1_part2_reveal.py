#!/usr/bin/env python3
"""CLIFFSIDE VIDEO #1, PART 2 - SHOT 4: FINAL REVEAL.

Only runnable after Shot 3 (Final Detail) has been generated AND
approved - requires final_detail_raw.mp4 to already exist, and
additionally asks you to explicitly confirm you've reviewed and approved
it before submitting anything. final_detail_raw.mp4 is only ever read,
never modified.

Starting image is the REAL last frame of final_detail_raw.mp4, extracted
locally via extract_last_frame() - pure ffmpeg, free, no API call. NO
Nano Banana Pro edit is used immediately before this shot, per the
already-locked safest-reveal method: risking the completed structure
through an edit right before the payoff is exactly the failure mode that
rule exists to avoid.

Makes exactly ONE Wan 3.0 video call (an in-generation camera pull-back,
not an edit). No retries. This is Part 2's final stage - no downstream
chaining.

Usage (from the repo root, with FAL_API_KEY set in your .env, and
final_detail_raw.mp4 already generated and reviewed):
    python -m scripts.run_cliffside_video_1_part2_reveal
    python -m scripts.run_cliffside_video_1_part2_reveal --yes   (skips only the cost confirmation - the upstream-approval confirmation always runs)
"""
import dataclasses
import json
import sys
import time
from datetime import datetime, timezone

from app.config import settings
from app.providers.base import ProviderJobState, VideoGenerationRequest, VideoProviderError
from app.providers.video.fal import WAN_3_0_STANDARD, FalVideoProvider
from app.services.frame_extraction import FrameExtractionError, extract_last_frame
from scripts.run_cliffside_video_1_part2_final_detail import FINAL_DETAIL_RAW_PATH
from scripts.run_cliffside_video_1_rough_assembly import MANIFEST_PATH, OUTPUT_DIR

ASPECT_RATIO = "9:16"
RESOLUTION = "480p"
MAX_SPEND_USD = 0.35
DURATION_SECONDS = 7.0
POLL_INTERVAL_SECONDS = 3
MAX_WAIT_SECONDS = 300

REVEAL_START_FRAME_PATH = OUTPUT_DIR / "reveal_start_frame.jpg"
REVEAL_RAW_PATH = OUTPUT_DIR / "reveal_raw.mp4"
JOB_STATE_PATH = OUTPUT_DIR / "reveal_last_job.json"

# Visual-only - no audio instructions. No construction of any kind - this
# is a pure camera move, near real-time, from the real last frame of
# Final Detail. Environment and structure both get real compositional
# weight; builder is small/secondary, never presenting to camera.
REVEAL_PROMPT = (
    "Vertical 9:16, realistic documentary-style footage, near real-time pace. Continuing directly "
    "from the current state shown in the starting image - no further construction of any kind.\n\n"
    "The camera performs a slow, continuous pull-back and widening movement from its current "
    "position, smoothly revealing progressively more of the scene: the entire completed cabin on "
    "its platform, the full platform itself, the cliff edge, the ocean horizon, and the "
    "surrounding coastline, all in warm late-day light. By the end of the movement, the cabin "
    "occupies roughly 35 to 50 percent of the vertical frame - present and clearly the subject, "
    "but not dominating the image - with the ocean, cliff, and coastline sharing real visual "
    "weight alongside it. The builder is small in the frame, positioned off to one side, either "
    "standing naturally or walking away from the camera - he never turns to face or present to "
    "the camera. Nothing about the cabin changes during this shot. No posing, no presenter "
    "behavior."
)

WAN_3_0_CLIFFSIDE_REVEAL = dataclasses.replace(WAN_3_0_STANDARD, extra_payload={"duration": 7})


def fail(message: str) -> None:
    print(f"\nSTOPPED: {message}")
    print("No retry, no further generation - the script is exiting now.")
    sys.exit(1)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def load_manifest() -> dict:
    if MANIFEST_PATH.exists():
        return json.loads(MANIFEST_PATH.read_text())
    return {"experiment": "cliffside_video_1", "created_at": _now()}


def save_manifest(manifest: dict) -> None:
    MANIFEST_PATH.parent.mkdir(parents=True, exist_ok=True)
    MANIFEST_PATH.write_text(json.dumps(manifest, indent=2))


def main() -> None:
    skip_confirm = "--yes" in sys.argv[1:]

    key_preview = f"{settings.fal_api_key[:6]}..." if settings.fal_api_key else None
    print(f"FAL_API_KEY loaded from .env: {'yes (' + key_preview + ')' if key_preview else 'NO'}")
    if not settings.fal_api_key:
        fail("FAL_API_KEY is not set. Add FAL_API_KEY=your_key_here to your .env file and try again.")

    if not FINAL_DETAIL_RAW_PATH.exists():
        fail(
            f"{FINAL_DETAIL_RAW_PATH} not found - Shot 3 (Final Detail) has not been generated "
            "yet. Run scripts/run_cliffside_video_1_part2_final_detail.py first."
        )

    print(f"\nUpstream file found: {FINAL_DETAIL_RAW_PATH}")
    approval = input(
        "Have you reviewed and approved final_detail_raw.mp4? Type 'yes' to confirm before "
        "proceeding (anything else stops here, nothing generated): "
    ).strip().lower()
    if approval != "yes":
        print("Stopped - Final Detail was not confirmed as approved. Nothing was generated.")
        sys.exit(0)

    print("\n[1/2] Extracting the real last frame of final_detail_raw.mp4 locally (no API call)...")
    try:
        extract_last_frame(FINAL_DETAIL_RAW_PATH, REVEAL_START_FRAME_PATH)
    except FrameExtractionError as e:
        fail(f"Frame extraction failed: {e}")
    print(f"      Done -> {REVEAL_START_FRAME_PATH} (final_detail_raw.mp4 was only read, never modified)")

    video_provider = FalVideoProvider(WAN_3_0_CLIFFSIDE_REVEAL)
    video_request = VideoGenerationRequest(
        prompt=REVEAL_PROMPT,
        reference_image_path=str(REVEAL_START_FRAME_PATH),
        aspect_ratio=ASPECT_RATIO,
        duration_seconds=DURATION_SECONDS,
        extra_params={"resolution": RESOLUTION},
    )
    video_cost = video_provider.estimate_cost(video_request)

    print("=" * 70)
    print("CLIFFSIDE VIDEO #1 - PART 2 - SHOT 4 (FINAL REVEAL) - THIS WILL SPEND REAL MONEY")
    print("=" * 70)
    print(f"Video model: {WAN_3_0_CLIFFSIDE_REVEAL.submit_path}  ({RESOLUTION}, {ASPECT_RATIO}, {DURATION_SECONDS:.0f}s)")
    print(f"Source image: {REVEAL_START_FRAME_PATH} (real extracted pixels from Final Detail's raw output)")
    print(f"\nVideo prompt:\n  {REVEAL_PROMPT}")
    print(f"\nEstimated cost: ${video_cost:.4f}")
    print(f"Hard cap:       ${MAX_SPEND_USD:.2f}")
    print("Rules: exactly 1 video call, no retries - this is Part 2's final stage.")
    print("=" * 70)

    if video_cost > MAX_SPEND_USD:
        fail(f"Estimated cost ${video_cost:.4f} exceeds the ${MAX_SPEND_USD:.2f} cap. Nothing was generated.")

    if not skip_confirm:
        answer = input(f"\nType 'yes' to spend up to ${video_cost:.4f} and proceed: ").strip().lower()
        if answer != "yes":
            print("Cancelled. Nothing was generated.")
            sys.exit(0)

    manifest = load_manifest()
    manifest["reveal"] = {
        "video_model": WAN_3_0_CLIFFSIDE_REVEAL.submit_path,
        "resolution": RESOLUTION,
        "aspect_ratio": ASPECT_RATIO,
        "duration_seconds": DURATION_SECONDS,
        "video_prompt": REVEAL_PROMPT,
        "start_frame_path": str(REVEAL_START_FRAME_PATH),
        "max_spend_usd": MAX_SPEND_USD,
        "estimated_cost_usd": video_cost,
        "raw_video_path": None,
        "actual_cost_usd": None,
        "completed_at": None,
    }
    save_manifest(manifest)

    print(f"\n[2/2] Submitting Final Reveal video generation job (Wan 3.0 standard, {RESOLUTION})...")
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
        video_provider.download_result(submitted.provider_job_id, result.output_url, str(REVEAL_RAW_PATH))
    except VideoProviderError as e:
        fail(
            f"Download failed (generation already succeeded and was billed, but the local save failed): {e}\n"
            f"      To retry just the download without spending anything again, run:\n"
            f"      python -m scripts.recover_fal_video_job {submitted.provider_job_id}"
        )

    actual_cost = result.actual_cost_usd if result.actual_cost_usd is not None else submitted.estimated_cost_usd

    manifest["reveal"]["raw_video_path"] = str(REVEAL_RAW_PATH)
    manifest["reveal"]["actual_cost_usd"] = actual_cost
    manifest["reveal"]["completed_at"] = _now()
    save_manifest(manifest)

    print("\n" + "=" * 70)
    print("SHOT 4 (FINAL REVEAL) DONE - Part 2 complete.")
    print("=" * 70)
    print(f"Reveal raw:  {REVEAL_RAW_PATH}")
    print(f"Actual cost: ${actual_cost:.4f}")
    print(f"Manifest:    {MANIFEST_PATH}")
    print("\nSTOP HERE. Review reveal_raw.mp4 against:")
    print("  1. smooth, continuous pull-back/widening move, near real-time pace")
    print("  2. cabin occupies roughly 35-50% of the vertical frame by the end - not dominating")
    print("  3. cliff, ocean, coastline, and golden-hour light share real visual weight")
    print("  4. builder small/secondary, never presenting to camera")
    print("  5. no further construction happens - the cabin does not change")
    print("\nPart 2 is now complete. Combine with Part 1's rough assembly and this Part 2 sequence")
    print("(decking-completion edit, framing, framing-completion edit, glass, exterior-completion")
    print("edit, final detail, reveal) via local FFmpeg assembly - no further paid calls needed.")


if __name__ == "__main__":
    main()
