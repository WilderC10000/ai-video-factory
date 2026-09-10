#!/usr/bin/env python3
"""CLIFFSIDE VIDEO #1, PART 2 - SHOT 3: FINAL DETAIL.

Only runnable after Jump Cut 2 (exterior-completion edit) has been
generated AND approved - requires exterior_complete_edit.jpg to already
exist, and additionally asks you to explicitly confirm you've reviewed
and approved it before submitting anything. exterior_complete_edit.jpg is
only ever read, never modified.

One small, clearly visible finishing action only (door handle, one trim
piece, one small exterior adjustment) - the cabin is already essentially
complete going in and stays that way; this exists purely to give one last
believable human construction beat before the Reveal.

Makes exactly ONE Wan 3.0 video call. No retries. Does NOT chain to the
Reveal - that is a separate script, run only after this stage's own
output is reviewed and approved.

Usage (from the repo root, with FAL_API_KEY set in your .env, and
exterior_complete_edit.jpg already generated and reviewed):
    python -m scripts.run_cliffside_video_1_part2_final_detail
    python -m scripts.run_cliffside_video_1_part2_final_detail --yes   (skips only the cost confirmation - the upstream-approval confirmation always runs)
"""
import dataclasses
import json
import sys
import time
from datetime import datetime, timezone

from app.config import settings
from app.providers.base import ProviderJobState, VideoGenerationRequest, VideoProviderError
from app.providers.video.fal import WAN_3_0_STANDARD, FalVideoProvider
from scripts.run_cliffside_video_1_part2_exterior_edit import EXTERIOR_COMPLETE_EDIT_PATH
from scripts.run_cliffside_video_1_rough_assembly import MANIFEST_PATH, OUTPUT_DIR

ASPECT_RATIO = "9:16"
RESOLUTION = "480p"
MAX_SPEND_USD = 0.25
DURATION_SECONDS = 5.0
POLL_INTERVAL_SECONDS = 3
MAX_WAIT_SECONDS = 300

FINAL_DETAIL_RAW_PATH = OUTPUT_DIR / "final_detail_raw.mp4"
JOB_STATE_PATH = OUTPUT_DIR / "final_detail_last_job.json"

CAMERA_CLAUSE = (
    "Camera view: the fixed viewpoint established by the previous edit, held completely steady. "
    "No camera movement, no further angle change."
)

# Visual-only - no audio instructions. Exactly one small finishing
# action - no further structural change of any kind.
FINAL_DETAIL_PROMPT = (
    "Vertical 9:16, realistic construction footage, documentary/observational style. "
    f"{CAMERA_CLAUSE} Continuing directly from the current state shown in the starting image.\n\n"
    "The cabin is essentially complete: the approximately 12 by 16 foot cabin stands finished on "
    "the platform, with its glass panels, door, dark-toned exterior cladding, and finished roof "
    "all in place, matching exactly what is shown in the starting image. The builder performs one "
    "small, clearly visible finishing action only - installing a door handle, fastening a single "
    "piece of trim, or adjusting one small exterior detail - and nothing else about the cabin "
    "changes. No new construction, no additional materials, no structural changes of any kind. "
    "The ocean, cliff, and coastline remain visible and consistent around the platform. No "
    "posing, no presenter behavior."
)

WAN_3_0_CLIFFSIDE_FINAL_DETAIL = dataclasses.replace(WAN_3_0_STANDARD, extra_payload={"duration": 5})


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

    if not EXTERIOR_COMPLETE_EDIT_PATH.exists():
        fail(
            f"{EXTERIOR_COMPLETE_EDIT_PATH} not found - Jump Cut 2 (exterior-completion edit) has "
            "not been generated yet. Run scripts/run_cliffside_video_1_part2_exterior_edit.py first."
        )

    print(f"\nUpstream file found: {EXTERIOR_COMPLETE_EDIT_PATH}")
    approval = input(
        "Have you reviewed and approved exterior_complete_edit.jpg? Type 'yes' to confirm before "
        "proceeding (anything else stops here, nothing generated): "
    ).strip().lower()
    if approval != "yes":
        print("Stopped - the exterior-completion edit was not confirmed as approved. Nothing was generated.")
        sys.exit(0)

    video_provider = FalVideoProvider(WAN_3_0_CLIFFSIDE_FINAL_DETAIL)
    video_request = VideoGenerationRequest(
        prompt=FINAL_DETAIL_PROMPT,
        reference_image_path=str(EXTERIOR_COMPLETE_EDIT_PATH),
        aspect_ratio=ASPECT_RATIO,
        duration_seconds=DURATION_SECONDS,
        extra_params={"resolution": RESOLUTION},
    )
    video_cost = video_provider.estimate_cost(video_request)

    print("=" * 70)
    print("CLIFFSIDE VIDEO #1 - PART 2 - SHOT 3 (FINAL DETAIL) - THIS WILL SPEND REAL MONEY")
    print("=" * 70)
    print(f"Video model: {WAN_3_0_CLIFFSIDE_FINAL_DETAIL.submit_path}  ({RESOLUTION}, {ASPECT_RATIO}, {DURATION_SECONDS:.0f}s)")
    print(f"Source image: {EXTERIOR_COMPLETE_EDIT_PATH}")
    print(f"\nVideo prompt:\n  {FINAL_DETAIL_PROMPT}")
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
    manifest["final_detail"] = {
        "video_model": WAN_3_0_CLIFFSIDE_FINAL_DETAIL.submit_path,
        "resolution": RESOLUTION,
        "aspect_ratio": ASPECT_RATIO,
        "duration_seconds": DURATION_SECONDS,
        "video_prompt": FINAL_DETAIL_PROMPT,
        "start_frame_path": str(EXTERIOR_COMPLETE_EDIT_PATH),
        "max_spend_usd": MAX_SPEND_USD,
        "estimated_cost_usd": video_cost,
        "raw_video_path": None,
        "actual_cost_usd": None,
        "completed_at": None,
    }
    save_manifest(manifest)

    print(f"\n[1/1] Submitting Final Detail video generation job (Wan 3.0 standard, {RESOLUTION})...")
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
        video_provider.download_result(submitted.provider_job_id, result.output_url, str(FINAL_DETAIL_RAW_PATH))
    except VideoProviderError as e:
        fail(
            f"Download failed (generation already succeeded and was billed, but the local save failed): {e}\n"
            f"      To retry just the download without spending anything again, run:\n"
            f"      python -m scripts.recover_fal_video_job {submitted.provider_job_id}"
        )

    actual_cost = result.actual_cost_usd if result.actual_cost_usd is not None else submitted.estimated_cost_usd

    manifest["final_detail"]["raw_video_path"] = str(FINAL_DETAIL_RAW_PATH)
    manifest["final_detail"]["actual_cost_usd"] = actual_cost
    manifest["final_detail"]["completed_at"] = _now()
    save_manifest(manifest)

    print("\n" + "=" * 70)
    print("SHOT 3 (FINAL DETAIL) DONE - stopping completely, as required.")
    print("=" * 70)
    print(f"Final detail raw: {FINAL_DETAIL_RAW_PATH}")
    print(f"Actual cost:       ${actual_cost:.4f}")
    print(f"Manifest:          {MANIFEST_PATH}")
    print("\nSTOP HERE. Review final_detail_raw.mp4 against:")
    print("  1. exactly one small finishing action shown - no further structural change")
    print("  2. the cabin matches the exterior-completion edit exactly throughout")
    print("  3. camera framing matches the exterior-completion edit - no drift")
    print("\nDo NOT run the Reveal until you have reviewed and approved this clip.")
    print("That is scripts/run_cliffside_video_1_part2_reveal.py - a separate script.")


if __name__ == "__main__":
    main()
