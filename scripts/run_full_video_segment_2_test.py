#!/usr/bin/env python3
"""FULL VIDEO #1 - SEGMENT 2 ("SMALL STARTER PLATFORM -> ~10m x 6m FLOOR
STRUCTURE").

Third of 7 segments in the planned ~68s production video. Segment 1B's
locked video was reviewed for real, and its actual generated appearance
reads as a much smaller starter platform (~3m x 3m relative to the
builder) than its own prompt text implied. Per the new standing FORMA
rule - the ACTUAL generated visual output outranks a prior segment's
intended prompt dimensions when establishing continuity - this script's
start-state text (SEGMENT_2_START_STATE below) deliberately does NOT
import SEGMENT_1B_END_STATE_S1 verbatim; it re-describes what the footage
actually shows. This is a one-time deviation from the "always import the
previous segment's end state byte-identical" pattern used everywhere
else in this project, justified by that new rule.

This segment is entirely one transformation: the small ~3x3m starter
platform is expanded, on-camera, into a substantially larger ~10m x 6m
floor structure - several times its original size - with the original
platform remaining visually recognizable throughout (never magically
swapped for a bigger one between cuts). No wall framing begins here; the
completed large floor platform is this segment's own payoff, held clean
for the final ~1.5-2s so segment 3 can open on it with its own new
payoff (decking + walls rising).

This is also the first real implementation of the new FORMA camera rule:
a substantially different observational angle from 1A/1B - opposite side
of the site, a naturally elevated vantage point but with the camera axis
kept near-horizontal (not tilted down) - revealing a fresh, compositionally
major sweep of coastline that was not shown in earlier segments, while
still making the platform's expansion legible. The builder is used
aggressively as a scale reference: by the segment's end he reads as
noticeably small against the completed platform.

Two calls, same "reference image, then video from it" pattern as segments
1A/1B:
  1. Exactly ONE Nano Banana Pro Generate still image - this segment's
     START-state reference frame (the small starter platform, as it
     actually looks, from the new camera angle). No source image - fresh
     text-to-image generation.
  2. Exactly ONE Wan 3.0 standard video generation (image-to-video) from
     that still, 480p, 9:16, 12 seconds - a local dataclasses.replace()
     variant of WAN_3_0_STANDARD (extra_payload={"duration": 12}), not
     touching the shared module-level config or any earlier segment's own
     duration variant (WAN_3_0_SEGMENT_1A duration=6, WAN_3_0_SEGMENT_1B
     duration=8).

SEGMENT_2_END_STATE_S2 is recorded in the manifest as the exact hand-off
text segment 3's own script must reuse as ITS start state - from this
point onward, ~10m x 6m is the canonical, locked footprint for every
future segment.

Safety, same pattern as every other real-call script in this repo:
  - Exactly 1 image-generation call, exactly 1 video-generation call. No
    loop, no retry, no auto-regeneration, no other segment.
  - Total cost checked against MAX_SPEND_USD BEFORE either call; one
    "type yes" confirmation gates the whole run.
  - manifest.json records both prompts, both costs, the output paths, and
    the exact build-state text handed off to segment 3.
  - Job state saved to disk immediately after video submission, before
    polling starts, so scripts/recover_fal_video_job.py can recover it.
  - The same mandatory manual REVIEW GATE as segments 1A/1B sits between
    the two calls: after the image is generated, the script prints its
    path and stops, requiring a separate "type yes" before submitting the
    video job. NOT skippable by --yes.

Usage (from the repo root, with FAL_API_KEY set in your .env):
    python -m scripts.run_full_video_segment_2_test
    python -m scripts.run_full_video_segment_2_test --yes   (skips only the upfront cost confirmation - the image review gate always runs)
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

MAX_SPEND_USD = 0.75  # $0.15 image + $0.60 video (12s @ $0.05/s) - zero margin
RESOLUTION = "480p"
ASPECT_RATIO = "9:16"
DURATION_SECONDS = 12.0
POLL_INTERVAL_SECONDS = 3
MAX_WAIT_SECONDS = 300  # 5 minutes; see the timeout message below if this is hit

SEGMENT_ID = "2"

OUTPUT_DIR = Path(__file__).resolve().parent.parent / "data" / "fal_full_video_segment_2"
MANIFEST_PATH = OUTPUT_DIR / "manifest.json"
JOB_STATE_PATH = OUTPUT_DIR / "last_job.json"

# Start state - corrected to the ACTUAL appearance of segment 1B's locked
# video (a small ~3x3m starter platform), NOT segment 1B's own prompt text
# (SEGMENT_1B_END_STATE_S1), which implied a larger footprint than what
# was actually generated. Per the new standing rule, real output outranks
# intended prompt dimensions for continuity purposes.
SEGMENT_2_START_STATE = (
    "Current construction state (matching the actual generated appearance, not the original "
    "prompt's stated dimensions): a small, compact starter floor platform - roughly 3 meters by "
    "3 meters relative to the builder's scale - sits on foundation piers, with a dense grid of "
    "floor joists already installed across it. Stacks of raw timber, a tool case, and a circular "
    "saw remain staged beside it. There is still no floor decking, no wall framing, no roof, and "
    "no windows or doors."
)

# End state (S2) - the new canonical ~10m x 6m footprint, locked from here
# onward for every future segment. No wall framing yet - the completed
# large floor platform is THIS segment's own payoff; walls rising is
# segment 3's payoff.
SEGMENT_2_END_STATE_S2 = (
    "Current construction state: the original small starter platform is fully incorporated into "
    "a single, substantially larger floor structure, its foundation piers, perimeter beams, and "
    "joist grid now spanning roughly 10 meters wide by 6 meters deep - several times larger than "
    "the original starter platform, which remains recognizable as one section within it. The "
    "builder appears noticeably small relative to the completed floor platform. There is still "
    "no floor decking, no wall framing, no roof, and no windows or doors."
)

# First real implementation of the FORMA camera-variation rule: a
# substantially different angle from 1A/1B - opposite side, a naturally
# elevated vantage point, but the camera AXIS stays near-horizontal (never
# tilted down at the site) - giving the landscape real compositional
# weight rather than background scenery.
CAMERA_OPPOSITE_ELEVATED = (
    "Camera view: a substantially different observational angle from previous segments - "
    "positioned on the opposite side of the site, at a natural vantage point slightly higher "
    "than the platform, but with the camera axis kept near-horizontal rather than tilted "
    "downward. This reveals a fresh sweep of coastline, ocean, and cliff geography not yet "
    "shown, occupying a clearly major share of the frame alongside the structure - never a "
    "downward-looking construction shot. From this angle the small starter platform and the "
    "full extent of its expansion are both legible, with the builder appearing small against "
    "the completed floor structure and the surrounding landscape alike. Candid, fixed-camera "
    "construction-documentary feeling, not a posed or hero composition."
)

IMAGE_PROMPT = (
    f"{SITE_BIBLE} {SEGMENT_2_START_STATE} {CAMERA_OPPOSITE_ELEVATED} The builder stands near "
    "the small existing platform, beginning to mark out new foundation points further out with "
    "a string line and stakes, his gaze on the work - not toward the camera. No eye contact, no "
    "portrait pose, no presenter stance."
)

VIDEO_PROMPT = (
    "Vertical 9:16, extreme time-lapse construction footage, documentary/observational style. "
    f"{CAMERA_OPPOSITE_ELEVATED} He never looks toward the camera.\n\n"
    "The first 1.5-2 seconds hold on the existing small starter platform exactly as it stands - "
    "roughly 3 meters by 3 meters relative to the builder. Then: NOT continuous real-time "
    "footage - the floor structure expands in hard, visible jumps, with an obvious change "
    "approximately every 1.5-2 seconds, each jump a clearly different stage. HARD TIME JUMP: new "
    "foundation piers rapidly appear much farther outward from the small platform in multiple "
    "directions. HARD TIME JUMP: large perimeter beams span between the new outer piers, "
    "establishing the outline of a dramatically larger footprint around the original platform. "
    "HARD TIME JUMP: new floor joists rapidly extend outward from the original platform, "
    "integrating it into the larger structure rather than replacing it. HARD TIME JUMP: "
    "additional joists rapidly fill in across the expanded area until the grid is dense and "
    "continuous.\n\n"
    "The final 1.5-2 seconds hold on the completed floor structure: one continuous, substantial "
    "joist platform roughly 10 meters wide by 6 meters deep, several times larger than the "
    "original starter section, which remains clearly visible and recognizable within it - never "
    "replaced or swapped, only built outward from. The builder appears noticeably small against "
    "the completed platform, making the new scale of the project unmistakable. Still no floor "
    "decking, no wall framing, no roof, and no windows or doors.\n\n"
    "Once a pier, beam, or joist is placed it stays in place - progress only ever moves forward. "
    "The ocean, cliffs, and horizon remain clearly visible and hold real compositional weight "
    "throughout, not scenery behind the construction; wind moves the surrounding vegetation; "
    "clouds drift overhead. Natural ambient sounds only - hammering, wood handling, wind, ocean - "
    "no dialogue, no narration, no music. No posing, no presenter behavior, no eye contact with "
    "the camera, no commercial aesthetic. His attention stays entirely on the work - he must not "
    "look toward the camera at any point during this clip."
)

# Local per-segment duration variant - does NOT mutate the shared
# module-level WAN_3_0_STANDARD or any earlier segment's own variant.
WAN_3_0_SEGMENT_2 = dataclasses.replace(WAN_3_0_STANDARD, extra_payload={"duration": 12})


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
    image_path = OUTPUT_DIR / "segment_2_start_frame.jpg"
    video_path = OUTPUT_DIR / "segment_2.mp4"

    image_provider = FalImageProvider(NANO_BANANA_PRO_GENERATE)
    video_provider = FalVideoProvider(WAN_3_0_SEGMENT_2)

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
    print(f"Video model: {WAN_3_0_SEGMENT_2.submit_path}  ({RESOLUTION}, {ASPECT_RATIO}, {DURATION_SECONDS:.0f}s)")
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
        "experiment": "full_video_segment_2",
        "segment_id": SEGMENT_ID,
        "build_state_start": SEGMENT_2_START_STATE,
        "build_state_end": SEGMENT_2_END_STATE_S2,
        "image_model": NANO_BANANA_PRO_GENERATE.model_id,
        "video_model": WAN_3_0_SEGMENT_2.submit_path,
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
    # as segments 1A/1B.
    print(f"\n{'=' * 70}")
    print("REVIEW GATE - open the image below before continuing.")
    print(f"{'=' * 70}")
    print(f"Start-frame image: {image_path}")
    print("Check: small ~3x3m starter platform (matching 1B's actual output), new opposite-side")
    print("near-horizontal camera angle, fresh coastline clearly visible, builder not looking at camera.")
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
    print("\nSTOP HERE. Review segment_2.mp4 against:")
    print("  - opens on the small ~3x3m starter platform matching 1B's actual appearance")
    print("  - each hard jump reads as a visually distinct stage of the expansion")
    print("  - the original small platform stays recognizable, never magically swapped")
    print("  - builder never looks toward camera; new opposite-side near-horizontal angle")
    print("  - fresh coastline clearly visible with real compositional weight")
    print("  - ends on a clean ~1.5-2s hold of the completed ~10m x 6m floor structure")
    print("  - builder reads as noticeably small against the completed platform")
    print("  - still no floor decking, wall framing, roof, windows, or doors")
    print("\nDo not build segment 3 until this segment is reviewed and approved.")


if __name__ == "__main__":
    main()
