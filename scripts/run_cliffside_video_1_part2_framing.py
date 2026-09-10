#!/usr/bin/env python3
"""CLIFFSIDE VIDEO #1, PART 2 - SHOT 1: WALL FRAMING MECHANISM.

Only runnable after Stage C0 (decking-completion edit) has been generated
AND approved - requires decking_complete_edit.jpg to already exist, and
additionally asks you to explicitly confirm you've reviewed and approved
it before submitting anything. decking_complete_edit.jpg is only ever
read, never modified.

DEMONSTRATE, THEN SKIP: this clip shows only the beginning of the wall-
framing process - 2-3 studs, one clear frontier - never the whole wall.
The permanent construction spec (12ft x 16ft footprint, ~8ft wall height)
governs the studs' scale; completion happens at the next jump cut
(Stage C0's sibling, run_cliffside_video_1_part2_framing_edit.py), not
in this clip.

Makes exactly ONE Wan 3.0 video call. No retries. Does NOT chain to the
framing-completion edit - that is a separate script, run only after this
stage's own output is reviewed and approved.

Usage (from the repo root, with FAL_API_KEY set in your .env, and
decking_complete_edit.jpg already generated and reviewed):
    python -m scripts.run_cliffside_video_1_part2_framing
    python -m scripts.run_cliffside_video_1_part2_framing --yes   (skips only the cost confirmation - the upstream-approval confirmation always runs)
"""
import dataclasses
import json
import sys
import time
from datetime import datetime, timezone

from app.config import settings
from app.providers.base import ProviderJobState, VideoGenerationRequest, VideoProviderError
from app.providers.video.fal import WAN_3_0_STANDARD, FalVideoProvider
from scripts.run_cliffside_video_1_decking_complete_edit import DECKING_COMPLETE_EDIT_PATH
from scripts.run_cliffside_video_1_rough_assembly import MANIFEST_PATH, OUTPUT_DIR

ASPECT_RATIO = "9:16"
RESOLUTION = "480p"
MAX_SPEND_USD = 0.30
DURATION_SECONDS = 6.0
POLL_INTERVAL_SECONDS = 3
MAX_WAIT_SECONDS = 300

FRAMING_RAW_PATH = OUTPUT_DIR / "framing_raw.mp4"
JOB_STATE_PATH = OUTPUT_DIR / "framing_last_job.json"

CAMERA_CLAUSE = (
    "Camera view: the fixed viewpoint established by the previous edit, held completely steady. "
    "No camera movement, no further angle change."
)

# Visual-only - no audio instructions. Single bounded causal operation:
# 2-3 full-height studs, one direction, one frontier. Explicitly excludes
# roof, glass, siding, door, and any wall progress elsewhere.
FRAMING_PROMPT = (
    "Vertical 9:16, realistic construction footage, documentary/observational style. "
    f"{CAMERA_CLAUSE} Continuing directly from the current state shown in the starting image.\n\n"
    "The floor is completely decked - the entire platform reads as a finished floor with no "
    "exposed joists, no walls, no roof, no windows or glass, and no siding of any kind yet. The "
    "cabin being framed here will define a simple rectangular perimeter approximately 12 feet "
    "wide by 16 feet deep, with wall studs standing about 8 feet tall. The builder has full-"
    "height timber studs staged nearby, just outside the frame. He lifts one full-height stud, "
    "positions it vertically at the edge of the platform, seats it onto the base framing, and "
    "secures it in place, then immediately shifts to the adjacent position roughly 16 to 24 "
    "inches away and repeats the same action for 2 to 3 studs total - all standing vertical, "
    "evenly spaced, and aligned in one straight wall plane. Progress moves in one clear direction "
    "only: installed studs on one side, the builder actively working at the current position, "
    "and the empty wall line still ahead of him, untouched until he reaches it. No roof framing, "
    "no glass, no siding, no door, and no additional beams appear; no wall studs appear anywhere "
    "else on the platform. The ocean, cliff, and coastline remain visible and consistent around "
    "the platform. No posing, no presenter behavior."
)

WAN_3_0_CLIFFSIDE_FRAMING = dataclasses.replace(WAN_3_0_STANDARD, extra_payload={"duration": 6})


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

    if not DECKING_COMPLETE_EDIT_PATH.exists():
        fail(
            f"{DECKING_COMPLETE_EDIT_PATH} not found - Stage C0 (decking-completion edit) has not "
            "been generated yet. Run scripts/run_cliffside_video_1_decking_complete_edit.py first."
        )

    print(f"\nUpstream file found: {DECKING_COMPLETE_EDIT_PATH}")
    approval = input(
        "Have you reviewed and approved decking_complete_edit.jpg? Type 'yes' to confirm before "
        "proceeding (anything else stops here, nothing generated): "
    ).strip().lower()
    if approval != "yes":
        print("Stopped - the decking-completion edit was not confirmed as approved. Nothing was generated.")
        sys.exit(0)

    video_provider = FalVideoProvider(WAN_3_0_CLIFFSIDE_FRAMING)
    video_request = VideoGenerationRequest(
        prompt=FRAMING_PROMPT,
        reference_image_path=str(DECKING_COMPLETE_EDIT_PATH),
        aspect_ratio=ASPECT_RATIO,
        duration_seconds=DURATION_SECONDS,
        extra_params={"resolution": RESOLUTION},
    )
    video_cost = video_provider.estimate_cost(video_request)

    print("=" * 70)
    print("CLIFFSIDE VIDEO #1 - PART 2 - SHOT 1 (WALL FRAMING) - THIS WILL SPEND REAL MONEY")
    print("=" * 70)
    print(f"Video model: {WAN_3_0_CLIFFSIDE_FRAMING.submit_path}  ({RESOLUTION}, {ASPECT_RATIO}, {DURATION_SECONDS:.0f}s)")
    print(f"Source image: {DECKING_COMPLETE_EDIT_PATH}")
    print(f"\nVideo prompt:\n  {FRAMING_PROMPT}")
    print(f"\nEstimated cost: ${video_cost:.4f}")
    print(f"Hard cap:       ${MAX_SPEND_USD:.2f}")
    print("Rules: exactly 1 video call, no retries, no chaining - this stage stops here.")
    print("=" * 70)

    if video_cost > MAX_SPEND_USD:
        fail(f"Estimated cost ${video_cost:.4f} exceeds the ${MAX_SPEND_USD:.2f} cap. Nothing was generated.")

    if not skip_confirm:
        answer = input(f"\nType 'yes' to spend up to ${video_cost:.4f} and proceed: ").strip().lower()
        if answer != "yes":
            print("Cancelled. Nothing was generated.")
            sys.exit(0)

    manifest = load_manifest()
    manifest["framing"] = {
        "video_model": WAN_3_0_CLIFFSIDE_FRAMING.submit_path,
        "resolution": RESOLUTION,
        "aspect_ratio": ASPECT_RATIO,
        "duration_seconds": DURATION_SECONDS,
        "video_prompt": FRAMING_PROMPT,
        "start_frame_path": str(DECKING_COMPLETE_EDIT_PATH),
        "max_spend_usd": MAX_SPEND_USD,
        "estimated_cost_usd": video_cost,
        "raw_video_path": None,
        "actual_cost_usd": None,
        "completed_at": None,
    }
    save_manifest(manifest)

    print(f"\n[1/1] Submitting Wall Framing video generation job (Wan 3.0 standard, {RESOLUTION})...")
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
        video_provider.download_result(submitted.provider_job_id, result.output_url, str(FRAMING_RAW_PATH))
    except VideoProviderError as e:
        fail(
            f"Download failed (generation already succeeded and was billed, but the local save failed): {e}\n"
            f"      To retry just the download without spending anything again, run:\n"
            f"      python -m scripts.recover_fal_video_job {submitted.provider_job_id}"
        )

    actual_cost = result.actual_cost_usd if result.actual_cost_usd is not None else submitted.estimated_cost_usd

    manifest["framing"]["raw_video_path"] = str(FRAMING_RAW_PATH)
    manifest["framing"]["actual_cost_usd"] = actual_cost
    manifest["framing"]["completed_at"] = _now()
    save_manifest(manifest)

    print("\n" + "=" * 70)
    print("SHOT 1 (WALL FRAMING) DONE - stopping completely, as required.")
    print("=" * 70)
    print(f"Framing raw: {FRAMING_RAW_PATH}")
    print(f"Actual cost:  ${actual_cost:.4f}")
    print(f"Manifest:     {MANIFEST_PATH}")
    print("\nSTOP HERE. Review framing_raw.mp4 against:")
    print("  1. 2-3 full-height studs installed, evenly spaced, one direction, one frontier")
    print("  2. INSTALLED STUDS | BUILDER | EMPTY WALL LINE reads clearly")
    print("  3. no roof, glass, siding, door, or extra beams appear")
    print("  4. no studs appear anywhere else on the platform")
    print("  5. camera framing matches the decking-completion edit - no drift")
    print("\nDo NOT run the framing-completion edit until you have reviewed and approved this clip.")
    print("That is scripts/run_cliffside_video_1_part2_framing_edit.py - a separate script.")


if __name__ == "__main__":
    main()
