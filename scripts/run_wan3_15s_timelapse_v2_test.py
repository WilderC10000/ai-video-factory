#!/usr/bin/env python3
"""WAN 3.0 15-SECOND TIMELAPSE TEST V2: fixes temporal pacing after the V1
result. V1 (scripts/run_wan3_15s_timelapse_test.py) succeeded technically
and visually, but the construction read as continuous and too slow - not
the extreme, hard-cut timelapse feel of the liked Seedance benchmark.

Root cause suspected: V1's prompt imported the Seedance benchmark prompt
verbatim and only appended a progression extension. That base prompt
contains phrases like "works continuously and rapidly" and "moves quickly
but plausibly between tasks" - language that plausibly nudged the model
toward simulating one continuous physical action rather than cutting
between discontinuous time-lapse states.

This version does NOT import or append to that prompt. It is a
substantially rewritten, standalone prompt built around hard temporal
jumps: ~6 explicit "HARD TIME JUMP" transitions across the 15s, each
showing a meaningfully more advanced construction state than the moment
before - sparse framing -> many more studs already exist -> walls
substantially framed -> upper beams/header -> roof framing appears ->
roof substantially developed -> dramatically more complete cabin. Between
jumps, only a brief burst of activity is described, not continuous work.

Model/config are UNCHANGED from V1: WAN_3_0_STANDARD (`alibaba/wan-3.0/
image-to-video`), 480p, 15s, 9:16, same source image
(`data/fal_mechanical_start_test/mechanical_start_frame.jpg`), same
`start_image_url` field (confirmed correct by V1's real 422/resubmission),
same omitted audio field, same $0.75 cost. Only the prompt differs.

Safety, same pattern as every other real-call script in this repo:
  - Exactly 1 video call. Zero image calls. No loop, no alternate model,
    no retry.
  - Hard cap set exactly equal to the computed estimate ($0.75) - checked
    BEFORE the call; one "type yes" confirmation gates it.
  - No automatic retries - any failure (including a schema-validation
    4xx, which cannot happen here since the schema is already confirmed
    from V1's real submission) stops the script immediately.
  - manifest.json records the exact prompt, model, resolution, duration,
    cost, job id, and output path. Own dedicated output directory so
    V1's result is never overwritten.

Usage (from the repo root, with FAL_API_KEY set in your .env, AFTER
scripts/run_mechanical_start_frame_test.py has already been run and its
frame approved):
    python -m scripts.run_wan3_15s_timelapse_v2_test
    python -m scripts.run_wan3_15s_timelapse_v2_test --yes
"""
import argparse
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

from app.config import settings
from app.providers.base import ProviderJobState, VideoGenerationRequest, VideoProviderError
from app.providers.video.fal import WAN_3_0_STANDARD, FalVideoProvider

ASPECT_RATIO = "9:16"
RESOLUTION = "480p"
DURATION_SECONDS = 15.0

SOURCE_DIR = Path(__file__).resolve().parent.parent / "data" / "fal_mechanical_start_test"
SOURCE_MANIFEST_PATH = SOURCE_DIR / "manifest.json"

OUTPUT_DIR = Path(__file__).resolve().parent.parent / "data" / "fal_wan3_15s_timelapse_v2_test"
MANIFEST_PATH = OUTPUT_DIR / "manifest.json"

POLL_INTERVAL_SECONDS = 5
MAX_WAIT_SECONDS = 420

# Rewritten from scratch (not appended to the V1/Seedance-derived prompt)
# around hard temporal jumps rather than continuous real-time motion.
TIMELAPSE_PROMPT = (
    "This is an EDITED, EXTREME TIME-LAPSE CONSTRUCTION MONTAGE compressing MANY HOURS of building "
    "a timber cabin into 15 seconds. It is NOT continuous real-time footage and NOT one continuous "
    "physical action - it is a rapid sequence of time-lapse jumps, like footage from a construction "
    "time-lapse camera where hours have passed between each cut.\n\n"
    "Vertical 9:16. A rugged male builder in his 40s works on the partially framed timber cabin on a "
    "dramatic ocean-cliff site at golden hour. He never looks toward the camera - his attention stays "
    "on the tools, materials, and structure at all times. The camera is a mostly stationary, "
    "observational side/three-quarter-rear angle, as though a fixed time-lapse camera is documenting "
    "the build from a slight distance - no orbiting, no cinematic camera movement, no posing.\n\n"
    "The 15 seconds contain approximately 6 HARD TIME JUMPS in construction state, each one showing a "
    "meaningfully more advanced structure than the moment before - not smooth continuous progress. "
    "Between jumps, show only a very short burst of believable construction activity (a few seconds at "
    "most), then cut to a visibly more advanced state, as if hours passed. Lumber, studs, beams, and "
    "roof components may already be installed immediately after a jump without showing every "
    "individual installation - this is expected and desirable, not a flaw.\n\n"
    "Roughly: sparse initial framing with the builder working, HARD TIME JUMP, many additional wall "
    "studs already exist and the builder is working elsewhere on the structure, HARD TIME JUMP, walls "
    "substantially framed, HARD TIME JUMP, upper beams and header structure installed, HARD TIME JUMP, "
    "roof framing rapidly appears, HARD TIME JUMP, roof structure substantially developed, HARD TIME "
    "JUMP, a dramatically more complete timber cabin.\n\n"
    "The viewer should perceive an obvious change in the building approximately every 2 seconds. "
    "Construction progress - not the builder, not the camera - is the dominant visual event. Previously "
    "completed structural elements remain in place; construction only ever moves forward, never "
    "backward or sideways.\n\n"
    "The ocean and cliff remain visible around the worksite, with natural wave motion and wind. Do NOT "
    "show slow continuous construction, lingering on one action, one board taking several seconds to "
    "install, cinematic slow motion, camera orbiting, posing, or long uninterrupted tool use. This "
    "should feel like 15 seconds extracted from a rapid 'cabin built from nothing' construction "
    "time-lapse video - not a 15-second cinematic scene of a carpenter working."
)

SUCCESS_CRITERIA = [
    "Feels like an EXTREME time-lapse/montage, not continuous real-time footage",
    "A perceptible change in the building roughly every ~2 seconds",
    "~6 hard, obvious jumps in construction state across the 15s",
    "Structure is dramatically more complete at the end vs. V1's more gradual result",
    "Builder never acknowledges the camera",
    "Camera stays mostly stationary, side/three-quarter-rear observational",
    "Ocean/wind/environment show natural movement",
    "Construction only moves forward - no regressions or disappearing structure",
    "Materially more 'time-lapse' feeling than V1 (data/fal_wan3_15s_timelapse_test/)",
]


def fail(message: str) -> None:
    print(f"\nSTOPPED: {message}")
    print(f"No retry, no alternate model - the script is exiting now. Manifest: {MANIFEST_PATH}")
    sys.exit(1)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def save_manifest(manifest: dict) -> None:
    MANIFEST_PATH.parent.mkdir(parents=True, exist_ok=True)
    MANIFEST_PATH.write_text(json.dumps(manifest, indent=2))


def load_source_image() -> str:
    """Reads the approved mechanical start frame's path out of its own
    manifest.json - same reuse pattern as V1 and every prior "reuse an
    approved image" script in this project."""
    if not SOURCE_MANIFEST_PATH.exists():
        fail(
            f"Source manifest not found at {SOURCE_MANIFEST_PATH}. This experiment reuses the "
            "approved mechanical_start_frame.jpg - run scripts/run_mechanical_start_frame_test.py first."
        )
    source_manifest = json.loads(SOURCE_MANIFEST_PATH.read_text())
    output_path = source_manifest.get("output_path")
    if not output_path:
        fail(f"Manifest at {SOURCE_MANIFEST_PATH} has no output_path recorded.")
    image_path = Path(output_path)
    if not image_path.exists() or image_path.stat().st_size == 0:
        fail(f"Approved source image not found (or empty) at {image_path}.")
    return str(image_path)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Wan 3.0 15s timelapse test V2: rewritten hard-time-jump prompt, same model/config as V1."
    )
    parser.add_argument("--yes", action="store_true", help="Skip the 'type yes' confirmation prompt")
    args = parser.parse_args()

    key_preview = f"{settings.fal_api_key[:6]}..." if settings.fal_api_key else None
    print(f"FAL_API_KEY loaded from .env: {'yes (' + key_preview + ')' if key_preview else 'NO'}")
    if not settings.fal_api_key:
        fail("FAL_API_KEY is not set. Add FAL_API_KEY=your_key_here to your .env file and try again.")

    source_image_path = load_source_image()
    provider = FalVideoProvider(WAN_3_0_STANDARD)
    request = VideoGenerationRequest(
        prompt=TIMELAPSE_PROMPT,
        reference_image_path=source_image_path,
        aspect_ratio=ASPECT_RATIO,
        duration_seconds=DURATION_SECONDS,
        extra_params={"resolution": RESOLUTION},
    )
    cost = provider.estimate_cost(request)
    max_spend_usd = cost  # hard cap set exactly equal to the verified expected cost, per instruction

    print("=" * 70)
    print("WAN 3.0 15s TIMELAPSE TEST V2 (temporal pacing fix) - THIS WILL SPEND REAL MONEY")
    print("=" * 70)
    print(f"Source image (reused, $0 image cost): {source_image_path}")
    print(f"\nPrompt (rewritten from scratch - NOT appended to V1's Seedance-derived prompt):\n  {TIMELAPSE_PROMPT}")
    print(f"\nModel: {WAN_3_0_STANDARD.submit_path}")
    print(f"Resolution: {RESOLUTION}   Duration: {DURATION_SECONDS:.0f}s   Aspect ratio: {ASPECT_RATIO}")
    print("Audio: no audio field sent (unchanged from V1)")
    print(f"\nEstimated cost: ${cost:.4f}  ($0.05/s x {DURATION_SECONDS:.0f}s)")
    print(f"Hard cap:       ${max_spend_usd:.4f}  (set exactly equal to the estimate, no margin)")
    print("Rules: exactly 1 video call, 0 image calls, 0 retries, 0 alternate models.")
    print("=" * 70)

    if not args.yes:
        answer = input(f"\nType 'yes' to spend up to ${cost:.4f} and proceed: ").strip().lower()
        if answer != "yes":
            print("Cancelled. Nothing was generated.")
            sys.exit(0)

    manifest = {
        "created_at": _now(),
        "experiment": "wan3_15s_timelapse_v2_temporal_pacing_fix",
        "compared_against": "wan3_15s_timelapse (V1) - continuous/too-slow result",
        "creative_basis": "rewritten from scratch, NOT appended to the V1/Seedance-derived prompt",
        "source_image_path": source_image_path,
        "reused_from_manifest": str(SOURCE_MANIFEST_PATH),
        "model": WAN_3_0_STANDARD.submit_path,
        "prompt": TIMELAPSE_PROMPT,
        "resolution": RESOLUTION,
        "duration_seconds": DURATION_SECONDS,
        "aspect_ratio": ASPECT_RATIO,
        "max_spend_usd": max_spend_usd,
        "estimated_cost_usd": cost,
        "provider_job_id": None,
        "status_url": None,
        "response_url": None,
        "actual_cost_usd": None,
        "video_path": None,
        "submitted_at": None,
        "completed_at": None,
    }
    save_manifest(manifest)

    print("\n[submit] Submitting the one 15s generation...")
    t_submit = time.monotonic()
    try:
        submitted = provider.submit_video_job(request)
    except VideoProviderError as e:
        fail(f"submission failed: {e}")
    print(f"         Submitted. Provider job id: {submitted.provider_job_id} "
          f"(estimated ${submitted.estimated_cost_usd:.4f})")

    manifest["provider_job_id"] = submitted.provider_job_id
    manifest["status_url"] = submitted.meta.get("status_url")
    manifest["response_url"] = submitted.meta.get("response_url")
    manifest["submitted_at"] = _now()
    save_manifest(manifest)

    print("         Polling (no retries on error - any failure stops the script)...")
    result = None
    while True:
        elapsed = time.monotonic() - t_submit
        if elapsed > MAX_WAIT_SECONDS:
            fail(
                f"gave up after {elapsed:.0f}s waiting (job may still complete and be billed on "
                f"fal.ai's side - check https://fal.ai/dashboard/billing). To check on it later "
                f"without spending anything again, run:\n"
                f"      python -m scripts.recover_fal_video_job {submitted.provider_job_id}"
            )
        try:
            result = provider.get_job_status(submitted.provider_job_id, meta=submitted.meta)
        except VideoProviderError as e:
            fail(
                f"status check failed: {e}\n"
                f"      To check on it later without spending anything again, run:\n"
                f"      python -m scripts.recover_fal_video_job {submitted.provider_job_id}"
            )
        if result.status == ProviderJobState.PROCESSING:
            print(f"         ...still processing ({elapsed:.0f}s elapsed)")
            time.sleep(POLL_INTERVAL_SECONDS)
            continue
        break

    if result.status == ProviderJobState.FAILED:
        fail(f"provider reported generation failure: {result.error_message}")

    video_path = OUTPUT_DIR / "wan3_15s_timelapse_v2.mp4"
    try:
        provider.download_result(submitted.provider_job_id, result.output_url, str(video_path))
    except VideoProviderError as e:
        fail(
            f"download failed (already billed, only the local save failed): {e}\n"
            f"      To retry just the download, run:\n"
            f"      python -m scripts.recover_fal_video_job {submitted.provider_job_id}"
        )

    actual_cost = result.actual_cost_usd if result.actual_cost_usd is not None else submitted.estimated_cost_usd
    manifest["actual_cost_usd"] = actual_cost
    manifest["video_path"] = str(video_path)
    manifest["completed_at"] = _now()
    save_manifest(manifest)

    total_seconds = time.monotonic() - t_submit
    print("\n" + "=" * 70)
    print("DONE - 1 clip generated. No further generation will happen automatically.")
    print("=" * 70)
    print(f"wan3_15s_timelapse_v2: {video_path}  (${actual_cost:.4f}, {total_seconds:.0f}s)")
    print(f"Manifest: {MANIFEST_PATH}")
    print("\nCompare directly against data/fal_wan3_15s_timelapse_test/wan3_15s_timelapse.mp4 (V1).")
    print("Review against the success criteria:")
    for item in SUCCESS_CRITERIA:
        print(f"  - {item}")


if __name__ == "__main__":
    main()
