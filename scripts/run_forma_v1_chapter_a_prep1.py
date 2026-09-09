#!/usr/bin/env python3
"""FORMA VIDEO #1 - CHAPTER A, STAGE A2: SITE PREP CLIP 1.

Only runnable after Stage A1 (Hook) has been generated AND approved by
you - this script requires hook_raw.mp4 to already exist, and additionally
asks you to explicitly confirm you've reviewed and approved it (a
separate confirmation from the cost confirmation below) before it submits
anything. This double gate exists specifically so a failed or unreviewed
Hook can never automatically trigger this paid generation - checked
BEFORE any spend, not caught after the fact.

Starting image is the REAL last frame of Stage A1's raw output
(hook_raw.mp4), extracted locally via extract_last_frame() - pure ffmpeg,
free, no API call. hook_raw.mp4 is only ever read, never modified. Same
camera as the Hook (CAMERA_CLAUSE_A, imported unchanged from
run_forma_v1_chapter_a_hook - no camera change within Camera Chapter A).

Visual-only prompt - no audio instructions of any kind, per explicit
instruction. Wan runs with no audio field regardless; sound is an
entirely separate later post-production layer.

REDESIGNED per the permanent FORMA Site Prep Rule (the original
hand-clearing version was rejected: visual quality was good, but "pick up
one rock" did not read as meaningful site preparation). Every prep clip
must now show (1) a clear physical obstacle, (2) a clear tool/machine
matched to it, (3) visible removal/transformation of that obstacle, and
(4) a clearly more buildable site by the end - never vague hand-clearing.
For Waterfall Cave, that's a compact tracked mini excavator, operated by
the builder, scraping loose rock/mud/debris and depositing it in a
visible pile to one side.

Makes exactly ONE Wan 3.0 video call. No retries. Does NOT chain to Stage
A3 (Prep 2) - that is a separate script, run only after this stage's own
output is reviewed and approved.

Safety, same pattern as every other real-call script in this repo:
  - Exactly 1 video-generation call. No image call, no retry, no chaining
    to any other stage.
  - Hard cap set exactly equal to the computed cost ($0.35) - zero
    margin.
  - Job state saved to disk immediately after submission.

Usage (from the repo root, with FAL_API_KEY set in your .env, and
hook_raw.mp4 already generated and reviewed):
    python -m scripts.run_forma_v1_chapter_a_prep1
    python -m scripts.run_forma_v1_chapter_a_prep1 --yes   (skips only the cost confirmation - the upstream-approval confirmation always runs)
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
from scripts.run_forma_v1_chapter_a_hook import (
    ASPECT_RATIO,
    CAMERA_CLAUSE_A,
    HOOK_RAW_PATH,
    MANIFEST_PATH,
    OUTPUT_DIR,
    RESOLUTION,
)

MAX_SPEND_USD = 0.35
DURATION_SECONDS = 7.0
POLL_INTERVAL_SECONDS = 3
MAX_WAIT_SECONDS = 300

PREP1_START_FRAME_PATH = OUTPUT_DIR / "site_prep_clip1_start_frame.jpg"
PREP1_RAW_PATH = OUTPUT_DIR / "site_prep_clip1_raw.mp4"
JOB_STATE_PATH = OUTPUT_DIR / "prep1_last_job.json"

# Visual-only - no audio instructions, per explicit instruction. Redesigned
# around the permanent FORMA Site Prep Rule: every prep stage must show a
# clear physical obstacle, a clear tool/machine matched to it, visible
# removal/transformation of that obstacle, and a clearly more buildable
# site by the end - never vague hand-clearing or symbolic actions. For
# Waterfall Cave, that means a compact tracked mini excavator (operated by
# the builder) doing the clearing, not manual hand-clearing.
PREP1_PROMPT = (
    "Vertical 9:16, realistic construction footage, documentary/observational style. "
    f"{CAMERA_CLAUSE_A} No camera movement, no angle change - continuing directly from the "
    "current state shown in the starting image.\n\n"
    "The ground beneath the overhang is rough, natural, and clearly not yet buildable: loose "
    "rock, mud, and plant debris cover the intended build area. The builder walks to a compact "
    "tracked mini excavator waiting at the edge of the site, climbs into it, and starts the "
    "machine. He operates it to clear the ground: the excavator's arm swings its toothed bucket "
    "into the loose rock, mud, and debris directly in front of it, scoops up a load, swings to "
    "one side, and dumps it onto a growing debris pile just outside the work area, then swings "
    "back and repeats the same scoop-swing-dump motion on the next section of ground immediately "
    "adjacent to where it just worked. The machine works in one continuous direction across a "
    "single bounded section of the site - it never jumps to a different part of the site, and "
    "nothing clears itself outside the machine's active work zone. By the end of the clip, that "
    "section reads as visibly scraped down to bare, cleared earth - clearly different from the "
    "rough ground around it - with an obvious pile of removed material beside it. No structure of "
    "any kind appears yet. The builder never looks toward the camera. The waterfall remains "
    "visible and in motion beside the cave; mist continues to drift. No posing, no presenter "
    "behavior."
)

WAN_3_0_FORMA_V1_PREP1 = dataclasses.replace(WAN_3_0_STANDARD, extra_payload={"duration": 7})


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

    if not HOOK_RAW_PATH.exists():
        fail(
            f"{HOOK_RAW_PATH} not found - Stage A1 (Hook) has not been generated yet. "
            "Run scripts/run_forma_v1_chapter_a_hook.py first."
        )

    # Mandatory upstream-approval gate - NOT the same as the cost
    # confirmation below, and not skippable by --yes. A failed or
    # unreviewed Hook must never be able to trigger this paid generation.
    print(f"\nUpstream file found: {HOOK_RAW_PATH}")
    approval = input(
        "Have you reviewed and approved hook_raw.mp4? Type 'yes' to confirm before proceeding "
        "(anything else stops here, nothing generated): "
    ).strip().lower()
    if approval != "yes":
        print("Stopped - Hook was not confirmed as approved. Nothing was generated.")
        sys.exit(0)

    print(f"\n[1/2] Extracting the real last frame of hook_raw.mp4 locally (no API call)...")
    try:
        extract_last_frame(HOOK_RAW_PATH, PREP1_START_FRAME_PATH)
    except FrameExtractionError as e:
        fail(f"Frame extraction failed: {e}")
    print(f"      Done -> {PREP1_START_FRAME_PATH} (hook_raw.mp4 was only read, never modified)")

    video_provider = FalVideoProvider(WAN_3_0_FORMA_V1_PREP1)
    video_request = VideoGenerationRequest(
        prompt=PREP1_PROMPT,
        reference_image_path=str(PREP1_START_FRAME_PATH),
        aspect_ratio=ASPECT_RATIO,
        duration_seconds=DURATION_SECONDS,
        extra_params={"resolution": RESOLUTION},
    )
    video_cost = video_provider.estimate_cost(video_request)

    print("=" * 70)
    print("FORMA VIDEO #1 - CHAPTER A - STAGE A2 (SITE PREP CLIP 1) - THIS WILL SPEND REAL MONEY")
    print("=" * 70)
    print(f"Video model: {WAN_3_0_FORMA_V1_PREP1.submit_path}  ({RESOLUTION}, {ASPECT_RATIO}, {DURATION_SECONDS:.0f}s)")
    print(f"Source image: {PREP1_START_FRAME_PATH} (real extracted pixels from Hook's raw output)")
    print(f"\nVideo prompt:\n  {PREP1_PROMPT}")
    print(f"\nEstimated cost: ${video_cost:.4f}")
    print(f"Hard cap:       ${MAX_SPEND_USD:.2f}")
    print("Rules: exactly 1 video call, no retries, no chaining to Prep 2 - this stage stops here.")
    print("=" * 70)

    if video_cost > MAX_SPEND_USD:
        fail(f"Estimated cost ${video_cost:.4f} exceeds the ${MAX_SPEND_USD:.2f} cap. Nothing was generated.")

    if not skip_confirm:
        answer = input(f"\nType 'yes' to spend up to ${video_cost:.4f} and proceed: ").strip().lower()
        if answer != "yes":
            print("Cancelled. Nothing was generated.")
            sys.exit(0)

    manifest = load_manifest()
    manifest["prep1"] = {
        "video_model": WAN_3_0_FORMA_V1_PREP1.submit_path,
        "resolution": RESOLUTION,
        "aspect_ratio": ASPECT_RATIO,
        "duration_seconds": DURATION_SECONDS,
        "video_prompt": PREP1_PROMPT,
        "start_frame_path": str(PREP1_START_FRAME_PATH),
        "max_spend_usd": MAX_SPEND_USD,
        "estimated_cost_usd": video_cost,
        "raw_video_path": None,
        "actual_cost_usd": None,
        "completed_at": None,
    }
    save_manifest(manifest)

    print(f"\n[2/2] Submitting Site Prep Clip 1 video generation job (Wan 3.0 standard, {RESOLUTION})...")
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
        video_provider.download_result(submitted.provider_job_id, result.output_url, str(PREP1_RAW_PATH))
    except VideoProviderError as e:
        fail(
            f"Download failed (generation already succeeded and was billed, but the local save failed): {e}\n"
            f"      To retry just the download without spending anything again, run:\n"
            f"      python -m scripts.recover_fal_video_job {submitted.provider_job_id}"
        )

    actual_cost = result.actual_cost_usd if result.actual_cost_usd is not None else submitted.estimated_cost_usd

    manifest["prep1"]["raw_video_path"] = str(PREP1_RAW_PATH)
    manifest["prep1"]["actual_cost_usd"] = actual_cost
    manifest["prep1"]["completed_at"] = _now()
    save_manifest(manifest)

    print("\n" + "=" * 70)
    print("STAGE A2 (SITE PREP CLIP 1) DONE - stopping completely, as required.")
    print("=" * 70)
    print(f"Site Prep Clip 1 raw: {PREP1_RAW_PATH}")
    print(f"Actual cost:          ${actual_cost:.4f}")
    print(f"Manifest:             {MANIFEST_PATH}")
    print("\nSTOP HERE. Review site_prep_clip1_raw.mp4 against the FORMA Site Prep Rule:")
    print("  - a clear physical obstacle is shown (rough ground: loose rock, mud, debris)")
    print("  - a clear tool/machine matched to it is shown (compact tracked mini excavator)")
    print("  - visible removal/transformation: scoop-swing-dump cycle, growing debris pile")
    print("  - the worked section reads as clearly more buildable (bare cleared earth) by the end")
    print("  - continues directly from Hook's real last frame - no reset")
    print("  - machine works in one clear spatial direction - nothing clears itself elsewhere")
    print("  - no construction of any kind begins yet")
    print("  - camera framing identical to the Hook - no drift")
    print("  - builder never looks toward the camera")
    print("\nDo NOT run Stage A3 (Prep 2) until you have reviewed and approved this clip.")
    print("Stage A3 is scripts/run_forma_v1_chapter_a_prep2.py - a separate script, not run automatically.")


if __name__ == "__main__":
    main()
