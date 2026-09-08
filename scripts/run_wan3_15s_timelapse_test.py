#!/usr/bin/env python3
"""WAN 3.0 15-SECOND CONTINUOUS TIMELAPSE TEST: a cost-down candidate for
one continuous ~15s generation with the same accelerated-montage feel as
the successful 8s Seedance 2.0 Fast benchmark - NOT the slow, continuous
style of either Wan Turbo experiment.

Model: WAN_3_0_STANDARD (`alibaba/wan-3.0/image-to-video` - app/providers/
video/fal.py), 480p. HIGH CONFIDENCE, cross-confirmed across multiple
fal.ai model-page searches: endpoint path, 2-30s duration range (15s well
within it), 480p/720p/1080p tiers, 9:16 support, and per-second pricing
($0.05/s at 480p). UNRESOLVED despite 7 search attempts (fal.ai itself is
unreachable from this sandbox, so this couldn't be pinned down against an
actual schema repo the way Seedance's was): the exact audio-control
field's name/type - sources disagree between a boolean flag ("sound" or
"enable_audio") and prompt-implicit control. Resolved by NOT sending any
audio field at all, and sending `duration` as a bare int (15) rather than
a string, per the one concrete code example found. Both choices fail
safely: a wrong field name/type means an immediate 4xx at submission
time - before any billable work starts - not a paid generation.

Creative prompt: imports `BENCHMARK_PROMPT` directly from
`scripts/run_seedance_benchmark_test` (the successful 8s benchmark) as
the base style/camera/attention language, rather than retyping it, then
extends it for 15 seconds of MORE construction progression (not the same
amount of progress stretched thinner) with an explicit multi-stage
montage structure: early framing -> jump/progress -> denser wall framing
-> jump/progress -> upper framing -> jump/progress -> roof structure/
bracing -> substantially more complete cabin. Natural jump/cut-like
progression is explicitly encouraged, not treated as a flaw to avoid.

Source image: `data/fal_mechanical_start_test/mechanical_start_frame.jpg`
(9:16 already) - reused via its own manifest.json, $0 image cost, no
image-generation call at all.

Safety, same pattern as every other real-call script in this repo:
  - Exactly 1 video call. Zero image calls. No loop, no alternate model,
    no retry.
  - Total cost checked against MAX_SPEND_USD (set exactly equal to the
    computed estimate, per instruction - no margin) BEFORE the call; one
    "type yes" confirmation gates it.
  - No automatic retries - any failure (including an immediate schema
    validation 4xx, which is the realistic risk given the unresolved
    audio-field question above) stops the script immediately, printing a
    `recover_fal_video_job.py <job_id>` hint if a job was already
    submitted.
  - manifest.json records the exact prompt, model, resolution, duration,
    cost, job id, and output path.

Usage (from the repo root, with FAL_API_KEY set in your .env, AFTER
scripts/run_mechanical_start_frame_test.py has already been run and its
frame approved):
    python -m scripts.run_wan3_15s_timelapse_test
    python -m scripts.run_wan3_15s_timelapse_test --yes
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
from scripts.run_seedance_benchmark_test import BENCHMARK_PROMPT as SEEDANCE_BENCHMARK_PROMPT

ASPECT_RATIO = "9:16"
RESOLUTION = "480p"
DURATION_SECONDS = 15.0

SOURCE_DIR = Path(__file__).resolve().parent.parent / "data" / "fal_mechanical_start_test"
SOURCE_MANIFEST_PATH = SOURCE_DIR / "manifest.json"

OUTPUT_DIR = Path(__file__).resolve().parent.parent / "data" / "fal_wan3_15s_timelapse_test"
MANIFEST_PATH = OUTPUT_DIR / "manifest.json"

POLL_INTERVAL_SECONDS = 5
MAX_WAIT_SECONDS = 420  # a 15s premium-tier generation may take longer than the Wan Turbo tests

# The Seedance benchmark's own proven camera/attention/environment/style
# language, imported verbatim above - reused as the base, then extended
# below for 15s of MORE progression (not the same amount of progress
# stretched across a longer clip) with an explicit multi-stage structure.
TIMELAPSE_PROMPT = (
    SEEDANCE_BENCHMARK_PROMPT
    + "\n\nThis is a longer, 15-second version of the same accelerated construction timelapse - it "
    "should show meaningfully MORE construction progress than a shorter clip would, not the same "
    "amount of progress paced more slowly. Natural jump/cut-like shifts in the construction state are "
    "good and expected - do not spend several seconds slowly completing one single action. The "
    "sequence should move through several distinct, visibly different construction stages: early "
    "framing work, then a noticeable jump forward in progress as wall framing becomes denser with "
    "more studs and beams, then another noticeable jump forward as upper framing develops, then "
    "another jump forward as roof structure and bracing are added, ending with the cabin substantially "
    "more complete than at the start. Each stage should look clearly and obviously further along than "
    "the one before it."
)

SUCCESS_CRITERIA = [
    "Reads as an accelerated construction timelapse/montage, not a slow continuous shot",
    "Multiple visually distinct construction stages are apparent across the 15s",
    "Cabin is dramatically more complete at the end than at the start",
    "Natural jump/cut-like progression is present and doesn't feel like a flaw",
    "Builder never acknowledges the camera",
    "Camera stays mostly stationary, side/three-quarter-rear observational",
    "Ocean/wind/environment show natural movement",
    "Construction only moves forward - no regressions or disappearing structure",
    "Feels like a stronger, longer version of the liked Seedance benchmark, not the Wan Turbo tests",
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
    manifest.json - same reuse pattern as every prior "reuse an approved
    image" script in this project."""
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
        description="Wan 3.0 standard 15s timelapse test, using the Seedance benchmark prompt as the creative base."
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
    print("WAN 3.0 15s TIMELAPSE TEST - THIS WILL SPEND REAL MONEY")
    print("=" * 70)
    print(f"Source image (reused, $0 image cost): {source_image_path}")
    print(f"\nPrompt (Seedance benchmark base + 15s multi-stage extension):\n  {TIMELAPSE_PROMPT}")
    print(f"\nModel: {WAN_3_0_STANDARD.submit_path}")
    print(f"Resolution: {RESOLUTION}   Duration: {DURATION_SECONDS:.0f}s   Aspect ratio: {ASPECT_RATIO}")
    print("Audio: no audio field sent (unresolved schema detail - see module docstring)")
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
        "experiment": "wan3_15s_timelapse",
        "creative_basis": "scripts.run_seedance_benchmark_test.BENCHMARK_PROMPT (imported, not retyped)",
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
        fail(
            f"submission failed: {e}\n"
            "      If this is a schema/validation error, it's the unresolved audio-field or "
            "duration-type question flagged in this script's docstring - no charge should have "
            "occurred (fal.ai validates the request before any billable work starts)."
        )
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

    video_path = OUTPUT_DIR / "wan3_15s_timelapse.mp4"
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
    print(f"wan3_15s_timelapse: {video_path}  (${actual_cost:.4f}, {total_seconds:.0f}s)")
    print(f"Manifest: {MANIFEST_PATH}")
    print("\nReview against the success criteria (compare against the liked Seedance benchmark,")
    print("NOT against either Wan Turbo test):")
    for item in SUCCESS_CRITERIA:
        print(f"  - {item}")


if __name__ == "__main__":
    main()
