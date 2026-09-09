#!/usr/bin/env python3
"""VALIDATION TEST #1 - CAUSAL PHYSICAL ACTION + FFMPEG TIMELAPSE.

Tests the single most important open question in the FORMA format before
any more segment production happens: can Wan 3.0 generate ONE believable,
causally-grounded physical construction action (not a multi-stage
"HARD TIME JUMP" montage), which FFmpeg can then accelerate afterward into
a genuine timelapse feel - rather than asking Wan itself to fake extreme
time compression, which is what produced Segment 3's "structure changes
while the builder does something unrelated" failure.

This script does NOT call Nano Banana Pro at all. The starting image is
the REAL LAST FRAME of the actual approved Segment 2 video
(data/fal_full_video_segment_2/segment_2.mp4), extracted locally via the
existing app.services.frame_extraction.extract_last_frame() - pure ffmpeg,
free, no API call. Segment 2's video file is only ever READ, never
modified. This is real pixel conditioning, not a text re-description -
directly answering Failure 1 from the Segment 3 review (a text-only
SITE_BIBLE re-description is not the same structure from another angle).
There is no camera-angle change here at all: the video prompt reuses
Segment 2's own camera clause (CAMERA_OPPOSITE_ELEVATED, imported
unchanged) to describe the same fixed framing the extracted pixels
already show.

The video prompt deliberately contains NO "HARD TIME JUMP" or time-
compression language whatsoever - it describes ONE continuous, causally
specific action (installing several deck boards, each appearing only
where and when the builder's hands are actually working) at a believable,
continuous pace. Time compression is deferred entirely to a local,
free, post-processing step: three accelerated versions (2x, 3x, 4x) are
generated from the exact same raw clip via the new
app.services.video_assembly.accelerate_video() function, so this test can
compare "raw causal footage" against "the same footage genuinely
accelerated" side by side - the central question of this experiment.

Makes exactly ONE Wan 3.0 video call (10s, 480p, no image-generation call
of any kind). No retries. No camera change. No Segment 3 production. Does
not touch or modify Segments 1A, 1B, or 2 in any way - segment_2.mp4 is
only read.

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
    python -m scripts.run_causal_action_test
    python -m scripts.run_causal_action_test --yes
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

OUTPUT_DIR = REPO_ROOT / "data" / "fal_causal_action_test"
REFERENCE_FRAME_PATH = OUTPUT_DIR / "segment_2_real_last_frame.jpg"
RAW_VIDEO_PATH = OUTPUT_DIR / "causal_action_raw.mp4"
MANIFEST_PATH = OUTPUT_DIR / "manifest.json"
JOB_STATE_PATH = OUTPUT_DIR / "last_job.json"

VIDEO_PROMPT = (
    "Vertical 9:16, realistic construction footage, documentary/observational style. "
    f"{CAMERA_OPPOSITE_ELEVATED} No camera movement, no angle change.\n\n"
    "The builder is working at the near edge of the large expanded floor platform, where the "
    "exposed joists are visible. He picks up a single deck board from a stack beside him, "
    "carries it into position across the joists, kneels, aligns its edge against any previously "
    "placed decking, and fastens it down with a drill, driving screws at several points along "
    "the board. Once fastened, he immediately moves to the next board in the stack and repeats "
    "the exact same sequence: pick up, carry, position, align, fasten. He installs approximately "
    "3 to 5 boards this way over the course of the clip. Each new board appears on the platform "
    "ONLY at the moment and location his hands actually place and fasten it - never anywhere "
    "else on the structure. Every board he installs remains permanently in place for the rest of "
    "the clip. Nothing else about the structure changes: no wall studs, no roof, no other joists "
    "or beams appear or move. The stack of remaining boards beside him visibly shrinks as he "
    "uses them. His movements are efficient, continuous, and physically grounded - a real person "
    "doing repetitive physical labor at a natural working pace, not idle or unrelated tool "
    "motion. He never looks toward the camera at any point. The ocean, cliffs, and horizon "
    "remain visible and stationary in the background, with natural wind and wave motion. Natural "
    "ambient sounds only - drill, wood handling, footsteps, wind, ocean. No dialogue, no "
    "narration, no music. No posing, no presenter behavior, no commercial aesthetic."
)

# Local duration variant - does NOT mutate the shared module-level
# WAN_3_0_STANDARD or any existing segment's own duration variant.
WAN_3_0_CAUSAL_TEST = dataclasses.replace(WAN_3_0_STANDARD, extra_payload={"duration": 10})


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

    video_provider = FalVideoProvider(WAN_3_0_CAUSAL_TEST)
    video_request = VideoGenerationRequest(
        prompt=VIDEO_PROMPT,
        reference_image_path=str(REFERENCE_FRAME_PATH),
        aspect_ratio=ASPECT_RATIO,
        duration_seconds=DURATION_SECONDS,
        extra_params={"resolution": RESOLUTION},
    )
    video_cost = video_provider.estimate_cost(video_request)

    print("=" * 70)
    print("VALIDATION TEST #1 - CAUSAL PHYSICAL ACTION - THIS WILL SPEND REAL MONEY")
    print("=" * 70)
    print(f"Video model: {WAN_3_0_CAUSAL_TEST.submit_path}  ({RESOLUTION}, {ASPECT_RATIO}, {DURATION_SECONDS:.0f}s)")
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
        "experiment": "causal_action_test",
        "source_segment2_video": str(SEGMENT_2_VIDEO_PATH),
        "reference_frame_path": str(REFERENCE_FRAME_PATH),
        "video_model": WAN_3_0_CAUSAL_TEST.submit_path,
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

    print(f"\n[2/2] Submitting causal-action video generation job (Wan 3.0 standard, {RESOLUTION})...")
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
        out_path = OUTPUT_DIR / f"causal_action_{factor_label}.mp4"
        try:
            accelerate_video(RAW_VIDEO_PATH, out_path, factor=factor)
        except VideoAssemblyError as e:
            fail(
                f"FFmpeg acceleration at {factor_label} failed: {e}\n"
                f"      The raw clip itself is safe and unmodified: {RAW_VIDEO_PATH}\n"
                "      This is a local, free step - no additional API spend is needed to retry it. "
                "Fix ffmpeg/PATH, then run scripts/accelerate a video manually with "
                "app.services.video_assembly.accelerate_video() against the raw clip above; "
                "re-running this whole script would submit a second paid video job."
            )
        print(f"      {factor_label} -> {out_path}")
        accelerated_videos.append({"factor": factor, "path": str(out_path)})

    manifest["accelerated_videos"] = accelerated_videos
    manifest["completed_at"] = _now()
    save_manifest(manifest)

    print("\n" + "=" * 70)
    print("DONE - causal-action test generated. No Segment 3 production happened.")
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
    print("  - new decking appears ONLY where and when his hands are working")
    print("  - no wall framing, roof, or unrelated structural change appears")
    print("  - every installed board stays installed - no flicker/disappearance/reversal")
    print("  - material stack beside him visibly diminishes as boards are used")
    print("  - builder never looks toward or acknowledges the camera")
    print("  - camera framing, structure, site, and background match the source frame exactly")
    print("  - no teleporting/duplicating boards, no tool/material morphing")
    print("\nTimelapse-aesthetic criteria (2x/3x/4x versions):")
    print("  - movements read as quick, purposeful bursts, not jittery sped-up video")
    print("  - progress accumulates rapidly and satisfyingly")
    print("  - the action stays legible despite the speed")
    print("  - no motion artifacts introduced or exaggerated by acceleration")
    print("  - overall: genuine accelerated documentary footage, not 'an AI clip played fast'")
    print("  - determine which speed (if any) best achieves the FORMA timelapse feel")
    print("\nDo not proceed to Segment 3 or any further generation until this is reviewed.")


if __name__ == "__main__":
    main()
