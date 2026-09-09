#!/usr/bin/env python3
"""VALIDATION TEST #2 - CONSTRUCTION FRONTIER + FFMPEG TIMELAPSE.

Validation Test #1 (scripts/run_causal_action_test.py) proved individual
board handling can look physically believable - the builder used tools
correctly and installed boards convincingly. But it failed on ORDERED
PROGRESSION: after ~2 correctly-installed boards, additional decking
spontaneously appeared elsewhere on the platform, breaking the
construction illusion even though each individual action looked real.

This script tests the fix: the CONSTRUCTION FRONTIER principle. Every
repetitive construction operation gets a single, strict spatial direction
of progress, with exactly one active boundary at all times between
completed work, the builder's current position, and untouched work still
to come. For this test: decking progresses strictly RIGHT TO LEFT. The
prompt is written with an explicit priority order (matching the user's
own): (1) ordered right-to-left progression, (2) the builder visibly
causing that progression, (3) believable board handling, (4) fine tool
detail (individual fastening motions) - LAST, and explicitly sacrificed
first if the model has to trade something off. This is a deliberate
inversion from Test #1's prompt, which gave equal or greater weight to
mechanical fastening detail.

Same starting image, camera, and mechanism as Test #1 for a clean
single-variable comparison: the REAL LAST FRAME of the actual approved
Segment 2 video (data/fal_full_video_segment_2/segment_2.mp4), extracted
freshly here (not reusing Test #1's cached copy) via the existing
extract_last_frame() - pure ffmpeg, free, no API call, read-only (segment_2.mp4
is never modified). No Nano Banana Pro call. No camera-angle change - the
video prompt reuses Segment 2's own camera clause (CAMERA_OPPOSITE_ELEVATED,
imported unchanged) verbatim, same as Test #1.

Still contains NO "HARD TIME JUMP" or time-compression language - time
compression is still deferred entirely to a local, free FFmpeg pass
afterward. Same 2x/3x/4x acceleration comparison as Test #1, via the same
app.services.video_assembly.accelerate_video() function, from the exact
same raw clip, without ever overwriting it - now specifically evaluating
whether the frontier's right-to-left sweep reads as a satisfying,
almost-hypnotic "progress bar filling in" once accelerated, not just
whether individual actions look real.

Makes exactly ONE Wan 3.0 video call (10s, 480p, no image-generation call
of any kind). No retries. No camera change. No Segment 3 production. Does
not touch or modify Segments 1A, 1B, or 2 in any way - segment_2.mp4 is
only read. Board count is explicitly NOT a pass/fail factor here - 2-3
correctly-sequenced boards with an unbroken frontier is an intended pass;
more boards with any ordering violation is not.

Safety, same pattern as every other real-call script in this repo:
  - Exactly 1 video-generation call. No image call, no retry.
  - Hard cap set exactly equal to the computed video cost ($0.50) - zero
    margin, since Wan 3.0's per-second billing is exactly precomputable.
  - Job state saved to disk immediately after video submission, before
    polling starts, so scripts/recover_fal_video_job.py can recover it.
  - The raw downloaded clip is NEVER overwritten by the acceleration
    step - accelerate_video() itself refuses to write to its own input
    path, and each accelerated version gets its own distinct filename.

Usage (from the repo root, with FAL_API_KEY set in your .env, ffmpeg on
PATH, and data/fal_full_video_segment_2/segment_2.mp4 present):
    python -m scripts.run_construction_frontier_test
    python -m scripts.run_construction_frontier_test --yes
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
from app.services.video_assembly import VideoAssemblyError, accelerate_video
from scripts.run_full_video_segment_2_test import CAMERA_OPPOSITE_ELEVATED

MAX_SPEND_USD = 0.50  # video only - no image-generation call of any kind
RESOLUTION = "480p"
ASPECT_RATIO = "9:16"
DURATION_SECONDS = 10.0
POLL_INTERVAL_SECONDS = 3
MAX_WAIT_SECONDS = 300  # 5 minutes; see the timeout message below if this is hit
ACCELERATION_FACTORS = (2.0, 3.0, 4.0)

REPO_ROOT = Path(__file__).resolve().parent.parent
SEGMENT_2_VIDEO_PATH = REPO_ROOT / "data" / "fal_full_video_segment_2" / "segment_2.mp4"  # READ ONLY - never modified

OUTPUT_DIR = REPO_ROOT / "data" / "fal_construction_frontier_test"
REFERENCE_FRAME_PATH = OUTPUT_DIR / "segment_2_real_last_frame.jpg"
RAW_VIDEO_PATH = OUTPUT_DIR / "construction_frontier_raw.mp4"
MANIFEST_PATH = OUTPUT_DIR / "manifest.json"
JOB_STATE_PATH = OUTPUT_DIR / "last_job.json"

# Priority order matches the user's own, explicitly: (1) ordered
# right-to-left progression, (2) the builder visibly causing it, (3)
# believable board handling, (4) fine tool detail - LAST, and the first
# thing to simplify away if the model has to trade something off. This is
# a deliberate inversion from Test #1's prompt.
VIDEO_PROMPT = (
    "Vertical 9:16, realistic construction footage, documentary/observational style. "
    f"{CAMERA_OPPOSITE_ELEVATED} No camera movement, no angle change.\n\n"
    "The single most important visual behavior in this clip: at all times, the platform reads "
    "as three clear zones in a fixed left-to-right order - completed decking on the right, the "
    "builder working at the boundary in the middle, and untouched exposed joists on the left - "
    "and that entire boundary steadily advances from right to left over the course of the clip, "
    "like a progress bar filling in behind him. Nothing is ever allowed to leapfrog the builder: "
    "no board appears anywhere except directly beside the most recently completed board, "
    "immediately adjacent to his current position.\n\n"
    "He installs one deck board at a time: he picks it up, moves it into place directly beside "
    "the previous board, and secures it - then immediately shifts exactly one board-width to the "
    "left and begins the next board in exactly the same way. The viewer should be able to "
    "predict exactly where the next board will go: directly beside the last one, immediately to "
    "its left. Fine mechanical detail (how many screws, exact hand position) matters far less "
    "than this strict, unbroken right-to-left ordering - if anything must be simplified, "
    "simplify the small tool motions, never the ordering.\n\n"
    "Each new board appears only as a direct result of his visible physical work, at the "
    "position his hands are working, and never elsewhere. Once installed, a board remains in "
    "place for the rest of the clip. Only one location on the platform is ever under "
    "construction at a time - nothing changes anywhere else on the structure while he works, "
    "and no completed board is ever lost or altered. Nothing else about the structure changes: "
    "no wall studs, no roof, no other joists or beams appear or move. His movements are "
    "efficient and physically grounded - a real person doing focused, repetitive physical labor "
    "at a natural working pace, not idle or unrelated motion. He never looks toward the camera "
    "at any point. The ocean, cliffs, and horizon remain visible and stationary in the "
    "background, with natural wind and wave motion. Natural ambient sounds only - tools, wood "
    "handling, footsteps, wind, ocean. No dialogue, no narration, no music. No posing, no "
    "presenter behavior, no commercial aesthetic."
)

# Local duration variant - separate from Test #1's WAN_3_0_CAUSAL_TEST and
# every segment's own variant; does NOT mutate the shared module-level
# WAN_3_0_STANDARD or any other config.
WAN_3_0_FRONTIER_TEST = dataclasses.replace(WAN_3_0_STANDARD, extra_payload={"duration": 10})


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

    if not SEGMENT_2_VIDEO_PATH.exists():
        fail(
            f"Approved Segment 2 video not found at {SEGMENT_2_VIDEO_PATH} - nothing to extract from. "
            "This file only exists after running scripts/run_full_video_segment_2_resume_video_test.py "
            "for real; it is never created or modified by this script."
        )

    print(f"\n[1/2] Extracting the real last frame of {SEGMENT_2_VIDEO_PATH.name} locally (no API call)...")
    try:
        extract_last_frame(SEGMENT_2_VIDEO_PATH, REFERENCE_FRAME_PATH)
    except FrameExtractionError as e:
        fail(f"Frame extraction failed: {e}")
    print(f"      Done -> {REFERENCE_FRAME_PATH} (Segment 2's own video file was only read, never modified)")

    video_provider = FalVideoProvider(WAN_3_0_FRONTIER_TEST)
    video_request = VideoGenerationRequest(
        prompt=VIDEO_PROMPT,
        reference_image_path=str(REFERENCE_FRAME_PATH),
        aspect_ratio=ASPECT_RATIO,
        duration_seconds=DURATION_SECONDS,
        extra_params={"resolution": RESOLUTION},
    )
    video_cost = video_provider.estimate_cost(video_request)

    print("=" * 70)
    print("VALIDATION TEST #2 - CONSTRUCTION FRONTIER - THIS WILL SPEND REAL MONEY")
    print("=" * 70)
    print(f"Video model: {WAN_3_0_FRONTIER_TEST.submit_path}  ({RESOLUTION}, {ASPECT_RATIO}, {DURATION_SECONDS:.0f}s)")
    print(f"Source image: {REFERENCE_FRAME_PATH} (real extracted pixels, no Nano Banana call)")
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
        "experiment": "construction_frontier_test",
        "source_segment2_video": str(SEGMENT_2_VIDEO_PATH),
        "reference_frame_path": str(REFERENCE_FRAME_PATH),
        "video_model": WAN_3_0_FRONTIER_TEST.submit_path,
        "resolution": RESOLUTION,
        "aspect_ratio": ASPECT_RATIO,
        "duration_seconds": DURATION_SECONDS,
        "video_prompt": VIDEO_PROMPT,
        "max_spend_usd": MAX_SPEND_USD,
        "estimated_cost_usd": video_cost,
        "raw_video_path": None,
        "video_cost_usd": None,
        "accelerated_videos": [],
        "actual_cost_usd": None,
        "completed_at": None,
    }
    save_manifest(manifest)

    print(f"\n[2/2] Submitting construction-frontier video generation job (Wan 3.0 standard, {RESOLUTION})...")
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

    manifest["raw_video_path"] = str(RAW_VIDEO_PATH)
    manifest["video_cost_usd"] = actual_video_cost
    manifest["actual_cost_usd"] = actual_video_cost
    save_manifest(manifest)

    print(f"\nRaw clip saved (never to be overwritten): {RAW_VIDEO_PATH}")
    print("\n[local, free] Generating accelerated versions (2x, 3x, 4x) from the raw clip...")
    accelerated_videos = []
    for factor in ACCELERATION_FACTORS:
        factor_label = f"{factor:g}x"
        out_path = OUTPUT_DIR / f"construction_frontier_{factor_label}.mp4"
        try:
            accelerate_video(RAW_VIDEO_PATH, out_path, factor=factor)
        except VideoAssemblyError as e:
            fail(
                f"FFmpeg acceleration at {factor_label} failed: {e}\n"
                f"      The raw clip itself is safe and unmodified: {RAW_VIDEO_PATH}\n"
                "      This is a local, free step - no additional API spend is needed to retry it. "
                "Fix ffmpeg/PATH, then run "
                "app.services.video_assembly.accelerate_video() manually against the raw clip above; "
                "re-running this whole script would submit a second paid video job."
            )
        print(f"      {factor_label} -> {out_path}")
        accelerated_videos.append({"factor": factor, "path": str(out_path)})

    manifest["accelerated_videos"] = accelerated_videos
    manifest["completed_at"] = _now()
    save_manifest(manifest)

    print("\n" + "=" * 70)
    print("DONE - construction-frontier test generated. No Segment 3 production happened.")
    print("Segments 1A, 1B, and 2 were not modified (segment_2.mp4 was only read).")
    print("=" * 70)
    print(f"Reference frame (real Segment 2 pixels): {REFERENCE_FRAME_PATH}")
    print(f"Raw clip (10s, unmodified):               {RAW_VIDEO_PATH}")
    for entry in accelerated_videos:
        print(f"Accelerated {entry['factor']:g}x:                        {entry['path']}")
    print(f"Video cost: ${actual_video_cost:.4f}   Manifest: {MANIFEST_PATH}")
    print("\nSTOP HERE. Compare all four files side by side against:")
    print("\nPhysical-causality criteria (raw clip):")
    print("  - builder visibly picks up/carries/positions/aligns/fastens each board")
    print("  - builder never looks toward or acknowledges the camera")
    print("  - camera framing, structure, site, and background match the source frame exactly")
    print("  - no teleporting/duplicating boards, no tool/material morphing")
    print("  - no wall framing, roof, or unrelated structural change appears")
    print("\nConstruction-frontier criteria (raw clip - the primary target of this test):")
    print("  - exactly one active work location at any moment, never simultaneous areas")
    print("  - the completed | active | untouched boundary is spatially contiguous, no gaps")
    print("  - the boundary advances monotonically right-to-left, never reverses or jumps")
    print("  - no board ever appears ahead of (left of) the current frontier")
    print("  - every completed board is immediately adjacent to the previous one")
    print("  - board count is NOT pass/fail - 2-3 correctly sequential boards passes;")
    print("    5 boards with any ordering violation fails")
    print("\nTimelapse-aesthetic criteria (2x/3x/4x versions):")
    print("  - the sweeping boundary is clearly visible and legible at speed")
    print("  - progress feels satisfying/hypnotic once accelerated - like a progress bar filling in")
    print("  - movements read as quick, purposeful bursts, not jittery sped-up video")
    print("  - no motion artifacts introduced or exaggerated by acceleration")
    print("  - determine which speed (if any) best achieves the FORMA timelapse feel")
    print("\nDo not proceed to Segment 3 or any further generation until this is reviewed.")


if __name__ == "__main__":
    main()
