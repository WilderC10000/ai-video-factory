#!/usr/bin/env python3
"""PREMIUM 8-SECOND CONSTRUCTION-TIMELAPSE BENCHMARK: one-time quality
ceiling test, NOT a production-model decision.

The bake-off and the atomic/mechanical still-image gates all tested
whether a MODEL or a WORKFLOW could get physical interaction believable.
This test asks a different question entirely: using our best available
approved still image and a current premium model (Seedance 2.0 Fast),
what does the upper bound of "exciting, believable accelerated
construction progression" actually look like in 8 seconds? Once we know
that ceiling, cheaper models (Wan, etc.) get judged against it rather than
against a vague, un-grounded target - and premium generation stays
reserved for hook/reveal/hard-interaction shots, not every second of a
final video.

Source image: `data/fal_mechanical_start_test/mechanical_start_frame.jpg` -
the most refined approved frame available (correct composition AND
corrected saw mechanics layered on top of it), reused via its own
manifest.json exactly like every other "reuse an approved image" script in
this project. $0 image cost - this script makes NO image call at all.

Model: SEEDANCE_2_0_FAST (`bytedance/seedance-2.0/fast/image-to-video` -
app/providers/video/fal.py), chosen over Standard because Standard's only
capability difference is a 1080p ceiling (Fast tops out at 720p) at a
higher flat per-second rate - not something this motion/progression
benchmark needs. Audio is left on (`generate_audio: true`, the config's
default for this candidate) because fal.ai's documented pricing does not
change whether audio is requested or not.

Safety, same pattern as every other real-call script in this repo:
  - Exactly 1 video call. Zero image calls (the source image already
    exists and is reused as-is). No loop, no alternate model, no retry.
  - Total cost checked against MAX_SPEND_USD BEFORE the call; one
    "type yes" confirmation gates it.
  - No automatic retries - any failure stops the script immediately,
    printing a `recover_fal_video_job.py <job_id>` hint if the job had
    already been submitted.
  - manifest.json records the exact prompt, model, duration, resolution,
    cost, job id, and output path.

Usage (from the repo root, with FAL_API_KEY set in your .env, AFTER
scripts/run_mechanical_start_frame_test.py has already been run and its
frame approved):
    python -m scripts.run_seedance_benchmark_test
    python -m scripts.run_seedance_benchmark_test --yes
"""
import argparse
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

from app.config import settings
from app.providers.base import ProviderJobState, VideoGenerationRequest, VideoProviderError
from app.providers.video.fal import SEEDANCE_2_0_FAST, FalVideoProvider

MAX_SPEND_USD = 2.30
ASPECT_RATIO = "9:16"
DURATION_SECONDS = 8.0
RESOLUTION = "720p"
POLL_INTERVAL_SECONDS = 5
MAX_WAIT_SECONDS = 420  # premium 8s generations can take longer than the cheaper candidates

SOURCE_DIR = Path(__file__).resolve().parent.parent / "data" / "fal_mechanical_start_test"
SOURCE_MANIFEST_PATH = SOURCE_DIR / "manifest.json"

OUTPUT_DIR = Path(__file__).resolve().parent.parent / "data" / "fal_seedance_benchmark_test"
MANIFEST_PATH = OUTPUT_DIR / "manifest.json"

# A continuous narrative arc rather than literal "0-2s: X, 2-4s: Y" markup -
# video models generally follow a coherent scene description with implied
# pacing far more reliably than explicit timestamp instructions, which they
# tend to only loosely honor. The four-stage progression from the approved
# plan is folded into this arc, not dropped.
BENCHMARK_PROMPT = (
    "Vertical 9:16 accelerated construction timelapse, documentary/observational style. A "
    "rugged male builder in his 40s, wearing worn work clothes, works continuously and rapidly "
    "on a partially framed timber cabin on a dramatic ocean-cliff site at golden hour. He is "
    "completely absorbed in the work throughout and never looks toward the camera - his gaze "
    "and attention stay on the tools, materials, and structure at all times. The camera stays in "
    "a mostly stationary side/three-quarter-rear observational position, as though someone is "
    "quietly filming him work from a slight distance; only subtle natural camera movement, no "
    "orbiting, no dramatic sweeps, no centered hero framing.\n\n"
    "Over the course of the clip, construction visibly and rapidly advances in compressed, "
    "accelerated time: he cuts, carries, and positions timber; additional vertical studs and "
    "structural framing rapidly appear and get fastened into place as he works; the framing "
    "becomes progressively denser with more beams and cross-bracing added; by the end, the cabin "
    "structure is obviously and substantially more complete than at the start. Completed "
    "structural elements already in place remain present and are not lost or altered - "
    "construction only moves forward, never backward. The builder moves quickly but plausibly "
    "between tasks, like sped-up real footage rather than random or impossible motion.\n\n"
    "The lumber and tools stay consistent in size, shape and material - no warping, "
    "duplication, or morphing. The cabin's overall geometry and location remain recognizable "
    "throughout. The dramatic ocean and cliff landscape remains visible around the worksite. "
    "Natural ambient construction sounds throughout - saw and drill and hammer bursts, wood "
    "handling, footsteps, wind, and subtle ocean ambience in the background - no dialogue, no "
    "narration, no music. No posing, no presenter behavior, no commercial or advertisement "
    "aesthetic - this should read as genuine, exciting, rapid construction progress footage."
)

SUCCESS_CRITERIA = [
    "Immediately reads as construction/timelapse footage",
    "Builder remains focused on the work throughout",
    "No obvious camera acknowledgement (no eye contact, no posing)",
    "Cabin makes substantial visible progress",
    "Progress generally moves forward rather than randomly changing",
    "Major cabin geometry remains recognizable",
    "Builder remains reasonably consistent",
    "Tools/materials aren't constantly morphing",
    "Multiple satisfying progress moments",
    "At least ~4-6 seconds total are potentially usable after editing",
    "Can imagine a ~65-second video built from clips of this style",
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
    image" script in this project. Never generates a new image."""
    if not SOURCE_MANIFEST_PATH.exists():
        fail(
            f"Source manifest not found at {SOURCE_MANIFEST_PATH}. This benchmark reuses the "
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
        description="Seedance 2.0 Fast benchmark: 1 premium 8s video generation from the approved mechanical start frame."
    )
    parser.add_argument("--yes", action="store_true", help="Skip the 'type yes' confirmation prompt")
    args = parser.parse_args()

    key_preview = f"{settings.fal_api_key[:6]}..." if settings.fal_api_key else None
    print(f"FAL_API_KEY loaded from .env: {'yes (' + key_preview + ')' if key_preview else 'NO'}")
    if not settings.fal_api_key:
        fail("FAL_API_KEY is not set. Add FAL_API_KEY=your_key_here to your .env file and try again.")

    source_image_path = load_source_image()
    provider = FalVideoProvider(SEEDANCE_2_0_FAST)
    request = VideoGenerationRequest(
        prompt=BENCHMARK_PROMPT,
        reference_image_path=source_image_path,
        aspect_ratio=ASPECT_RATIO,
        duration_seconds=DURATION_SECONDS,
        extra_params={"resolution": RESOLUTION},
    )
    cost = provider.estimate_cost(request)

    print("=" * 70)
    print("SEEDANCE 2.0 FAST BENCHMARK - THIS WILL SPEND REAL MONEY")
    print("=" * 70)
    print(f"Source image (reused, $0 image cost): {source_image_path}")
    print(f"\nPrompt:\n  {BENCHMARK_PROMPT}")
    print(f"\nModel: {SEEDANCE_2_0_FAST.submit_path}")
    print(f"Resolution: {RESOLUTION}   Duration: {DURATION_SECONDS:.0f}s   Aspect ratio: {ASPECT_RATIO}")
    print(f"Audio: generate_audio=True (no price difference per fal.ai's documented pricing)")
    print(f"\nEstimated cost: ${cost:.4f}  ($0.2419/s x {DURATION_SECONDS:.0f}s)")
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
        "experiment": "seedance_2_0_fast_benchmark",
        "source_image_path": source_image_path,
        "reused_from_manifest": str(SOURCE_MANIFEST_PATH),
        "model": SEEDANCE_2_0_FAST.submit_path,
        "prompt": BENCHMARK_PROMPT,
        "resolution": RESOLUTION,
        "duration_seconds": DURATION_SECONDS,
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

    print("\n[submit] Submitting the one benchmark generation...")
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

    video_path = OUTPUT_DIR / "seedance_benchmark.mp4"
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
    print("DONE - 1 premium benchmark clip generated. No further generation will happen automatically.")
    print("=" * 70)
    print(f"seedance_benchmark: {video_path}  (${actual_cost:.4f}, {total_seconds:.0f}s)")
    print(f"Manifest: {MANIFEST_PATH}")
    print("\nReview against the success criteria (most should hold for a PASS):")
    for item in SUCCESS_CRITERIA:
        print(f"  - {item}")
    print("\nRemember: this is a one-time quality-ceiling benchmark, not a production-model")
    print("decision. Next is comparing cheaper models/workflows against what this establishes.")


if __name__ == "__main__":
    main()
