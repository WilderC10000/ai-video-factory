#!/usr/bin/env python3
"""FORMA VIDEO #1 - CHAPTER B, STAGE B1: FOUNDATION / FLOOR.

Only runnable after Stage B0 (Camera B transition edit) has been
generated AND approved by you - this script requires camera_b_edit.jpg
to already exist, and additionally asks you to explicitly confirm you've
reviewed and approved it (a separate confirmation from the cost
confirmation below) before it submits anything. This double gate exists
specifically so a failed or unreviewed edit can never automatically
trigger this paid generation - checked BEFORE any spend, per explicit
instruction: only after the Camera B edit is approved does this stage
become eligible to run.

Starting image is camera_b_edit.jpg directly (an already-generated still
image, not a video frame - no extract_last_frame() call needed here).
camera_b_edit.jpg is only ever read, never modified.

Visual-only prompt - no audio instructions of any kind. Foundation is
built as ONE bounded causal operation per explicit instruction: the
builder installs foundation posts across the cleared pad, one at a time,
in one continuous direction (Construction Frontier). No decking, no
framing, no walls, no glass, and no other structure appears in this
clip - those are separate, later stages. The skid-steer machine from
Chapter A remains visible but parked/unused, preserving continuity
without implying it does foundation work.

Makes exactly ONE Wan 3.0 video call. No retries. Does NOT chain to
Decking (Stage B2) - that is a separate script, run only after this
stage's own output is reviewed and approved.

Safety, same pattern as every other real-call script in this repo:
  - Exactly 1 video-generation call. No image call, no retry, no chaining
    to any other stage.
  - Hard cap set exactly equal to the computed cost ($0.35) - zero
    margin.
  - Job state saved to disk immediately after submission.

Usage (from the repo root, with FAL_API_KEY set in your .env, and
camera_b_edit.jpg already generated and reviewed):
    python -m scripts.run_forma_v1_chapter_b_foundation
    python -m scripts.run_forma_v1_chapter_b_foundation --yes   (skips only the cost confirmation - the upstream-approval confirmation always runs)
"""
import dataclasses
import json
import sys
import time
from datetime import datetime, timezone

from app.config import settings
from app.providers.base import ProviderJobState, VideoGenerationRequest, VideoProviderError
from app.providers.video.fal import WAN_3_0_STANDARD, FalVideoProvider
from scripts.run_forma_v1_chapter_b_camera_edit import CAMERA_B_EDIT_PATH, MANIFEST_PATH, OUTPUT_DIR

ASPECT_RATIO = "9:16"
RESOLUTION = "480p"
MAX_SPEND_USD = 0.35
DURATION_SECONDS = 7.0
POLL_INTERVAL_SECONDS = 3
MAX_WAIT_SECONDS = 300

FOUNDATION_RAW_PATH = OUTPUT_DIR / "foundation_raw.mp4"
JOB_STATE_PATH = OUTPUT_DIR / "foundation_last_job.json"

# Fixed camera established by Stage B0's edit - the actual geometry is
# whatever the real edited image shows, so the prompt only describes it
# as held steady, not a specific angle in words.
CAMERA_CLAUSE_B = (
    "Camera view: the fixed three-quarter angle established by the previous camera transition, "
    "held completely steady. No camera movement, no further angle change."
)

# Visual-only - no audio instructions, per explicit instruction. Single
# bounded causal operation only: foundation posts, one at a time, one
# direction. Explicitly excludes decking, framing, walls, and glass -
# those are separate, later stages, not part of this clip.
FOUNDATION_PROMPT = (
    "Vertical 9:16, realistic construction footage, documentary/observational style. "
    f"{CAMERA_CLAUSE_B} Continuing directly from the current state shown in the starting "
    "image.\n\n"
    "The cleared, leveled construction pad is empty - no foundation, no structure of any kind "
    "yet. The builder installs foundation posts across the pad: he sets and secures one post "
    "firmly into the ground, moves to the next position immediately adjacent to it, and repeats "
    "the same action - setting and securing one post at a time, working in one continuous "
    "direction across the pad. Each post is visibly placed and secured before he moves to the "
    "next; nothing appears anywhere else on the pad while he works in one area. By the end of "
    "the clip, a row of foundation posts stands across the worked section of the pad - the first "
    "visible structural element of the build - but no decking, no floor boards, no framing, no "
    "walls, and no glass appear yet. The compact tracked skid-steer remains parked at the edge of "
    "the pad, unused during this clip. The waterfall remains visible and in motion beside the "
    "cave; mist continues to drift. No posing, no presenter behavior."
)

WAN_3_0_FORMA_V1_B_FOUNDATION = dataclasses.replace(WAN_3_0_STANDARD, extra_payload={"duration": 7})


def fail(message: str) -> None:
    print(f"\nSTOPPED: {message}")
    print("No retry, no further generation - the script is exiting now.")
    sys.exit(1)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def load_manifest() -> dict:
    if MANIFEST_PATH.exists():
        return json.loads(MANIFEST_PATH.read_text())
    return {"experiment": "forma_video_1_chapter_b", "created_at": _now()}


def save_manifest(manifest: dict) -> None:
    MANIFEST_PATH.parent.mkdir(parents=True, exist_ok=True)
    MANIFEST_PATH.write_text(json.dumps(manifest, indent=2))


def main() -> None:
    skip_confirm = "--yes" in sys.argv[1:]

    key_preview = f"{settings.fal_api_key[:6]}..." if settings.fal_api_key else None
    print(f"FAL_API_KEY loaded from .env: {'yes (' + key_preview + ')' if key_preview else 'NO'}")
    if not settings.fal_api_key:
        fail("FAL_API_KEY is not set. Add FAL_API_KEY=your_key_here to your .env file and try again.")

    if not CAMERA_B_EDIT_PATH.exists():
        fail(
            f"{CAMERA_B_EDIT_PATH} not found - Stage B0 (Camera B transition edit) has not been "
            "generated yet. Run scripts/run_forma_v1_chapter_b_camera_edit.py first."
        )

    # Mandatory upstream-approval gate - NOT the same as the cost
    # confirmation below, and not skippable by --yes. A failed or
    # unreviewed edit must never be able to trigger this paid generation.
    print(f"\nUpstream file found: {CAMERA_B_EDIT_PATH}")
    approval = input(
        "Have you reviewed and approved camera_b_edit.jpg? Type 'yes' to confirm before proceeding "
        "(anything else stops here, nothing generated): "
    ).strip().lower()
    if approval != "yes":
        print("Stopped - Camera B edit was not confirmed as approved. Nothing was generated.")
        sys.exit(0)

    video_provider = FalVideoProvider(WAN_3_0_FORMA_V1_B_FOUNDATION)
    video_request = VideoGenerationRequest(
        prompt=FOUNDATION_PROMPT,
        reference_image_path=str(CAMERA_B_EDIT_PATH),
        aspect_ratio=ASPECT_RATIO,
        duration_seconds=DURATION_SECONDS,
        extra_params={"resolution": RESOLUTION},
    )
    video_cost = video_provider.estimate_cost(video_request)

    print("=" * 70)
    print("FORMA VIDEO #1 - CHAPTER B - STAGE B1 (FOUNDATION / FLOOR) - THIS WILL SPEND REAL MONEY")
    print("=" * 70)
    print(f"Video model: {WAN_3_0_FORMA_V1_B_FOUNDATION.submit_path}  ({RESOLUTION}, {ASPECT_RATIO}, {DURATION_SECONDS:.0f}s)")
    print(f"Source image: {CAMERA_B_EDIT_PATH} (Stage B0's approved camera-transition edit)")
    print(f"\nVideo prompt:\n  {FOUNDATION_PROMPT}")
    print(f"\nEstimated cost: ${video_cost:.4f}")
    print(f"Hard cap:       ${MAX_SPEND_USD:.2f}")
    print("Rules: exactly 1 video call, no retries, no chaining to Decking - this stage stops here.")
    print("=" * 70)

    if video_cost > MAX_SPEND_USD:
        fail(f"Estimated cost ${video_cost:.4f} exceeds the ${MAX_SPEND_USD:.2f} cap. Nothing was generated.")

    if not skip_confirm:
        answer = input(f"\nType 'yes' to spend up to ${video_cost:.4f} and proceed: ").strip().lower()
        if answer != "yes":
            print("Cancelled. Nothing was generated.")
            sys.exit(0)

    manifest = load_manifest()
    manifest["foundation"] = {
        "video_model": WAN_3_0_FORMA_V1_B_FOUNDATION.submit_path,
        "resolution": RESOLUTION,
        "aspect_ratio": ASPECT_RATIO,
        "duration_seconds": DURATION_SECONDS,
        "video_prompt": FOUNDATION_PROMPT,
        "start_frame_path": str(CAMERA_B_EDIT_PATH),
        "max_spend_usd": MAX_SPEND_USD,
        "estimated_cost_usd": video_cost,
        "raw_video_path": None,
        "actual_cost_usd": None,
        "completed_at": None,
    }
    save_manifest(manifest)

    print(f"\n[1/1] Submitting Foundation video generation job (Wan 3.0 standard, {RESOLUTION})...")
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
        video_provider.download_result(submitted.provider_job_id, result.output_url, str(FOUNDATION_RAW_PATH))
    except VideoProviderError as e:
        fail(
            f"Download failed (generation already succeeded and was billed, but the local save failed): {e}\n"
            f"      To retry just the download without spending anything again, run:\n"
            f"      python -m scripts.recover_fal_video_job {submitted.provider_job_id}"
        )

    actual_cost = result.actual_cost_usd if result.actual_cost_usd is not None else submitted.estimated_cost_usd

    manifest["foundation"]["raw_video_path"] = str(FOUNDATION_RAW_PATH)
    manifest["foundation"]["actual_cost_usd"] = actual_cost
    manifest["foundation"]["completed_at"] = _now()
    save_manifest(manifest)

    print("\n" + "=" * 70)
    print("STAGE B1 (FOUNDATION / FLOOR) DONE - stopping completely, as required.")
    print("=" * 70)
    print(f"Foundation raw: {FOUNDATION_RAW_PATH}")
    print(f"Actual cost:     ${actual_cost:.4f}")
    print(f"Manifest:        {MANIFEST_PATH}")
    print("\nSTOP HERE. Review foundation_raw.mp4 against:")
    print("  1. this is ONE bounded causal operation - foundation posts only")
    print("  2. posts are placed one at a time, in one consistent direction (no random jumps)")
    print("  3. NO decking, floor boards, framing, walls, or glass appear anywhere in the clip")
    print("  4. no unrelated structure spawns elsewhere on the pad")
    print("  5. camera framing matches the Camera B edit - no drift")
    print("  6. continues directly from camera_b_edit.jpg - the pad and debris ridge are unchanged")
    print("     everywhere the builder has not worked")
    print("\nDo NOT run Stage B2 (Decking) until you have reviewed and approved this clip.")
    print("Stage B2 has not been built yet - Framing is flagged as the highest-risk compressed")
    print("stage in this shorter plan and will need its own constrained, single-frontier design.")


if __name__ == "__main__":
    main()
