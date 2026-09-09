#!/usr/bin/env python3
"""VALIDATION TEST #3 - CHECKPOINT CHAINING.

Validation Test #2 (scripts/run_construction_frontier_test.py) proved the
CONSTRUCTION FRONTIER principle works within a single clip - the user
judged it good enough to pass, with 4x FFmpeg acceleration close to the
target FORMA timelapse aesthetic. This script tests the next question:
can a SECOND Wan generation continue the exact same construction
operation from the first clip's own real final frame, so that two
separately generated clips read as ONE continuous timelapse when
accelerated and concatenated - without the viewer being able to tell a
second AI generation has started?

This is the basis for eventually completing larger construction phases
through checkpoint chains (extract each clip's real last frame as the
next clip's start) instead of asking one AI generation to magically
perform an entire phase - the same mechanism already proven for
same-angle propagation in the Wan Turbo 2-clip tests, now applied to a
frontier-constrained repetitive operation specifically.

Starting image ("Clip B"'s start) is the REAL LAST FRAME of Test #2's own
RAW output - data/fal_construction_frontier_test/construction_frontier_raw.mp4
- extracted locally via extract_last_frame(), never Segment 2's original
frame and never Test #2's 4x-accelerated file (propagation must always
come from the raw, unaccelerated generation - accelerating re-times
frames, so it isn't the model's actual last output). Test #2's raw file is
only ever read, never modified.

Per explicit priority clarification: CONTINUITY across the Clip A -> Clip B
seam is the #1 success criterion, ranked above how much additional
decking Clip B completes. The video prompt is written accordingly - it
opens by naming every element that must stay visually identical to the
starting frame (existing decking, exposed joists, the frontier position,
camera/framing, structure geometry, builder appearance, site/background,
lighting) before describing the continued construction, and explicitly
states that a small amount of additional decking is entirely acceptable
if it preserves that continuity.

After the raw clip downloads, only the 4x accelerated version is produced
locally (the 2x/3x/4x speed comparison was already settled by Test #2 -
re-running it here would just be spending more to re-litigate a decided
question) via the existing app.services.video_assembly.accelerate_video().
Then Test #2's own real 4x file
(data/fal_construction_frontier_test/construction_frontier_4x.mp4, only
ever read) is concatenated with Clip B's 4x file via the existing
app.services.video_assembly.concatenate_videos() into
combined_preview_4x.mp4 - the single most important output of this test,
meant to be judged as one continuous timelapse the way a viewer would,
not as two separate technical clips.

Makes exactly ONE Wan 3.0 video call (10s, 480p, no image-generation call
of any kind). No retries. No camera change. No Segment 3 production. Does
not touch or modify Segments 1A, 1B, 2, or any Validation Test #1/#2
output file - all of those are only ever read.

Safety, same pattern as every other real-call script in this repo:
  - Exactly 1 video-generation call. No image call, no retry.
  - Hard cap set exactly equal to the computed video cost ($0.50) - zero
    margin, since Wan 3.0's per-second billing is exactly precomputable.
  - Job state saved to disk immediately after video submission, before
    polling starts, so scripts/recover_fal_video_job.py can recover it.
  - The raw downloaded clip is NEVER overwritten by the acceleration
    step - accelerate_video() itself refuses to write to its own input
    path.

Usage (from the repo root, with FAL_API_KEY set in your .env, ffmpeg on
PATH, and Test #2's construction_frontier_raw.mp4 + construction_frontier_4x.mp4
both present):
    python -m scripts.run_checkpoint_chain_test
    python -m scripts.run_checkpoint_chain_test --yes
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
from app.services.frame_extraction import FrameExtractionError, extract_last_frame
from app.services.video_assembly import VideoAssemblyError, accelerate_video, concatenate_videos
from scripts.run_full_video_segment_2_test import CAMERA_OPPOSITE_ELEVATED

MAX_SPEND_USD = 0.50  # video only - no image-generation call of any kind
RESOLUTION = "480p"
ASPECT_RATIO = "9:16"
DURATION_SECONDS = 10.0
POLL_INTERVAL_SECONDS = 3
MAX_WAIT_SECONDS = 300  # 5 minutes; see the timeout message below if this is hit
ACCELERATION_FACTOR = 4.0  # the speed question was already settled by Test #2 - not re-tested here

REPO_ROOT = Path(__file__).resolve().parent.parent

# Both READ ONLY - never modified by this script.
CLIP_A_RAW_PATH = REPO_ROOT / "data" / "fal_construction_frontier_test" / "construction_frontier_raw.mp4"
CLIP_A_4X_PATH = REPO_ROOT / "data" / "fal_construction_frontier_test" / "construction_frontier_4x.mp4"

OUTPUT_DIR = REPO_ROOT / "data" / "fal_checkpoint_chain_test"
REFERENCE_FRAME_PATH = OUTPUT_DIR / "clip_b_start_frame.jpg"
RAW_VIDEO_PATH = OUTPUT_DIR / "clip_b_raw.mp4"
CLIP_B_4X_PATH = OUTPUT_DIR / "clip_b_4x.mp4"
COMBINED_PREVIEW_PATH = OUTPUT_DIR / "combined_preview_4x.mp4"
MANIFEST_PATH = OUTPUT_DIR / "manifest.json"
JOB_STATE_PATH = OUTPUT_DIR / "last_job.json"

# Continuity across the Clip A -> Clip B seam is the #1 success criterion,
# ranked above how much additional decking Clip B completes - every
# element that must stay visually identical to the starting frame is
# named explicitly, up front, before any instruction about continuing
# the construction itself.
VIDEO_PROMPT = (
    "Vertical 9:16, realistic construction footage, documentary/observational style. "
    f"{CAMERA_OPPOSITE_ELEVATED} No camera movement, no angle change.\n\n"
    "This is a direct continuation of an ongoing right-to-left decking operation, picking up "
    "from the exact visual state shown in the starting image - not a fresh start. The following "
    "must remain visually identical to the starting image for the entire clip: every board "
    "already installed as completed decking, the exposed joists still untouched, the position of "
    "the construction frontier (the boundary between completed decking and exposed joists), the "
    "camera framing, the structure's geometry and proportions, the builder's appearance and "
    "clothing, the site and background (ocean, cliffs, horizon), and the lighting. None of this "
    "may shift, reset, or be redrawn differently from the starting image.\n\n"
    "The builder is positioned at the construction frontier exactly as shown, and continues "
    "working from exactly that position. He installs one deck board at a time: he picks it up, "
    "moves it into place directly beside the previous board, and secures it - then immediately "
    "shifts exactly one board-width to the left and begins the next board in exactly the same "
    "way. The boundary continues to advance from right to left, continuing its existing "
    "direction and pace, like a progress bar continuing to fill in behind him. Nothing is ever "
    "allowed to leapfrog the builder: no board appears anywhere except directly beside the most "
    "recently completed board, immediately adjacent to his current position.\n\n"
    "It is far more important that the existing completed decking, camera, structure, and "
    "lighting remain visually identical to the starting image than how many additional boards "
    "get installed in this clip - even one or two correctly placed boards, with everything else "
    "held perfectly continuous, is a good outcome. Fine mechanical detail matters far less than "
    "this continuity and the unbroken right-to-left ordering - if anything must be simplified, "
    "simplify the small tool motions first, never the continuity of the existing scene or the "
    "ordering.\n\n"
    "Each new board appears only as a direct result of his visible physical work, at the "
    "position his hands are working, and never elsewhere. Once installed, a board remains in "
    "place for the rest of the clip - and every board already completed before this clip began "
    "remains in place too, unchanged. Only one location on the platform is ever under "
    "construction at a time - nothing changes anywhere else on the structure while he works. "
    "Nothing else about the structure changes: no wall studs, no roof, no other joists or beams "
    "appear or move. His movements are efficient and physically grounded - a real person doing "
    "focused, repetitive physical labor at a natural working pace, not idle or unrelated motion. "
    "He never looks toward the camera at any point. The ocean, cliffs, and horizon remain "
    "visible and stationary in the background, with natural wind and wave motion. Natural "
    "ambient sounds only - tools, wood handling, footsteps, wind, ocean. No dialogue, no "
    "narration, no music. No posing, no presenter behavior, no commercial aesthetic."
)

# Local duration variant - separate from every other test/segment's own
# variant; does NOT mutate the shared module-level WAN_3_0_STANDARD or
# any other config.
WAN_3_0_CHECKPOINT_CHAIN_TEST = dataclasses.replace(WAN_3_0_STANDARD, extra_payload={"duration": 10})


def fail(message: str) -> None:
    print(f"\nSTOPPED: {message}")
    print("No retry, no further generation - the script is exiting now.")
    sys.exit(1)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def save_manifest(manifest: dict) -> None:
    MANIFEST_PATH.parent.mkdir(parents=True, exist_ok=True)
    MANIFEST_PATH.write_text(json.dumps(manifest, indent=2))


def main() -> None:
    skip_confirm = "--yes" in sys.argv[1:]

    key_preview = f"{settings.fal_api_key[:6]}..." if settings.fal_api_key else None
    print(f"FAL_API_KEY loaded from .env: {'yes (' + key_preview + ')' if key_preview else 'NO'}")
    if not settings.fal_api_key:
        fail("FAL_API_KEY is not set. Add FAL_API_KEY=your_key_here to your .env file and try again.")

    if not CLIP_A_RAW_PATH.exists():
        fail(
            f"Test #2's raw clip not found at {CLIP_A_RAW_PATH} - nothing to extract from. "
            "Run scripts/run_construction_frontier_test.py for real first; it is never created "
            "or modified by this script."
        )
    if not CLIP_A_4X_PATH.exists():
        fail(
            f"Test #2's 4x accelerated clip not found at {CLIP_A_4X_PATH} - needed to build "
            "combined_preview_4x.mp4, the primary output of this test. Checking this BEFORE any "
            "spend, since generating Clip B without being able to build the combined preview "
            "would defeat the point of this test."
        )

    print(f"\n[1/2] Extracting the real last frame of Test #2's raw clip locally (no API call)...")
    try:
        extract_last_frame(CLIP_A_RAW_PATH, REFERENCE_FRAME_PATH)
    except FrameExtractionError as e:
        fail(f"Frame extraction failed: {e}")
    print(f"      Done -> {REFERENCE_FRAME_PATH} (Test #2's raw clip was only read, never modified)")

    video_provider = FalVideoProvider(WAN_3_0_CHECKPOINT_CHAIN_TEST)
    video_request = VideoGenerationRequest(
        prompt=VIDEO_PROMPT,
        reference_image_path=str(REFERENCE_FRAME_PATH),
        aspect_ratio=ASPECT_RATIO,
        duration_seconds=DURATION_SECONDS,
        extra_params={"resolution": RESOLUTION},
    )
    video_cost = video_provider.estimate_cost(video_request)

    print("=" * 70)
    print("VALIDATION TEST #3 - CHECKPOINT CHAINING - THIS WILL SPEND REAL MONEY")
    print("=" * 70)
    print(f"Video model: {WAN_3_0_CHECKPOINT_CHAIN_TEST.submit_path}  ({RESOLUTION}, {ASPECT_RATIO}, {DURATION_SECONDS:.0f}s)")
    print(f"Source image: {REFERENCE_FRAME_PATH} (real extracted pixels from Test #2's raw output)")
    print(f"\nVideo prompt:\n  {VIDEO_PROMPT}")
    print(f"\nEstimated cost: ${video_cost:.4f} (video only - no image-generation call)")
    print(f"Hard cap:       ${MAX_SPEND_USD:.2f}")
    print("Rules: exactly 1 video call, no image call, no retries, no camera change, no Segment 3.")
    print("=" * 70)

    if video_cost > MAX_SPEND_USD:
        fail(f"Estimated cost ${video_cost:.4f} exceeds the ${MAX_SPEND_USD:.2f} cap. Nothing was generated.")

    if not skip_confirm:
        answer = input(f"\nType 'yes' to spend up to ${video_cost:.4f} and proceed: ").strip().lower()
        if answer != "yes":
            print("Cancelled. Nothing was generated.")
            sys.exit(0)

    manifest = {
        "created_at": _now(),
        "experiment": "checkpoint_chain_test",
        "clip_a_raw_path": str(CLIP_A_RAW_PATH),
        "clip_a_4x_path": str(CLIP_A_4X_PATH),
        "reference_frame_path": str(REFERENCE_FRAME_PATH),
        "video_model": WAN_3_0_CHECKPOINT_CHAIN_TEST.submit_path,
        "resolution": RESOLUTION,
        "aspect_ratio": ASPECT_RATIO,
        "duration_seconds": DURATION_SECONDS,
        "video_prompt": VIDEO_PROMPT,
        "max_spend_usd": MAX_SPEND_USD,
        "estimated_cost_usd": video_cost,
        "clip_b_raw_path": None,
        "video_cost_usd": None,
        "clip_b_4x_path": None,
        "combined_preview_path": None,
        "actual_cost_usd": None,
        "completed_at": None,
    }
    save_manifest(manifest)

    print(f"\n[2/2] Submitting checkpoint-chain video generation job (Wan 3.0 standard, {RESOLUTION})...")
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
        video_provider.download_result(submitted.provider_job_id, result.output_url, str(RAW_VIDEO_PATH))
    except VideoProviderError as e:
        fail(
            f"Download failed (generation already succeeded and was billed, but the local save failed): {e}\n"
            f"      To retry just the download without spending anything again, run:\n"
            f"      python -m scripts.recover_fal_video_job {submitted.provider_job_id}"
        )

    actual_video_cost = result.actual_cost_usd if result.actual_cost_usd is not None else submitted.estimated_cost_usd

    manifest["clip_b_raw_path"] = str(RAW_VIDEO_PATH)
    manifest["video_cost_usd"] = actual_video_cost
    manifest["actual_cost_usd"] = actual_video_cost
    save_manifest(manifest)

    print(f"\nClip B raw saved (never to be overwritten): {RAW_VIDEO_PATH}")
    print(f"\n[local, free] Accelerating Clip B at {ACCELERATION_FACTOR:g}x...")
    try:
        accelerate_video(RAW_VIDEO_PATH, CLIP_B_4X_PATH, factor=ACCELERATION_FACTOR)
    except VideoAssemblyError as e:
        fail(
            f"FFmpeg acceleration failed: {e}\n"
            f"      Clip B's raw file itself is safe and unmodified: {RAW_VIDEO_PATH}\n"
            "      This is a local, free step - no additional API spend is needed to retry it. "
            "Fix ffmpeg/PATH, then run app.services.video_assembly.accelerate_video() manually "
            "against the raw clip above; re-running this whole script would submit a second paid "
            "video job."
        )
    print(f"      -> {CLIP_B_4X_PATH}")

    manifest["clip_b_4x_path"] = str(CLIP_B_4X_PATH)
    save_manifest(manifest)

    print(f"\n[local, free] Concatenating Test #2's 4x clip + Clip B's 4x clip into the combined preview...")
    try:
        concatenate_videos([CLIP_A_4X_PATH, CLIP_B_4X_PATH], COMBINED_PREVIEW_PATH)
    except VideoAssemblyError as e:
        fail(
            f"FFmpeg concatenation failed: {e}\n"
            f"      Both source clips are safe and unmodified: {CLIP_A_4X_PATH}, {CLIP_B_4X_PATH}\n"
            "      This is a local, free step - no additional API spend is needed to retry it. "
            "Fix ffmpeg/PATH, then run app.services.video_assembly.concatenate_videos() manually."
        )
    print(f"      -> {COMBINED_PREVIEW_PATH}")

    manifest["combined_preview_path"] = str(COMBINED_PREVIEW_PATH)
    manifest["completed_at"] = _now()
    save_manifest(manifest)

    print("\n" + "=" * 70)
    print("DONE - checkpoint-chain test generated. No Segment 3 production happened.")
    print("Segments 1A, 1B, 2, and Test #1/#2 outputs were not modified (all only read).")
    print("=" * 70)
    print(f"Clip B start frame (real Test #2 raw pixels): {REFERENCE_FRAME_PATH}")
    print(f"Clip B raw (10s, unmodified):                  {RAW_VIDEO_PATH}")
    print(f"Clip B 4x:                                     {CLIP_B_4X_PATH}")
    print(f"COMBINED PREVIEW (Test #2 4x + Clip B 4x):     {COMBINED_PREVIEW_PATH}")
    print(f"Video cost: ${actual_video_cost:.4f}   Manifest: {MANIFEST_PATH}")
    print("\nSTOP HERE. Judge combined_preview_4x.mp4 first, as a viewer would - the seam is")
    print("the #1 success criterion, ranked above how much additional decking Clip B completes.")
    print("\nContinuity criteria (the primary target of this test):")
    print("  - every board completed in Clip A remains unchanged and in place throughout Clip B")
    print("  - Clip B's builder resumes exactly at the boundary shown in the starting frame")
    print("  - the right-to-left direction continues without reversal or jump")
    print("  - no construction appears anywhere except adjacent to the frontier")
    print("  - at the concatenation seam: structure, board position, lighting, and camera framing")
    print("    all match - no visible jump, flash, or discontinuity")
    print("  - combined_preview_4x.mp4 reads as ONE continuous timelapse, not two clips glued together")
    print("\nRetained from Test #2 (still apply within Clip B itself):")
    print("  - exactly one active work location at any moment")
    print("  - believable board handling")
    print("  - builder never looks toward the camera")
    print("  - board count is NOT pass/fail - a small amount of additional decking is fine")
    print("\nDo not proceed to Segment 3 or any further generation until this is reviewed.")


if __name__ == "__main__":
    main()
