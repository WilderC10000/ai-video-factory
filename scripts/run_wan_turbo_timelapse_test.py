#!/usr/bin/env python3
"""COST-DOWN CONSTRUCTION-TIMELAPSE TEST: how close can the $0.05 Wan
Turbo endpoint get to the Seedance 2.0 Fast benchmark's construction-
timelapse feel, at roughly 1/40th the cost?

Re-verified (Sept 2026) before writing this script: the Turbo endpoint
(`fal-ai/wan/v2.2-a14b/image-to-video/turbo`) takes a `num_frames` param,
81-100 inclusive, default 81 (~5.06s @ 16fps) - frame counts above 81 bill
at a 1.25x multiplier, which would break the flat $0.05 (480p) rate this
experiment is specifically testing. 15 seconds is NOT achievable on this
endpoint at any price - the absolute ceiling is 100 frames (~6.25s), which
would also cost more than $0.05. So this is the closest valid experiment
at exactly one $0.05 generation: ~5 seconds (81 frames), pinned explicitly
via `WAN_TURBO.extra_payload["num_frames"] = 81` (see
app/providers/video/fal.py) rather than left to the API's own default.

Also re-verified: this endpoint has no native audio parameter (Wan's
audio-capable sibling is a separate Speech-to-Video model that takes an
input audio file - a different capability, not used here). No audio is
requested; SFX stays a future editing-pipeline concern, per instruction.

Source image: `data/fal_mechanical_start_test/mechanical_start_frame.jpg` -
same approved composition and corrected saw-adjacent mechanics used for
the Seedance benchmark, reused via its own manifest.json. $0 image cost -
this script makes NO image call at all.

Prompt strategy: optimized for Wan Turbo's actual strengths, not a scaled-
down copy of the Seedance prompt. Broad, visible construction progression
(carrying lumber, adding studs/bracing, cabin getting denser) rather than
demanding continuous, mechanically precise tool physics - explicitly NOT
another slow circular-saw mechanics test. Environmental motion (waves,
wind) is called out because it made the Seedance clip feel alive.

Safety, same pattern as every other real-call script in this repo:
  - Exactly 1 video call. Zero image calls (source image reused as-is).
    No loop, no alternate model, no retry.
  - Total cost checked against MAX_SPEND_USD (exactly $0.05 - flat,
    deterministic billing, no per-second variability to leave margin for)
    BEFORE the call; one "type yes" confirmation gates it.
  - No automatic retries - any failure stops the script immediately,
    printing a `recover_fal_video_job.py <job_id>` hint if already submitted.
  - manifest.json records the exact prompt, model, resolution, frame
    count, cost, job id, and output path.

Usage (from the repo root, with FAL_API_KEY set in your .env, AFTER
scripts/run_mechanical_start_frame_test.py has already been run and its
frame approved):
    python -m scripts.run_wan_turbo_timelapse_test
    python -m scripts.run_wan_turbo_timelapse_test --yes
"""
import argparse
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

from app.config import settings
from app.providers.base import ProviderJobState, VideoGenerationRequest, VideoProviderError
from app.providers.video.fal import WAN_TURBO, FalVideoProvider

MAX_SPEND_USD = 0.05
ASPECT_RATIO = "9:16"
RESOLUTION = "480p"
NUM_FRAMES = 81  # ~5.06s @ 16fps - fal.ai's documented default, pinned explicitly (see WAN_TURBO config)
POLL_INTERVAL_SECONDS = 3
MAX_WAIT_SECONDS = 180  # Turbo is fast; the Seedance benchmark's longer timeout isn't needed here

SOURCE_DIR = Path(__file__).resolve().parent.parent / "data" / "fal_mechanical_start_test"
SOURCE_MANIFEST_PATH = SOURCE_DIR / "manifest.json"

OUTPUT_DIR = Path(__file__).resolve().parent.parent / "data" / "fal_wan_turbo_timelapse_test"
MANIFEST_PATH = OUTPUT_DIR / "manifest.json"

BENCHMARK_PROMPT = (
    "Vertical 9:16 accelerated construction timelapse, documentary/observational style. A "
    "rugged male builder in his 40s, wearing worn work clothes, works quickly on a partially "
    "framed timber cabin on a dramatic ocean-cliff site at golden hour. He is completely "
    "absorbed in the work and never looks toward the camera - his attention stays on the tools, "
    "materials, and structure. The camera stays in a mostly fixed side/three-quarter-rear "
    "observational position, as though someone is quietly filming him work from a slight "
    "distance; no orbiting, no dramatic camera moves, no centered hero framing.\n\n"
    "He rapidly carries lumber, positions framing, and adds studs and bracing to the cabin "
    "structure - the framing becomes visibly denser and the cabin looks noticeably more "
    "complete by the end. Construction only moves forward; nothing already built disappears. "
    "The ocean waves and wind add natural movement to the scene, and his clothing and loose "
    "materials move naturally too. The dramatic ocean-cliff landscape stays visible around the "
    "worksite. No posing, no presenter behavior, no commercial aesthetic - this should read as "
    "genuine, fast-paced construction timelapse footage."
)

SUCCESS_CRITERIA = [
    "Feels like accelerated construction",
    "Cabin visibly progresses",
    "Builder doesn't acknowledge camera",
    "Environment remains recognizable",
    "Major structure remains coherent",
    "Any morphing/fuzziness is tolerable at normal timelapse playback",
    "Enough usable footage to realistically use in the final video",
    "Feels surprisingly good considering the $0.05 generation price",
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
    manifest.json - same reuse pattern as the Seedance benchmark and every
    prior "reuse an approved image" script in this project."""
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
        description="Wan Turbo cost-down timelapse test: 1 $0.05 video generation from the approved mechanical start frame."
    )
    parser.add_argument("--yes", action="store_true", help="Skip the 'type yes' confirmation prompt")
    args = parser.parse_args()

    key_preview = f"{settings.fal_api_key[:6]}..." if settings.fal_api_key else None
    print(f"FAL_API_KEY loaded from .env: {'yes (' + key_preview + ')' if key_preview else 'NO'}")
    if not settings.fal_api_key:
        fail("FAL_API_KEY is not set. Add FAL_API_KEY=your_key_here to your .env file and try again.")

    source_image_path = load_source_image()
    provider = FalVideoProvider(WAN_TURBO)
    request = VideoGenerationRequest(
        prompt=BENCHMARK_PROMPT,
        reference_image_path=source_image_path,
        aspect_ratio=ASPECT_RATIO,
        extra_params={"resolution": RESOLUTION},
    )
    cost = provider.estimate_cost(request)

    print("=" * 70)
    print("WAN TURBO COST-DOWN TIMELAPSE TEST - THIS WILL SPEND REAL MONEY")
    print("=" * 70)
    print(f"Source image (reused, $0 image cost): {source_image_path}")
    print(f"\nPrompt:\n  {BENCHMARK_PROMPT}")
    print(f"\nModel: {WAN_TURBO.submit_path}")
    print(f"Resolution: {RESOLUTION}   num_frames: {NUM_FRAMES} (~5.06s @ 16fps)   Aspect ratio: {ASPECT_RATIO}")
    print("Audio: none (this endpoint has no native audio capability - verified)")
    print(f"\nEstimated cost: ${cost:.4f}  (flat rate, 480p)")
    print(f"Hard cap:       ${MAX_SPEND_USD:.2f}")
    print("Rules: exactly 1 video call, 0 image calls, 0 retries, 0 alternate models.")
    print("=" * 70)

    if cost > MAX_SPEND_USD:
        fail(f"Estimated cost ${cost:.4f} exceeds the ${MAX_SPEND_USD:.2f} cap. Nothing was generated.")

    if not args.yes:
        answer = input(f"\nType 'yes' to spend up to ${cost:.4f} and proceed: ").strip().lower()
        if answer != "yes":
            print("Cancelled. Nothing was generated.")
            sys.exit(0)

    manifest = {
        "created_at": _now(),
        "experiment": "wan_turbo_cost_down_timelapse",
        "source_image_path": source_image_path,
        "reused_from_manifest": str(SOURCE_MANIFEST_PATH),
        "model": WAN_TURBO.submit_path,
        "prompt": BENCHMARK_PROMPT,
        "resolution": RESOLUTION,
        "num_frames": NUM_FRAMES,
        "aspect_ratio": ASPECT_RATIO,
        "max_spend_usd": MAX_SPEND_USD,
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

    print("\n[submit] Submitting the one generation...")
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

    video_path = OUTPUT_DIR / "wan_turbo_timelapse.mp4"
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
    print("DONE - 1 cost-down clip generated. No further generation will happen automatically.")
    print("=" * 70)
    print(f"wan_turbo_timelapse: {video_path}  (${actual_cost:.4f}, {total_seconds:.0f}s)")
    print(f"Manifest: {MANIFEST_PATH}")
    print("\nReview against the success criteria - judge it as a few seconds inside a rapid")
    print("60-70s TikTok/Short, NOT frame-by-frame against the Seedance benchmark:")
    for item in SUCCESS_CRITERIA:
        print(f"  - {item}")


if __name__ == "__main__":
    main()
