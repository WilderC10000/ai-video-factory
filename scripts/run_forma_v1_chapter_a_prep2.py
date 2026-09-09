#!/usr/bin/env python3
"""FORMA VIDEO #1 - CHAPTER A, STAGE A3: SITE PREP CLIP 2.

Only runnable after Stage A2 (Site Prep Clip 1) has been generated AND
approved by you - requires site_prep_clip1_raw.mp4 to already exist, and
additionally asks you to explicitly confirm you've reviewed and approved
it before submitting anything, same double-gate pattern as Stage A2.

Starting image is the REAL last frame of Stage A2's raw output
(site_prep_clip1_raw.mp4), extracted locally - free, no API call.
site_prep_clip1_raw.mp4 is only ever read, never modified. Same camera as
Hook/Prep 1 (CAMERA_CLAUSE_A, imported unchanged).

Visual-only prompt - no audio instructions of any kind. This clip ends
Chapter A: the site reads as fully cleared and mechanically leveled,
still with zero structure - ready for foundation work. That real final
frame becomes the source for Chapter B's future NANO_BANANA_PRO_EDIT
camera transition (a separate, later step, not part of this script).

REDESIGNED alongside Prep 1 per the permanent FORMA Site Prep Rule (the
original hand-clearing version was rejected for not reading as meaningful
site preparation).

REDESIGNED AGAIN to match Prep 1's own real, approved result: Prep 1's
scoop/swing/dump excavator loop was itself rejected as the permanent
formula in favor of a single continuous sweeping blade action, which was
then generated for real and approved. Prep 2 now continues that same
compact tracked blade machine from Prep 1's actual real last frame:
ADVANCE -> PUSH/LEVEL -> SHIFT -> COMPLETE. The machine keeps advancing
in the same direction, blade down, clearing and leveling the remaining
rough ground while the already-cleared pad and the existing debris ridge
stay exactly as Prep 1 left them - ending with the entire intended pad
reading as fully cleared, flat, and ready for foundation work. No new
machinery, no method switch mid-clip.

Makes exactly ONE Wan 3.0 video call. No retries. Does NOT trigger Stage
A4 (local assembly) - that is a separate, free, non-API script, run only
after this stage's own output is reviewed and approved.

Safety, same pattern as every other real-call script in this repo:
  - Exactly 1 video-generation call. No image call, no retry.
  - Hard cap set exactly equal to the computed cost ($0.40) - zero
    margin.
  - Job state saved to disk immediately after submission.

Usage (from the repo root, with FAL_API_KEY set in your .env, and
site_prep_clip1_raw.mp4 already generated and reviewed):
    python -m scripts.run_forma_v1_chapter_a_prep2
    python -m scripts.run_forma_v1_chapter_a_prep2 --yes   (skips only the cost confirmation - the upstream-approval confirmation always runs)
"""
import dataclasses
import json
import sys
import time
from datetime import datetime, timezone

from app.config import settings
from app.providers.base import ProviderJobState, VideoGenerationRequest, VideoProviderError
from app.providers.video.fal import WAN_3_0_STANDARD, FalVideoProvider
from app.services.frame_extraction import FrameExtractionError, extract_last_frame
from scripts.run_forma_v1_chapter_a_hook import ASPECT_RATIO, CAMERA_CLAUSE_A, MANIFEST_PATH, OUTPUT_DIR, RESOLUTION
from scripts.run_forma_v1_chapter_a_prep1 import PREP1_RAW_PATH

MAX_SPEND_USD = 0.40
DURATION_SECONDS = 8.0
POLL_INTERVAL_SECONDS = 3
MAX_WAIT_SECONDS = 300

PREP2_START_FRAME_PATH = OUTPUT_DIR / "site_prep_clip2_start_frame.jpg"
PREP2_RAW_PATH = OUTPUT_DIR / "site_prep_clip2_raw.mp4"
JOB_STATE_PATH = OUTPUT_DIR / "prep2_last_job.json"

# Visual-only - no audio instructions, per explicit instruction. Continues
# Prep 1's real, approved sweeping-blade result (not the earlier,
# rejected excavator formula): ADVANCE -> PUSH/LEVEL -> SHIFT -> COMPLETE.
# Same machine, same site, same debris ridge - no new machinery, no
# method switch. Priority: (1) the same blade machine visibly causes the
# remaining transformation, (2) it continues in one consistent direction
# from the actual cleared frontier Prep 1 left, (3) the existing debris
# ridge/pile stays consistent, (4) cleared stays cleared and untouched
# stays untouched until reached, (5) by the end the whole intended pad
# reads as fully cleared, flat, and ready for foundation work.
PREP2_PROMPT = (
    "Vertical 9:16, realistic construction footage, documentary/observational style. "
    f"{CAMERA_CLAUSE_A} No camera movement, no angle change - this is a direct continuation of "
    "the sweeping site-clearing operation shown in the starting image; the cleared pad, the "
    "debris ridge, and the machine's position must remain exactly as shown, unchanged.\n\n"
    "The same compact tracked skid-steer continues from exactly where it left off, blade still "
    "down: it keeps advancing forward in the same direction, its wide blade pushing the remaining "
    "loose rock, mud, and debris ahead of it and adding it to the same existing debris ridge, "
    "while also passing back over the ground it has just crossed to level and smooth it flat. "
    "Behind the machine, the cleared ground stays cleared and grows flatter; ahead of it, the "
    "remaining rough ground stays completely untouched until the machine reaches it - nothing "
    "changes anywhere else on the site. No new machinery appears and the method never changes "
    "mid-clip. By the end of the clip, the machine has advanced across the remaining rough "
    "ground until none is left: the entire intended build area reads as fully cleared, flat, and "
    "ready for foundation work - still with no structure of any kind. The waterfall remains "
    "visible and in motion beside the cave; mist continues to drift. No posing, no presenter "
    "behavior."
)

WAN_3_0_FORMA_V1_PREP2 = dataclasses.replace(WAN_3_0_STANDARD, extra_payload={"duration": 8})


def fail(message: str) -> None:
    print(f"\nSTOPPED: {message}")
    print("No retry, no further generation - the script is exiting now.")
    sys.exit(1)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def load_manifest() -> dict:
    if MANIFEST_PATH.exists():
        return json.loads(MANIFEST_PATH.read_text())
    return {"experiment": "forma_video_1_chapter_a", "created_at": _now()}


def save_manifest(manifest: dict) -> None:
    MANIFEST_PATH.parent.mkdir(parents=True, exist_ok=True)
    MANIFEST_PATH.write_text(json.dumps(manifest, indent=2))


def main() -> None:
    skip_confirm = "--yes" in sys.argv[1:]

    key_preview = f"{settings.fal_api_key[:6]}..." if settings.fal_api_key else None
    print(f"FAL_API_KEY loaded from .env: {'yes (' + key_preview + ')' if key_preview else 'NO'}")
    if not settings.fal_api_key:
        fail("FAL_API_KEY is not set. Add FAL_API_KEY=your_key_here to your .env file and try again.")

    if not PREP1_RAW_PATH.exists():
        fail(
            f"{PREP1_RAW_PATH} not found - Stage A2 (Site Prep Clip 1) has not been generated "
            "yet. Run scripts/run_forma_v1_chapter_a_prep1.py first."
        )

    # Mandatory upstream-approval gate - NOT the same as the cost
    # confirmation below, and not skippable by --yes.
    print(f"\nUpstream file found: {PREP1_RAW_PATH}")
    approval = input(
        "Have you reviewed and approved site_prep_clip1_raw.mp4? Type 'yes' to confirm before "
        "proceeding (anything else stops here, nothing generated): "
    ).strip().lower()
    if approval != "yes":
        print("Stopped - Prep 1 was not confirmed as approved. Nothing was generated.")
        sys.exit(0)

    print(f"\n[1/2] Extracting the real last frame of site_prep_clip1_raw.mp4 locally (no API call)...")
    try:
        extract_last_frame(PREP1_RAW_PATH, PREP2_START_FRAME_PATH)
    except FrameExtractionError as e:
        fail(f"Frame extraction failed: {e}")
    print(f"      Done -> {PREP2_START_FRAME_PATH} (site_prep_clip1_raw.mp4 was only read, never modified)")

    video_provider = FalVideoProvider(WAN_3_0_FORMA_V1_PREP2)
    video_request = VideoGenerationRequest(
        prompt=PREP2_PROMPT,
        reference_image_path=str(PREP2_START_FRAME_PATH),
        aspect_ratio=ASPECT_RATIO,
        duration_seconds=DURATION_SECONDS,
        extra_params={"resolution": RESOLUTION},
    )
    video_cost = video_provider.estimate_cost(video_request)

    print("=" * 70)
    print("FORMA VIDEO #1 - CHAPTER A - STAGE A3 (SITE PREP CLIP 2) - THIS WILL SPEND REAL MONEY")
    print("=" * 70)
    print(f"Video model: {WAN_3_0_FORMA_V1_PREP2.submit_path}  ({RESOLUTION}, {ASPECT_RATIO}, {DURATION_SECONDS:.0f}s)")
    print(f"Source image: {PREP2_START_FRAME_PATH} (real extracted pixels from Prep 1's raw output)")
    print(f"\nVideo prompt:\n  {PREP2_PROMPT}")
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
    manifest["prep2"] = {
        "video_model": WAN_3_0_FORMA_V1_PREP2.submit_path,
        "resolution": RESOLUTION,
        "aspect_ratio": ASPECT_RATIO,
        "duration_seconds": DURATION_SECONDS,
        "video_prompt": PREP2_PROMPT,
        "start_frame_path": str(PREP2_START_FRAME_PATH),
        "max_spend_usd": MAX_SPEND_USD,
        "estimated_cost_usd": video_cost,
        "raw_video_path": None,
        "actual_cost_usd": None,
        "completed_at": None,
    }
    save_manifest(manifest)

    print(f"\n[2/2] Submitting Site Prep Clip 2 video generation job (Wan 3.0 standard, {RESOLUTION})...")
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
        video_provider.download_result(submitted.provider_job_id, result.output_url, str(PREP2_RAW_PATH))
    except VideoProviderError as e:
        fail(
            f"Download failed (generation already succeeded and was billed, but the local save failed): {e}\n"
            f"      To retry just the download without spending anything again, run:\n"
            f"      python -m scripts.recover_fal_video_job {submitted.provider_job_id}"
        )

    actual_cost = result.actual_cost_usd if result.actual_cost_usd is not None else submitted.estimated_cost_usd

    manifest["prep2"]["raw_video_path"] = str(PREP2_RAW_PATH)
    manifest["prep2"]["actual_cost_usd"] = actual_cost
    manifest["prep2"]["completed_at"] = _now()
    save_manifest(manifest)

    print("\n" + "=" * 70)
    print("STAGE A3 (SITE PREP CLIP 2) DONE - stopping completely, as required.")
    print("=" * 70)
    print(f"Site Prep Clip 2 raw: {PREP2_RAW_PATH}")
    print(f"Actual cost:          ${actual_cost:.4f}")
    print(f"Manifest:             {MANIFEST_PATH}")
    print("\nSTOP HERE. Review site_prep_clip2_raw.mp4 in this priority order:")
    print("  1. the same blade machine visibly causes the remaining transformation")
    print("  2. continues in one consistent direction from the actual cleared frontier Prep 1 left")
    print("  3. the existing debris ridge/pile from Prep 1 stays consistent (not a new one)")
    print("  4. cleared ground stays cleared; untouched ground stays untouched until reached")
    print("  5. by the end, the whole intended pad reads as fully cleared, flat, ready to build on")
    print("  Also: no new machinery introduced, no method switch mid-clip;")
    print("  continues directly from Prep 1's real last frame - machine position unchanged;")
    print("  no construction of any kind appears yet; camera framing identical throughout")
    print("\nOnce all three clips (Hook, Prep 1, Prep 2) are approved, run Stage A4 for local,")
    print("free FFmpeg acceleration + concatenation: scripts/run_forma_v1_chapter_a_assemble.py")
    print("(no API key needed, no paid calls, not run automatically by this script).")


if __name__ == "__main__":
    main()
