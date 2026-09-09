#!/usr/bin/env python3
"""RESUME Segment 2: video-only completion from the already-approved,
LOCKED start-frame image, with a REVISED relative-scale video prompt.

scripts/run_full_video_segment_2_test.py's mandatory review gate worked
exactly as designed - it stopped after the $0.15 image call and before the
$0.60 video call. The user exited at that gate (accidentally), and the
resulting image (segment_2_start_frame.jpg) was then reviewed separately
and approved/locked as the canonical Segment 2 starting image. This
script does NOT regenerate that image and does NOT call Nano Banana Pro at
all - it reuses the existing, approved image exactly as-is and makes ONLY
the remaining Wan 3.0 480p 12-second video call from it.

Scale correction based on reviewing the actual approved image: rather than
depending on absolute meter dimensions (the original script's prompt said
"roughly 10 meters wide by 6 meters deep"), the visible platform in the
approved start frame is now the visual source of truth. The target is
described RELATIVE to what's actually visible: approximately 2x the
current platform's width and 2x its depth (~4x floor area) - proportionate
and substantial, not an unrealistic structure consuming the whole site.
VIDEO_PROMPT_RESUME below is a revised version of the original script's
VIDEO_PROMPT with every absolute meter callout replaced by this relative
framing; the camera clause, opening/closing holds, hard-time-jump
structure, and every other creative requirement are otherwise unchanged.
The original VIDEO_PROMPT in run_full_video_segment_2_test.py is left
untouched as the historical planning record - this is a new, deliberate
prompt revision, not a reuse of the old one (unlike segment 1B's resume,
which used its approved prompt completely unchanged).

The manifest's build_state_end (SEGMENT_2_END_STATE_S2, imported
unchanged) still records the project's standing ~10m x 6m canonical
footprint fact for continuity-planning purposes across future segments -
only the actual generation prompt sent to Wan 3.0 for THIS call uses
relative-to-image framing instead, since meter callouts alone did not
reliably produce accurate real-world scale in the previous segment's
output.

Safety, same pattern as every other real-call script in this repo:
  - Exactly 1 video-generation call. No image call, no retry, no other
    segment.
  - Hard cap set exactly equal to the computed video cost ($0.60) - zero
    margin, since Wan 3.0's per-second billing is exactly precomputable.
  - Validates against the segment's own manifest.json (image already
    recorded, video not yet) before submitting, then updates it in place.
  - Any failure (submission, status check, or download) stops immediately
    via fail() with the exact error and, where relevant, the
    recover_fal_video_job.py hint - no automatic retry or resubmission.

Usage (from the repo root, with FAL_API_KEY set in your .env):
    python -m scripts.run_full_video_segment_2_resume_video_test
    python -m scripts.run_full_video_segment_2_resume_video_test --yes
"""
import json
import sys
import time
from datetime import datetime, timezone

from app.config import settings
from app.providers.base import ProviderJobState, VideoGenerationRequest, VideoProviderError
from app.providers.video.fal import FalVideoProvider
from scripts.run_full_video_segment_2_test import (
    ASPECT_RATIO,
    CAMERA_OPPOSITE_ELEVATED,
    DURATION_SECONDS,
    MANIFEST_PATH,
    OUTPUT_DIR,
    RESOLUTION,
    SEGMENT_ID,
    WAN_3_0_SEGMENT_2,
)

MAX_SPEND_USD = 0.60  # video only - the image was already generated and paid for
POLL_INTERVAL_SECONDS = 3
MAX_WAIT_SECONDS = 300  # 5 minutes; see the timeout message below if this is hit

# LOCKED: the approved Segment 2 start frame. Must never be regenerated.
IMAGE_PATH = OUTPUT_DIR / "segment_2_start_frame.jpg"
VIDEO_PATH = OUTPUT_DIR / "segment_2.mp4"
JOB_STATE_PATH = OUTPUT_DIR / "last_job.json"

# Revised video prompt: same camera clause, same opening/closing holds,
# same 4-beat hard-time-jump structure, same environment/no-camera-contact
# epilogue as the original script's VIDEO_PROMPT - but every absolute
# meter callout ("roughly 3 meters by 3 meters", "roughly 10 meters wide
# by 6 meters deep") is replaced with framing relative to the platform
# actually visible in the approved start frame: ~2x width, ~2x depth,
# ~4x floor area, explicitly proportionate rather than site-consuming.
VIDEO_PROMPT_RESUME = (
    "Vertical 9:16, extreme time-lapse construction footage, documentary/observational style. "
    f"{CAMERA_OPPOSITE_ELEVATED} He never looks toward the camera.\n\n"
    "The first 1.5-2 seconds hold on the existing floor platform exactly as it currently appears "
    "- a small, compact starter section relative to the builder. Then: NOT continuous real-time "
    "footage - the floor structure expands in hard, visible jumps, with an obvious change "
    "approximately every 1.5-2 seconds, each jump a clearly different stage. HARD TIME JUMP: new "
    "foundation piers rapidly appear well outside the current platform's edges in multiple "
    "directions. HARD TIME JUMP: large perimeter beams span between the new outer piers, "
    "extending roughly twice as far across the site as the current platform's width and depth, "
    "establishing the outline of a much larger footprint around it. HARD TIME JUMP: new floor "
    "joists rapidly extend outward from the current platform, integrating it into the larger "
    "structure rather than replacing it. HARD TIME JUMP: additional joists rapidly fill in across "
    "the expanded area until the grid is dense and continuous.\n\n"
    "The final 1.5-2 seconds hold on the completed floor structure: one continuous platform "
    "approximately twice the width and twice the depth of the platform shown at the start - "
    "roughly four times its floor area - with the original section clearly visible and "
    "recognizable within it, never replaced or swapped, only built outward from. The expansion "
    "is substantial but proportionate: a dramatically larger platform, not an unrealistic "
    "structure consuming the entire site. The builder appears substantially smaller relative to "
    "the floor structure than he did at the start, making the new scale of the project "
    "unmistakable. Still no floor decking, no wall framing, no roof, and no windows or doors.\n\n"
    "Once a pier, beam, or joist is placed it stays in place - progress only ever moves forward. "
    "The ocean, cliffs, and horizon remain clearly visible and hold real compositional weight "
    "throughout, not scenery behind the construction; wind moves the surrounding vegetation; "
    "clouds drift overhead. Natural ambient sounds only - hammering, wood handling, wind, ocean - "
    "no dialogue, no narration, no music. No posing, no presenter behavior, no eye contact with "
    "the camera, no commercial aesthetic. His attention stays entirely on the work - he must not "
    "look toward the camera at any point during this clip."
)


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
    if not manifest.get("image_cost_usd"):
        fail("manifest.json does not show a completed image generation (image_cost_usd is empty).")
    if manifest.get("video_path"):
        fail(
            f"manifest.json already records a completed video ({manifest['video_path']}) - "
            "this segment appears already done. Refusing to generate a second video for it."
        )

    print(f"Reusing approved, LOCKED image: {IMAGE_PATH} (not regenerated, no Nano Banana Pro call)")

    video_provider = FalVideoProvider(WAN_3_0_SEGMENT_2)
    video_request = VideoGenerationRequest(
        prompt=VIDEO_PROMPT_RESUME,
        reference_image_path=str(IMAGE_PATH),
        aspect_ratio=ASPECT_RATIO,
        duration_seconds=DURATION_SECONDS,
        extra_params={"resolution": RESOLUTION},
    )
    video_cost = video_provider.estimate_cost(video_request)

    print("=" * 70)
    print(f"FULL VIDEO #1 - SEGMENT {SEGMENT_ID} - RESUME (VIDEO ONLY, REVISED PROMPT) - THIS WILL SPEND REAL MONEY")
    print("=" * 70)
    print(f"Video model: {WAN_3_0_SEGMENT_2.submit_path}  ({RESOLUTION}, {ASPECT_RATIO}, {DURATION_SECONDS:.0f}s)")
    print(f"Source image (already approved, reused as-is): {IMAGE_PATH}")
    print(f"\nVideo prompt (REVISED - relative 2x width/2x depth scale, not absolute meters):\n  {VIDEO_PROMPT_RESUME}")
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

    manifest["video_prompt"] = VIDEO_PROMPT_RESUME
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
    print("\nSTOP HERE. Review segment_2.mp4 against:")
    print("  - opens on the small starter platform matching the approved start frame")
    print("  - each hard jump reads as a visually distinct stage of the expansion")
    print("  - the original small platform stays recognizable, never magically swapped")
    print("  - builder never looks toward camera; opposite-side near-horizontal angle preserved")
    print("  - fresh coastline clearly visible with real compositional weight")
    print("  - ends on a clean ~1.5-2s hold of the completed platform, ~2x width/2x depth of the start")
    print("  - builder reads as substantially smaller against the completed platform than at the start")
    print("  - expansion looks proportionate, not site-consuming")
    print("  - still no floor decking, wall framing, roof, windows, or doors")
    print("\nDo not build segment 3 until this segment is reviewed and approved.")


if __name__ == "__main__":
    main()
