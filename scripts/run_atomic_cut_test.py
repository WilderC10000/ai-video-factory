#!/usr/bin/env python3
"""ATOMIC-ACTION EXPERIMENT V1: does restricting a generated clip to ONE
dominant physical action (continuous circular-saw cutting - nothing else)
materially reduce the rigid-object/tool morphing seen in the original
quality bake-off's compound-action prompt (saw -> cut -> lift board ->
carry board -> position board -> fasten board)?

Deliberately a single-variable experiment against the original bake-off
(scripts/run_bakeoff_test.py) - everything is held constant EXCEPT the
video prompt:
  - Same reused reference image (data/fal_bakeoff_test/reference_image.jpg,
    read from that run's own manifest.json) - NOT regenerated. $0 image
    cost this time; the only paid calls are the 3 video generations.
  - Same 3 models/configs, same resolutions/durations/settings as the
    original bake-off (WAN_TURBO 480p/4s, KLING_2_6_PRO 5s, VEO_3_1_FAST
    1080p/6s).
  - The identical prompt text sent to all 3 candidates - no per-model
    rewriting - so model choice, not prompt wording, is the only variable
    between the two comparisons this experiment enables per model:
    original compound clip vs. this atomic clip.

Produces exactly 3 files - wan_atomic_cut.mp4, kling_atomic_cut.mp4,
veo_atomic_cut.mp4 - meant to be reviewed one-to-one against the 3
corresponding compound-action clips already sitting in
data/fal_bakeoff_test/.

Safety, identical pattern to every other real-call script in this repo:
  - Exactly 3 video calls, zero image calls. No loop that could ever
    submit a 4th of anything, no regeneration path.
  - Total cost computed and checked against MAX_SPEND_USD BEFORE any
    call; one "type yes" confirmation gates the whole run.
  - No automatic retries - any failure at any stage stops the script
    immediately.
  - manifest.json records, per candidate: exact prompt, model/endpoint,
    resolution, duration, estimated cost, actual cost, and output
    filename - written incrementally so a partial failure still leaves a
    full diagnostic trail and a recoverable job.

Usage (from the repo root, with FAL_API_KEY set in your .env, AFTER
scripts/run_bakeoff_test.py has already been run at least once so its
reference image and manifest exist):
    python -m scripts.run_atomic_cut_test
    python -m scripts.run_atomic_cut_test --yes
"""
import argparse
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

from app.config import settings
from app.providers.base import (
    ProviderJobState,
    VideoGenerationRequest,
    VideoProviderError,
)
from app.providers.video.fal import KLING_2_6_PRO, VEO_3_1_FAST, WAN_TURBO, FalVideoProvider

MAX_SPEND_USD = 1.15
ASPECT_RATIO = "9:16"
POLL_INTERVAL_SECONDS = 3
MAX_WAIT_SECONDS = 300  # per video; recover_fal_video_job.py can check on one later if hit

BAKEOFF_DIR = Path(__file__).resolve().parent.parent / "data" / "fal_bakeoff_test"
BAKEOFF_MANIFEST_PATH = BAKEOFF_DIR / "manifest.json"

OUTPUT_DIR = Path(__file__).resolve().parent.parent / "data" / "fal_atomic_cut_test"
MANIFEST_PATH = OUTPUT_DIR / "manifest.json"

# The ONLY thing that differs from the original bake-off's ACTION_PROMPT -
# restricted to a single dominant verb (cut) with everything else in the
# frame explicitly pinned unchanged. Sent verbatim, unmodified, to all 3
# candidates - no per-model rewriting - so model choice stays the only
# real variable in play.
ATOMIC_CUT_PROMPT = (
    "The builder continuously uses the circular saw to cut through the single timber board "
    "resting on the sawhorses. Both hands remain naturally positioned on the tool and board "
    "throughout. The saw stays physically consistent throughout the action, and the board "
    "remains the same size, shape, color, and position except for the physical cut being "
    "made. Fine sawdust is produced naturally as the blade moves through the timber. He does "
    "not pick up the board, carry it, install it, change tools, walk away, or perform any "
    "second task. The existing cabin framing, floor platform, builder appearance, ocean "
    "cliff, and lighting all remain unchanged throughout. Handheld documentary-style phone "
    "footage, natural motion, no cinematic camera movement."
)

# Same models, same resolutions/durations/settings as the original bake-off -
# only the prompt and the reused (not regenerated) reference image differ.
CANDIDATES = [
    {
        "label": "wan_atomic_cut",
        "video_config": WAN_TURBO,
        "duration_seconds": 4.0,
        "extra_params": {"resolution": "480p"},
    },
    {
        "label": "kling_atomic_cut",
        "video_config": KLING_2_6_PRO,
        "duration_seconds": 5.0,
        "extra_params": {},
    },
    {
        "label": "veo_atomic_cut",
        "video_config": VEO_3_1_FAST,
        "duration_seconds": 6.0,
        "extra_params": {"resolution": "1080p"},
    },
]


def fail(message: str) -> None:
    print(f"\nSTOPPED: {message}")
    print(f"No retry, no further generation - the script is exiting now. Manifest: {MANIFEST_PATH}")
    sys.exit(1)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def save_manifest(manifest: dict) -> None:
    MANIFEST_PATH.parent.mkdir(parents=True, exist_ok=True)
    MANIFEST_PATH.write_text(json.dumps(manifest, indent=2))


def load_reused_reference_image() -> tuple[str, dict]:
    """Reads the reference image path out of the ORIGINAL bake-off's own
    manifest.json rather than hard-coding a path, so this experiment can
    only ever reuse an image that a real bake-off run actually produced -
    never a new generation."""
    if not BAKEOFF_MANIFEST_PATH.exists():
        fail(
            f"Bake-off manifest not found at {BAKEOFF_MANIFEST_PATH}. This experiment reuses "
            "its reference image and must not generate a new one - run "
            "scripts/run_bakeoff_test.py first."
        )
    bakeoff_manifest = json.loads(BAKEOFF_MANIFEST_PATH.read_text())
    ref = bakeoff_manifest.get("reference_image")
    if not ref or not ref.get("image_path"):
        fail(
            f"Bake-off manifest at {BAKEOFF_MANIFEST_PATH} has no reference_image recorded. "
            "Run scripts/run_bakeoff_test.py first."
        )
    image_path = Path(ref["image_path"])
    if not image_path.exists() or image_path.stat().st_size == 0:
        fail(f"Reused reference image not found (or empty) at {image_path}.")
    return str(image_path), ref


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Atomic-action experiment V1: same 3 models, same reused reference image, atomic 'cut' prompt only."
    )
    parser.add_argument("--yes", action="store_true", help="Skip the 'type yes' confirmation prompt")
    args = parser.parse_args()

    key_preview = f"{settings.fal_api_key[:6]}..." if settings.fal_api_key else None
    print(f"FAL_API_KEY loaded from .env: {'yes (' + key_preview + ')' if key_preview else 'NO'}")
    if not settings.fal_api_key:
        fail("FAL_API_KEY is not set. Add FAL_API_KEY=your_key_here to your .env file and try again.")

    image_path, bakeoff_ref = load_reused_reference_image()
    print(
        f"[reuse] Using existing reference image from the original bake-off (NOT regenerated, $0.00): "
        f"{image_path}\n        (originally generated {bakeoff_ref.get('generated_at')}, "
        f"cost ${bakeoff_ref.get('cost_usd', 0.0):.4f} - already paid, not billed again here)"
    )

    video_providers = {}
    video_costs = {}
    for c in CANDIDATES:
        vp = FalVideoProvider(c["video_config"])
        req = VideoGenerationRequest(
            prompt=ATOMIC_CUT_PROMPT,
            aspect_ratio=ASPECT_RATIO,
            duration_seconds=c["duration_seconds"],
            extra_params=c["extra_params"],
        )
        video_providers[c["label"]] = vp
        video_costs[c["label"]] = vp.estimate_cost(req)

    total_cost = round(sum(video_costs.values()), 4)

    print("=" * 70)
    print("ATOMIC-ACTION EXPERIMENT V1 - THIS WILL SPEND REAL MONEY")
    print("=" * 70)
    print(f"Reused reference image (no new image call): {image_path}")
    print(f"\nAtomic-cut prompt (sent verbatim to all 3 candidates):\n  {ATOMIC_CUT_PROMPT}")
    print("\nCandidates:")
    for c in CANDIDATES:
        cfg = c["video_config"]
        res = c["extra_params"].get("resolution", cfg.default_resolution if cfg.supports_resolution_param else "n/a")
        print(
            f"  - {c['label']:16s} {cfg.submit_path}  resolution={res}  "
            f"duration={c['duration_seconds']:.0f}s  estimated=${video_costs[c['label']]:.4f}"
        )
    print(f"\nEstimated cost: $0.0000 (image, reused) + " + " + ".join(f"${v:.4f}" for v in video_costs.values())
          + f" (video) = ${total_cost:.4f}")
    print(f"Hard cap:       ${MAX_SPEND_USD:.2f}")
    print("Rules: exactly 3 videos, no image call, no retries, stop on any failure, manifest saved incrementally.")
    print("=" * 70)

    if total_cost > MAX_SPEND_USD:
        fail(f"Estimated cost ${total_cost:.4f} exceeds the ${MAX_SPEND_USD:.2f} cap. Nothing was generated.")

    if not args.yes:
        answer = input(f"\nType 'yes' to spend up to ${total_cost:.4f} and proceed: ").strip().lower()
        if answer != "yes":
            print("Cancelled. Nothing was generated.")
            sys.exit(0)

    manifest = {
        "created_at": _now(),
        "experiment": "atomic_cut_v1",
        "reused_reference_image_path": image_path,
        "reused_from_bakeoff_manifest": str(BAKEOFF_MANIFEST_PATH),
        "action_prompt": ATOMIC_CUT_PROMPT,
        "aspect_ratio": ASPECT_RATIO,
        "max_spend_usd": MAX_SPEND_USD,
        "estimated_total_cost_usd": total_cost,
        "candidates": [],
        "actual_total_cost_usd": None,
    }
    save_manifest(manifest)

    for c in CANDIDATES:
        label = c["label"]
        video_config = c["video_config"]
        video_provider = video_providers[label]
        video_path = OUTPUT_DIR / f"{label}.mp4"

        request = VideoGenerationRequest(
            prompt=ATOMIC_CUT_PROMPT,
            reference_image_path=image_path,
            aspect_ratio=ASPECT_RATIO,
            duration_seconds=c["duration_seconds"],
            extra_params=c["extra_params"],
        )

        print(f"\n[{label}] Submitting ({video_config.submit_path})...")
        t_submit = time.monotonic()
        try:
            submitted = video_provider.submit_video_job(request)
        except VideoProviderError as e:
            fail(f"{label}: submission failed: {e}")
        print(f"          Submitted. Provider job id: {submitted.provider_job_id} "
              f"(estimated ${submitted.estimated_cost_usd:.4f})")

        resolution = c["extra_params"].get(
            "resolution", video_config.default_resolution if video_config.supports_resolution_param else None
        )
        candidate_entry = {
            "label": label,
            "model": video_config.submit_path,
            "prompt": ATOMIC_CUT_PROMPT,
            "reference_image_path": image_path,
            "resolution": resolution,
            "duration_seconds": c["duration_seconds"],
            "provider_job_id": submitted.provider_job_id,
            "status_url": submitted.meta.get("status_url"),
            "response_url": submitted.meta.get("response_url"),
            "estimated_cost_usd": submitted.estimated_cost_usd,
            "actual_cost_usd": None,
            "video_path": None,
            "submitted_at": _now(),
            "completed_at": None,
        }
        manifest["candidates"].append(candidate_entry)
        save_manifest(manifest)

        print(f"          Polling (no retries on error - any failure stops the whole script)...")
        result = None
        while True:
            elapsed = time.monotonic() - t_submit
            if elapsed > MAX_WAIT_SECONDS:
                fail(
                    f"{label}: gave up after {elapsed:.0f}s waiting (job may still complete and be billed on "
                    f"fal.ai's side - check https://fal.ai/dashboard/billing). To check on it later without "
                    f"spending anything again, run:\n"
                    f"      python -m scripts.recover_fal_video_job {submitted.provider_job_id}"
                )
            try:
                result = video_provider.get_job_status(submitted.provider_job_id, meta=submitted.meta)
            except VideoProviderError as e:
                fail(
                    f"{label}: status check failed: {e}\n"
                    f"      To check on it later without spending anything again, run:\n"
                    f"      python -m scripts.recover_fal_video_job {submitted.provider_job_id}"
                )
            if result.status == ProviderJobState.PROCESSING:
                print(f"          ...still processing ({elapsed:.0f}s elapsed)")
                time.sleep(POLL_INTERVAL_SECONDS)
                continue
            break

        if result.status == ProviderJobState.FAILED:
            fail(f"{label}: provider reported generation failure: {result.error_message}")

        try:
            video_provider.download_result(submitted.provider_job_id, result.output_url, str(video_path))
        except VideoProviderError as e:
            fail(
                f"{label}: download failed (already billed, only the local save failed): {e}\n"
                f"      To retry just the download, run:\n"
                f"      python -m scripts.recover_fal_video_job {submitted.provider_job_id}"
            )

        video_seconds = time.monotonic() - t_submit
        actual_cost = result.actual_cost_usd if result.actual_cost_usd is not None else submitted.estimated_cost_usd
        candidate_entry["actual_cost_usd"] = actual_cost
        candidate_entry["video_path"] = str(video_path)
        candidate_entry["completed_at"] = _now()
        candidate_entry["generation_seconds"] = round(video_seconds, 2)
        save_manifest(manifest)

        print(f"          Completed in {video_seconds:.1f}s -> {video_path} (${actual_cost:.4f})")

    actual_total = round(sum(c["actual_cost_usd"] for c in manifest["candidates"]), 4)
    manifest["actual_total_cost_usd"] = actual_total
    save_manifest(manifest)

    print("\n" + "=" * 70)
    print("DONE - all 3 atomic-cut candidates generated from the reused reference image")
    print("=" * 70)
    print(f"Reused reference image: {image_path}")
    for c in manifest["candidates"]:
        print(f"{c['label']:16s}: {c['video_path']}  (${c['actual_cost_usd']:.4f})")
    print(f"Total actual cost: ${actual_total:.4f}")
    print(f"Full manifest (prompts, models, job ids, costs, timestamps): {MANIFEST_PATH}")
    print("\nNo further generation will happen automatically.")
    print("Compare each clip against its compound-action counterpart in data/fal_bakeoff_test/:")
    print("  wan_atomic_cut.mp4   vs  wan_turbo_480p.mp4")
    print("  kling_atomic_cut.mp4 vs  kling_2.6_pro.mp4")
    print("  veo_atomic_cut.mp4   vs  veo_3.1_fast.mp4")


if __name__ == "__main__":
    main()
