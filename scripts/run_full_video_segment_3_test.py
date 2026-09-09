#!/usr/bin/env python3
"""FULL VIDEO #1 - SEGMENT 3 ("EXPANDED PLATFORM -> DECKING + WALL FRAMING
SKELETON").

Fourth of 7 segments in the planned ~68s production video. Segment 2 is
approved and LOCKED (the platform expansion from a small starter section
to a substantially larger platform, "several times its original size").
This script picks up exactly where that approved footage ends and makes
the moment the project transitions from a large open platform into an
actual building: floor decking goes down, then wall framing begins and
becomes substantial - but deliberately NOT complete. This is the ONLY
segment this script builds - segment 4 and everything after it are
separate scripts, built only after this one's result is reviewed. This
script does not touch or regenerate segments 1A, 1B, or 2 in any way.

Two calls, same "reference image, then video from it" pattern as every
earlier segment:
  1. Exactly ONE Nano Banana Pro Generate still image - this segment's
     START-state reference frame (the expanded joist platform, no
     decking/walls yet), built from the fixed site continuity bible
     (imported byte-identical from run_full_video_segment_1a_test) plus
     this segment's own start-state text and a fresh camera angle. No
     source/reference image is used - fresh text-to-image generation.
     Critically, the camera clause explicitly instructs the model NOT to
     shrink the platform when adopting the new angle - a direct
     safeguard against the same kind of scale-drift Segment 2 itself had
     to correct after review.
  2. Exactly ONE Wan 3.0 standard video generation (image-to-video) from
     that still, 480p, 9:16, 14 seconds - a local dataclasses.replace()
     variant of WAN_3_0_STANDARD (extra_payload={"duration": 14}), not
     touching the shared module-level config or any earlier segment's own
     duration variant (segments 1A/1B/2 use duration=6/8/12
     respectively).

SEGMENT_3_START_STATE deliberately does NOT import SEGMENT_2_END_STATE_S2
verbatim from run_full_video_segment_2_test - the same one-time-deviation
pattern already used going into Segment 2 (visual truth outranks earlier
written/prompt text for continuity purposes). It re-describes the
platform using the relative-scale language Segment 2's own resume video
actually used ("approximately twice the width and twice the depth"), not
Segment 2's original script's absolute "roughly 10 meters wide by 6
meters deep" wording.

Per explicit creative correction, the second wall's progress is
represented ONLY by how much of its horizontal length is framed - every
stud in this segment is a normal FULL-HEIGHT stud. No "several studs
high" language appears anywhere in this segment.

Safety, same pattern as every other real-call script in this repo:
  - Exactly 1 image-generation call, exactly 1 video-generation call. No
    loop, no retry, no auto-regeneration, no other segment.
  - Total cost checked against MAX_SPEND_USD BEFORE either call; one
    "type yes" confirmation gates the whole run.
  - manifest.json records both prompts, both costs, the output paths, and
    the exact build-state text handed off to segment 4.
  - Job state saved to disk immediately after video submission, before
    polling starts, so scripts/recover_fal_video_job.py can recover it.
  - The same mandatory manual REVIEW GATE as every earlier segment sits
    between the two calls: after the image is generated, the script
    prints its path and stops, requiring a separate "type yes" before
    submitting the video job. NOT skippable by --yes.

Usage (from the repo root, with FAL_API_KEY set in your .env):
    python -m scripts.run_full_video_segment_3_test
    python -m scripts.run_full_video_segment_3_test --yes   (skips only the upfront cost confirmation - the image review gate always runs)
"""
import dataclasses
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

from app.config import settings
from app.providers.base import (
    ImageGenerationRequest,
    ImageProviderError,
    ProviderJobState,
    VideoGenerationRequest,
    VideoProviderError,
)
from app.providers.image.fal import NANO_BANANA_PRO_GENERATE, FalImageProvider
from app.providers.video.fal import WAN_3_0_STANDARD, FalVideoProvider
from scripts.run_full_video_segment_1a_test import SITE_BIBLE

MAX_SPEND_USD = 0.85  # $0.15 image + $0.70 video (14s @ $0.05/s) - zero margin
RESOLUTION = "480p"
ASPECT_RATIO = "9:16"
DURATION_SECONDS = 14.0
POLL_INTERVAL_SECONDS = 3
MAX_WAIT_SECONDS = 300  # 5 minutes; see the timeout message below if this is hit

SEGMENT_ID = "3"

OUTPUT_DIR = Path(__file__).resolve().parent.parent / "data" / "fal_full_video_segment_3"
MANIFEST_PATH = OUTPUT_DIR / "manifest.json"
JOB_STATE_PATH = OUTPUT_DIR / "last_job.json"

# Start state - re-described to match the ACTUAL approved Segment 2
# appearance (relative-scale language), not Segment 2's original script's
# absolute-meter end-state text. Same one-time-deviation pattern used
# going into Segment 2 itself.
SEGMENT_3_START_STATE = (
    "Current construction state: the joist platform now spans approximately twice the width and "
    "twice the depth of the original starter section (matching the actual appearance confirmed "
    "in the approved Segment 2 footage) - fully continuous and dense, sitting on its foundation "
    "piers and perimeter beams. There is still no floor decking, no wall framing, no roof, and no "
    "windows or doors."
)

# End state (S3). Corrected per explicit review: NO "several studs high"
# anywhere - every stud is a normal full-height stud. The second wall's
# progress is represented by horizontal extent framed, not partial stud
# height. Ocean-facing side stays predominantly open.
SEGMENT_3_END_STATE_S3 = (
    "Current construction state: floor decking now fully covers the expanded platform. The "
    "near-side wall is completely framed at full height, from end to end. On one adjacent side "
    "wall, a substantial horizontal portion has been framed at the same full stud height, while "
    "the remainder of that wall's length is not yet framed - progress on this second wall is "
    "represented by how much of its length is built, not by partial stud height. The ocean-facing "
    "side of the platform remains predominantly open. The cabin's volume is clearly recognizable "
    "as a building skeleton. There is still no roof framing, no roof sheathing, no exterior "
    "siding, no installed windows, no installed doors, and no interior finishes."
)

# A fresh three-quarter diagonal angle, different from Segment 2's -
# looking down the platform's long axis toward the ocean, so the rising
# wall reads along one side of the frame rather than blocking the
# landscape. Includes an explicit scale-preservation instruction - a
# direct safeguard against the same kind of scale-drift Segment 2 itself
# had to correct after review.
CAMERA_LENGTHWISE_DIAGONAL = (
    "Camera view: a fresh three-quarter diagonal angle, different from Segment 2's - positioned "
    "near one corner of the expanded platform, looking diagonally down its long axis toward the "
    "open ocean-facing side, so the full length of the platform recedes toward the coastline. "
    "This reveals a different beautiful sweep of cliff and coastline not yet shown from this "
    "vantage. The near-side wall framing rises along one side of the frame rather than blocking "
    "the view - the ocean, horizon, and cliff geography remain clearly visible beside and beyond "
    "the rising structure, never obscured by it. The full extent of the platform stays visible so "
    "its increased scale relative to the builder remains obvious. This new camera angle must "
    "preserve the platform's actual established scale from the previous segment - the platform "
    "must read as the same large, substantially expanded structure already shown, never smaller "
    "or reduced in size merely because the camera position changed. Candid, fixed-camera "
    "construction-documentary feeling, not a posed or hero composition."
)

IMAGE_PROMPT = (
    f"{SITE_BIBLE} {SEGMENT_3_START_STATE} {CAMERA_LENGTHWISE_DIAGONAL} The builder stands near "
    "the platform's edge, beginning to lay the first decking board across the joists, his gaze "
    "on the work - not toward the camera. No eye contact, no portrait pose, no presenter stance."
)

VIDEO_PROMPT = (
    "Vertical 9:16, extreme time-lapse construction footage, documentary/observational style. "
    f"{CAMERA_LENGTHWISE_DIAGONAL} He never looks toward the camera.\n\n"
    "The first 1.5-2 seconds hold on the platform exactly as it currently appears - floor joists "
    "complete, no decking, no walls. Then: NOT continuous real-time footage - construction "
    "advances in hard, visible jumps, with an obvious change approximately every 1.5-2 seconds, "
    "each jump a clearly different stage. HARD TIME JUMP: floor decking rapidly appears, board by "
    "board, quickly filling the platform. HARD TIME JUMP: the first wall plates and vertical "
    "studs begin appearing along the near-side edge of the deck. HARD TIME JUMP: the near-side "
    "wall is now completely framed at full height, from end to end. HARD TIME JUMP: a substantial "
    "horizontal portion of one adjacent side wall is now framed at that same full stud height, "
    "while the remaining length of that wall is not yet framed - progress on this wall reads as "
    "horizontal extent, not partial stud height.\n\n"
    "The final 1.5-2 seconds hold on the framed skeleton: decking complete, the near-side wall "
    "fully framed end to end, a substantial portion of the adjacent wall framed at full height, "
    "the ocean-facing side of the platform remaining predominantly open, the cabin's volume "
    "clearly recognizable against the coastline. Still no roof framing, no roof sheathing, no "
    "exterior siding, no installed windows, no installed doors, and no interior finishes. The "
    "builder appears small relative to the completed skeleton.\n\n"
    "Once decking, a plate, or a stud is placed it stays in place - progress only ever moves "
    "forward. The ocean, cliffs, and horizon remain clearly visible and hold real compositional "
    "weight throughout, beside and beyond the rising structure, never blocked by it; wind moves "
    "the surrounding vegetation; clouds drift overhead. Natural ambient sounds only - hammering, "
    "nailing, wood handling, wind, ocean - no dialogue, no narration, no music. No posing, no "
    "presenter behavior, no eye contact with the camera, no commercial aesthetic. His attention "
    "stays entirely on the work - he must not look toward the camera at any point during this "
    "clip."
)

# Local per-segment duration variant - does NOT mutate the shared
# module-level WAN_3_0_STANDARD or any earlier segment's own variant
# (WAN_3_0_SEGMENT_1A duration=6, WAN_3_0_SEGMENT_1B duration=8,
# WAN_3_0_SEGMENT_2 duration=12).
WAN_3_0_SEGMENT_3 = dataclasses.replace(WAN_3_0_STANDARD, extra_payload={"duration": 14})


def fail(message: str) -> None:
    print(f"\nSTOPPED: {message}")
    print(f"No retry, no further generation - the script is exiting now. Manifest: {MANIFEST_PATH}")
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

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    image_path = OUTPUT_DIR / "segment_3_start_frame.jpg"
    video_path = OUTPUT_DIR / "segment_3.mp4"

    image_provider = FalImageProvider(NANO_BANANA_PRO_GENERATE)
    video_provider = FalVideoProvider(WAN_3_0_SEGMENT_3)

    image_request = ImageGenerationRequest(
        prompt=IMAGE_PROMPT, extra_params={"aspect_ratio": ASPECT_RATIO, "resolution": "1K"}
    )
    image_cost = image_provider.estimate_cost(image_request)

    cost_preview_request = VideoGenerationRequest(
        prompt=VIDEO_PROMPT,
        aspect_ratio=ASPECT_RATIO,
        duration_seconds=DURATION_SECONDS,
        extra_params={"resolution": RESOLUTION},
    )
    video_cost = video_provider.estimate_cost(cost_preview_request)
    total_cost = round(image_cost + video_cost, 4)

    print("=" * 70)
    print(f"FULL VIDEO #1 - SEGMENT {SEGMENT_ID} - THIS WILL SPEND REAL MONEY")
    print("=" * 70)
    print(f"Image model: {NANO_BANANA_PRO_GENERATE.model_id}  (text-to-image, no source image)")
    print(f"Video model: {WAN_3_0_SEGMENT_3.submit_path}  ({RESOLUTION}, {ASPECT_RATIO}, {DURATION_SECONDS:.0f}s)")
    print(f"\nImage prompt:\n  {IMAGE_PROMPT}")
    print(f"\nVideo prompt:\n  {VIDEO_PROMPT}")
    print(f"\nEstimated cost: ${image_cost:.4f} (image) + ${video_cost:.4f} (video) = ${total_cost:.4f}")
    print(f"Hard cap:       ${MAX_SPEND_USD:.2f}")
    print("Rules: exactly 1 image call, exactly 1 video call, no retries, no other segment.")
    print("=" * 70)

    if total_cost > MAX_SPEND_USD:
        fail(f"Estimated cost ${total_cost:.4f} exceeds the ${MAX_SPEND_USD:.2f} cap. Nothing was generated.")

    if not skip_confirm:
        answer = input(f"\nType 'yes' to spend up to ${total_cost:.4f} and proceed: ").strip().lower()
        if answer != "yes":
            print("Cancelled. Nothing was generated.")
            sys.exit(0)

    manifest = {
        "created_at": _now(),
        "experiment": "full_video_segment_3",
        "segment_id": SEGMENT_ID,
        "build_state_start": SEGMENT_3_START_STATE,
        "build_state_end": SEGMENT_3_END_STATE_S3,
        "image_model": NANO_BANANA_PRO_GENERATE.model_id,
        "video_model": WAN_3_0_SEGMENT_3.submit_path,
        "resolution": RESOLUTION,
        "aspect_ratio": ASPECT_RATIO,
        "duration_seconds": DURATION_SECONDS,
        "image_prompt": IMAGE_PROMPT,
        "video_prompt": VIDEO_PROMPT,
        "max_spend_usd": MAX_SPEND_USD,
        "estimated_cost_usd": total_cost,
        "image_path": None,
        "image_cost_usd": None,
        "video_path": None,
        "video_cost_usd": None,
        "actual_cost_usd": None,
        "completed_at": None,
    }
    save_manifest(manifest)

    # --- Step 1: exactly one reference image (segment start state) ---------
    print(f"\n[1/2] Generating segment {SEGMENT_ID} start-frame reference image (Nano Banana Pro)...")
    t0 = time.monotonic()
    try:
        image_result = image_provider.generate_image(image_request, str(image_path))
    except ImageProviderError as e:
        fail(f"Image generation failed: {e}")
    image_seconds = time.monotonic() - t0
    print(f"      Done in {image_seconds:.1f}s -> {image_path} (${image_result.cost_usd:.4f})")

    manifest["image_path"] = str(image_path)
    manifest["image_cost_usd"] = image_result.cost_usd
    save_manifest(manifest)

    # Mandatory manual review gate - NOT skippable by --yes, same mechanism
    # as every earlier segment.
    print(f"\n{'=' * 70}")
    print("REVIEW GATE - open the image below before continuing.")
    print(f"{'=' * 70}")
    print(f"Start-frame image: {image_path}")
    print("Check: the platform reads as the SAME large, expanded scale established in Segment 2")
    print("(not shrunk by the new angle), new lengthwise-diagonal camera toward the ocean, fresh")
    print("coastline clearly visible, builder not looking at camera, no decking/walls yet.")
    review_answer = input(
        "\nType 'yes' once you've reviewed the image and want to proceed to the "
        f"${video_cost:.4f} video call (anything else stops here, no video generated): "
    ).strip().lower()
    if review_answer != "yes":
        print("Stopped after image review. No video was generated. Nothing further will happen automatically.")
        sys.exit(0)

    # --- Step 2: exactly one video, from that exact image -------------------
    print(f"\n[2/2] Submitting segment {SEGMENT_ID} video generation job (Wan 3.0 standard, {RESOLUTION})...")
    video_request = VideoGenerationRequest(
        prompt=VIDEO_PROMPT,
        reference_image_path=str(image_path),
        aspect_ratio=ASPECT_RATIO,
        duration_seconds=DURATION_SECONDS,
        extra_params={"resolution": RESOLUTION},
    )
    t1 = time.monotonic()
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

    manifest["video_path"] = str(video_path)
    manifest["video_cost_usd"] = actual_video_cost
    manifest["actual_cost_usd"] = total_actual
    manifest["completed_at"] = _now()
    save_manifest(manifest)

    print("\n" + "=" * 70)
    print(f"DONE - segment {SEGMENT_ID} generated. No other segment was touched.")
    print("=" * 70)
    print(f"Start-frame image: {image_path}")
    print(f"Segment clip:      {video_path}")
    print(f"Image cost: ${image_result.cost_usd:.4f}   Video cost: ${actual_video_cost:.4f}   Total: ${total_actual:.4f}")
    print(f"Manifest: {MANIFEST_PATH}")
    print("\nSTOP HERE. Review segment_3.mp4 against:")
    print("  - opens on the expanded joist platform, no decking/walls yet")
    print("  - each hard jump reads as a visually distinct stage")
    print("  - near-side wall becomes completely framed at full height, end to end")
    print("  - adjacent wall shows a substantial framed PORTION at full height (not full-length)")
    print("  - no 'partial stud height' anywhere - every stud is full height")
    print("  - ocean-facing side of the platform stays predominantly open")
    print("  - builder never looks toward camera; new lengthwise-diagonal angle toward the ocean")
    print("  - fresh coastline clearly visible, never blocked by the rising wall")
    print("  - platform scale reads as the same large size established in Segment 2, not shrunk")
    print("  - still no roof, siding, windows, doors, or interior finishes")
    print("\nDo not build segment 4 until this segment is reviewed and approved.")


if __name__ == "__main__":
    main()
