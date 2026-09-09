#!/usr/bin/env python3
"""FULL VIDEO #1 - SEGMENT 1B ("CLEARED SITE -> EARLY FOUNDATION/FLOOR").

Second of 7 segments in the planned ~68s production video. Segment 1A
(approved and LOCKED - see run_full_video_segment_1a_test.py and the V2
composition fix in run_full_video_segment_1a_image_v2_test.py) ended on a
fully cleared, still entirely unbuilt site (build state S0.5). This
script picks up exactly there and advances to S1: a measured footprint,
foundation piers, staged materials, and most of the floor joist system
installed - the unmistakable beginning of a timber floor structure, while
still preserving zero walls/roof/windows/doors. This is the ONLY segment
this script builds - segment 2 and everything after it are separate
scripts, built only after this one's result is reviewed.

Two calls, same "reference image, then video from it" pattern as segment
1A:
  1. Exactly ONE Nano Banana Pro Generate still image - this segment's
     START-state reference frame (S0.5, cleared but unbuilt), built from
     the fixed site continuity bible (imported byte-identical from
     run_full_video_segment_1a_test, not retyped) plus SEGMENT_1A_END_STATE_S0_5
     (also imported byte-identical - this is the exact hand-off text
     segment 1A's own docstring promised) and a new camera clause.
  2. Exactly ONE Wan 3.0 standard video generation (image-to-video) from
     that still, 480p, 9:16, 8 seconds - a local dataclasses.replace()
     variant of WAN_3_0_STANDARD (extra_payload={"duration": 8}), not
     touching the shared module-level config or segment 1A's own
     duration=6 variant.

Camera composition carries forward segment 1A's approved V2 visual
language (chest/eye height, near-horizontal axis, environment-forward
framing - NOT the original rejected downward-pitched wide shot) at a
somewhat closer scale, per the standing production rule: synchronize any
camera/scale change with a construction-state jump, never cut angles at
the same story moment. Ocean/horizon/coastline still occupies roughly
30-40% of the frame - slightly less than 1A's 40-50% only because the shot
is tighter, not because the environment matters less; FORMA's visual
identity requires it stay a major compositional element throughout.

The video prompt's hard-time-jump sequence was deliberately written so
each jump introduces a visually DIFFERENT stage of the transformation
(footprint marked -> foundations/materials staged -> joists begin ->
most joists installed) rather than several similar "more joists appeared"
beats back to back - the requirement was a substantial, clearly-staged
transformation, not repetition, while ending on S1 (most of the floor
joist system installed, still no walls/roof/doors/windows). Brief, varied
builder activity (hammering a stake, carrying timber, positioning a
joist, using an impact driver) is described between jumps without
lingering on any one action.

Safety, same pattern as every other real-call script in this repo:
  - Exactly 1 image-generation call, exactly 1 video-generation call. No
    loop, no retry, no auto-regeneration, no other segment.
  - Total cost checked against MAX_SPEND_USD BEFORE either call; one
    "type yes" confirmation gates the whole run.
  - manifest.json records both prompts, both costs, the output paths, and
    the exact build-state text (S1) handed off to segment 2.
  - Job state (provider job id + fal.ai's own status/response URLs) is
    saved to disk immediately after video submission, before polling
    starts, so scripts/recover_fal_video_job.py can recover it if this
    script crashes or is interrupted mid-poll.
  - The same mandatory manual REVIEW GATE as segment 1A sits between the
    two calls: after the image is generated, the script prints its path
    and stops, requiring a separate "type yes" before submitting the
    video job. NOT skippable by --yes - this is exactly the mechanism
    that caught segment 1A's V1 composition problem before any video
    spend, so it stays in place for every segment.

Usage (from the repo root, with FAL_API_KEY set in your .env):
    python -m scripts.run_full_video_segment_1b_test
    python -m scripts.run_full_video_segment_1b_test --yes   (skips only the upfront cost confirmation - the image review gate always runs)
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
from scripts.run_full_video_segment_1a_test import SEGMENT_1A_END_STATE_S0_5, SITE_BIBLE

MAX_SPEND_USD = 0.55  # $0.15 image + $0.40 video (8s @ $0.05/s) - zero margin
RESOLUTION = "480p"
ASPECT_RATIO = "9:16"
DURATION_SECONDS = 8.0
POLL_INTERVAL_SECONDS = 3
MAX_WAIT_SECONDS = 300  # 5 minutes; see the timeout message below if this is hit

SEGMENT_ID = "1B"

OUTPUT_DIR = Path(__file__).resolve().parent.parent / "data" / "fal_full_video_segment_1b"
MANIFEST_PATH = OUTPUT_DIR / "manifest.json"
JOB_STATE_PATH = OUTPUT_DIR / "last_job.json"

# Segment 1B's start state is segment 1A's own end state, imported
# byte-identical (not retyped) - this IS the hand-off segment 1A's own
# docstring promised.
SEGMENT_1B_START_STATE_S0_5 = SEGMENT_1A_END_STATE_S0_5

# Segment 1B's own end state (S1) - recorded in the manifest as the exact
# text segment 2's own script must reuse as ITS start state.
SEGMENT_1B_END_STATE_S1 = (
    "Current construction state: string lines and stakes mark the building footprint, with "
    "foundation piers set at the corners. Stacks of raw timber, a tool case, and a circular saw "
    "are staged beside the footprint. Most of the floor joist system is now installed, running "
    "parallel across nearly the entire footprint with only one or two gaps remaining - the "
    "beginning of a timber floor structure is clearly visible. There is still no floor decking, "
    "no wall framing, no roof, and no windows or doors."
)

# Carries forward segment 1A's approved V2 visual language (chest/eye
# height, near-horizontal axis, environment-forward framing) at a
# somewhat closer scale - NOT the original rejected downward-pitched wide
# shot. Ocean/horizon still a major compositional element (~30-40%).
CAMERA_MEDIUM_WIDE_V2 = (
    "Camera view: a medium-wide establishing shot, still taken from approximately human chest/eye "
    "height with a near-horizontal axis - closer to the site than a wide establishing view, but "
    "preserving the same environment-forward framing. The horizon remains clearly visible. "
    "Roughly the upper 30-40% of the frame showcases the ocean, horizon, and coastal landscape - "
    "slightly less than a wider establishing shot's share since this shot is tighter, but still a "
    "major, unmissable compositional element, not background scenery. The lower/mid portion of "
    "the frame contains the builder and the worksite, close enough to clearly read stakes, string "
    "lines, staged timber, and joists. The composition preserves front-to-back depth: foreground "
    "worksite detail, then the builder, then the cliff edge and coastline, then the ocean and "
    "horizon beyond. Candid, fixed-camera construction-documentary feeling, not a posed or hero "
    "composition."
)

IMAGE_PROMPT = (
    f"{SITE_BIBLE} {SEGMENT_1B_START_STATE_S0_5} {CAMERA_MEDIUM_WIDE_V2} The builder is naturally "
    "measuring and driving a wooden stake into the ground with a hammer, his gaze on the work - "
    "not toward the camera. No eye contact, no portrait pose, no presenter stance."
)

VIDEO_PROMPT = (
    "Vertical 9:16, extreme time-lapse construction footage, documentary/observational style. "
    f"{CAMERA_MEDIUM_WIDE_V2} He never looks toward the camera.\n\n"
    "NOT continuous real-time footage - site preparation and early construction advance in hard, "
    "visible jumps, with an obvious change approximately every 1.5-2 seconds, and each jump "
    "introduces a clearly different stage of the transformation rather than a repeat of the "
    "previous one. HARD TIME JUMP: string lines and wooden stakes rapidly appear, fully marking "
    "out the rectangular building footprint on the cleared ground; the builder drives a stake "
    "into place with a hammer. HARD TIME JUMP: foundation piers now sit at the corners of the "
    "footprint, and stacks of raw timber, a tool case, and a circular saw have been staged beside "
    "it; the builder carries a length of timber into place. HARD TIME JUMP: the first floor "
    "joists rapidly appear across the footprint, fastened into place one after another - the "
    "unmistakable beginning of a timber floor structure now visible over the piers; the builder "
    "positions a joist into place. HARD TIME JUMP: most of the joist system is now installed, "
    "running parallel across nearly the entire footprint with only one or two gaps left - the "
    "floor structure reads as substantially built, though there is still no wall framing, no "
    "roof, and no windows or doors; the builder fastens a final joist with an impact driver.\n\n"
    "Each stage, once reached, persists and is never lost - progress only ever moves forward. "
    "Some brief, varied builder activity is visible between jumps - hammering, carrying, "
    "positioning, fastening - without lingering on any single action. The ocean and coastline "
    "remain visible beyond the site with visible wave motion; wind moves the surrounding "
    "vegetation; clouds drift overhead. Natural ambient sounds only - hammering, an impact "
    "driver, wood handling, wind, ocean - no dialogue, no narration, no music. No posing, no "
    "presenter behavior, no eye contact with the camera, no commercial aesthetic. His attention "
    "moves immediately and fully onto the work ahead of him - he must not look toward the camera "
    "at any point during this clip."
)

# Local per-segment duration variant - does NOT mutate the shared
# module-level WAN_3_0_STANDARD or segment 1A's own duration=6 variant.
WAN_3_0_SEGMENT_1B = dataclasses.replace(WAN_3_0_STANDARD, extra_payload={"duration": 8})


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
    image_path = OUTPUT_DIR / "segment_1b_start_frame.jpg"
    video_path = OUTPUT_DIR / "segment_1b.mp4"

    image_provider = FalImageProvider(NANO_BANANA_PRO_GENERATE)
    video_provider = FalVideoProvider(WAN_3_0_SEGMENT_1B)

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
    print(f"Video model: {WAN_3_0_SEGMENT_1B.submit_path}  ({RESOLUTION}, {ASPECT_RATIO}, {DURATION_SECONDS:.0f}s)")
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
        "experiment": "full_video_segment_1b",
        "segment_id": SEGMENT_ID,
        "build_state_start": SEGMENT_1B_START_STATE_S0_5,
        "build_state_end": SEGMENT_1B_END_STATE_S1,
        "image_model": NANO_BANANA_PRO_GENERATE.model_id,
        "video_model": WAN_3_0_SEGMENT_1B.submit_path,
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
    # as segment 1A (it's what caught 1A's V1 composition problem before
    # any video spend, so it stays in place for every segment).
    print(f"\n{'=' * 70}")
    print("REVIEW GATE - open the image below before continuing.")
    print(f"{'=' * 70}")
    print(f"Start-frame image: {image_path}")
    print("Check: cleared but still unbuilt site, chest/eye-height near-horizontal")
    print("camera, ocean/horizon occupying ~30-40% of frame, builder not looking at camera.")
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
    print("\nSTOP HERE. Review segment_1b.mp4 against:")
    print("  - starts on the cleared-but-unbuilt site from segment 1A's own ending")
    print("  - each hard jump reads as a visually distinct stage, not repeated joist shots")
    print("  - builder never looks toward camera; camera stays observational")
    print("  - varied builder activity (hammering/carrying/positioning/fastening), no lingering")
    print("  - ends with most of the floor joist system installed, still no walls/roof/doors")
    print("  - ocean/coastline stays clearly visible (~30-40% of frame) throughout")
    print("\nDo not build segment 2 until this segment is reviewed and approved.")


if __name__ == "__main__":
    main()
