#!/usr/bin/env python3
"""QUALITY BAKE-OFF: the SAME reference image and the SAME construction
action, rendered through 3 different video models, so differences in the
output reflect model quality - not different creative direction.

Candidates:
    Wan 2.2 A14B Turbo, 480p   (current cheap baseline, already proven live)
    Kling 2.6 Pro, no audio    (new adapter, verified against fal.ai's docs)
    Veo 3.1 Fast, 1080p, no audio (new adapter, verified against fal.ai's docs)

Reference image: ONE FLUX pro v1.1 (not schnell, not ultra - see
app/providers/image/fal.py for why ultra was rejected) generation of the
recurring builder mid-construction on a beautiful natural site.

Test action: the builder cuts a timber board with a circular saw, then
carries and fastens it onto an incomplete wall structure - chosen
specifically to stress hand/tool realism, body motion, material behavior,
and structural continuity, per the quality bake-off's actual purpose (not
just "does it look pretty").

Safety, same pattern as every other real-call script in this repo:
  - Exactly 1 image call + exactly 3 video calls. No loop that could ever
    submit a 4th of anything, no regeneration path.
  - Total cost computed and checked against MAX_SPEND_USD BEFORE any call;
    one "type yes" confirmation gates the whole run.
  - No automatic retries - any failure at any stage stops the script
    immediately.
  - manifest.json records, per candidate: exact prompt, model/endpoint,
    resolution, duration, estimated cost, actual cost (if fal.ai returns
    one), and output filename - written incrementally so a partial failure
    still leaves a full diagnostic trail and a recoverable job.

Usage (from the repo root, with FAL_API_KEY set in your .env):
    python -m scripts.run_bakeoff_test
    python -m scripts.run_bakeoff_test --yes
"""
import argparse
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
from app.providers.image.fal import FLUX_PRO, FalImageProvider
from app.providers.video.fal import KLING_2_6_PRO, VEO_3_1_FAST, WAN_TURBO, FalVideoProvider

MAX_SPEND_USD = 1.25
ASPECT_RATIO = "9:16"
POLL_INTERVAL_SECONDS = 3
MAX_WAIT_SECONDS = 300  # per video; recover_fal_video_job.py can check on one later if hit

OUTPUT_DIR = Path(__file__).resolve().parent.parent / "data" / "fal_bakeoff_test"
MANIFEST_PATH = OUTPUT_DIR / "manifest.json"

BUILDER_DESCRIPTION = (
    "a rugged male builder, approximately mid-40s, slightly messy dark hair, short "
    "beard/stubble, medium athletic build, wearing worn jeans, a plain grey work shirt "
    "with no visible logo or branding, and brown work boots"
)

REFERENCE_IMAGE_PROMPT = (
    f"{BUILDER_DESCRIPTION}, standing on a partially built wooden cabin platform on a "
    "dramatic ocean cliff at golden hour. The cabin has a completed timber floor deck and "
    "partial wall framing on two sides (raw unfinished studs), the third side still open, "
    "no roof yet. He is standing beside sawhorses holding a long timber board, a circular "
    "saw resting nearby. Stacks of additional lumber and a tool bag are visible. Natural "
    "late-afternoon sunlight, dramatic ocean and sky in the background, documentary/"
    "phone-photo realism, not cinematic, vertical 9:16 composition."
)

# Sent to all 3 candidates, worded generically enough to need no per-model
# rewriting - this is the controlled variable of the whole experiment.
ACTION_PROMPT = (
    "The builder picks up the circular saw, switches it on, and cuts through the timber "
    "board resting on the sawhorses, sawdust visibly flying. He then lifts the cut board, "
    "carries it to the incomplete wall framing, and positions and fastens it into place, "
    "visibly extending the wall. Handheld documentary-style phone footage, natural "
    "lighting, no cinematic camera movement, realistic human motion and tool handling. "
    "The ocean cliff, the existing floor, and the existing wall framing remain visible and "
    "unchanged throughout - only the new board is added."
)

CANDIDATES = [
    {
        "label": "wan_turbo_480p",
        "video_config": WAN_TURBO,
        "duration_seconds": 4.0,  # Turbo's fixed output length; billing is flat, not duration-driven
        "extra_params": {"resolution": "480p"},
    },
    {
        "label": "kling_2.6_pro",
        "video_config": KLING_2_6_PRO,
        "duration_seconds": 5.0,  # must match KLING_2_6_PRO.extra_payload["duration"] = "5"
        "extra_params": {},
    },
    {
        "label": "veo_3.1_fast",
        "video_config": VEO_3_1_FAST,
        "duration_seconds": 6.0,  # must match VEO_3_1_FAST.extra_payload["duration"] = "6s"
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


def main() -> None:
    parser = argparse.ArgumentParser(description="Quality bake-off: Wan Turbo vs Kling 2.6 Pro vs Veo 3.1 Fast.")
    parser.add_argument("--yes", action="store_true", help="Skip the 'type yes' confirmation prompt")
    args = parser.parse_args()

    key_preview = f"{settings.fal_api_key[:6]}..." if settings.fal_api_key else None
    print(f"FAL_API_KEY loaded from .env: {'yes (' + key_preview + ')' if key_preview else 'NO'}")
    if not settings.fal_api_key:
        fail("FAL_API_KEY is not set. Add FAL_API_KEY=your_key_here to your .env file and try again.")

    image_provider = FalImageProvider(FLUX_PRO)
    image_request = ImageGenerationRequest(prompt=REFERENCE_IMAGE_PROMPT, width=576, height=1024)
    image_cost = image_provider.estimate_cost(image_request)

    video_providers = {}
    video_costs = {}
    for c in CANDIDATES:
        vp = FalVideoProvider(c["video_config"])
        req = VideoGenerationRequest(
            prompt=ACTION_PROMPT,
            aspect_ratio=ASPECT_RATIO,
            duration_seconds=c["duration_seconds"],
            extra_params=c["extra_params"],
        )
        video_providers[c["label"]] = vp
        video_costs[c["label"]] = vp.estimate_cost(req)

    total_cost = round(image_cost + sum(video_costs.values()), 4)

    print("=" * 70)
    print("QUALITY BAKE-OFF - THIS WILL SPEND REAL MONEY")
    print("=" * 70)
    print(f"Reference image model: {FLUX_PRO.model_id}  (1 call, shared across all candidates)")
    print(f"Reference image prompt:\n  {REFERENCE_IMAGE_PROMPT}")
    print(f"\nShared action prompt (sent to all 3 candidates):\n  {ACTION_PROMPT}")
    print("\nCandidates:")
    for c in CANDIDATES:
        cfg = c["video_config"]
        res = c["extra_params"].get("resolution", cfg.default_resolution if cfg.supports_resolution_param else "n/a")
        print(
            f"  - {c['label']:16s} {cfg.submit_path}  resolution={res}  "
            f"duration={c['duration_seconds']:.0f}s  estimated=${video_costs[c['label']]:.4f}"
        )
    print(f"\nEstimated cost: ${image_cost:.4f} (image) + " + " + ".join(f"${v:.4f}" for v in video_costs.values())
          + f" (video) = ${total_cost:.4f}")
    print(f"Hard cap:       ${MAX_SPEND_USD:.2f}")
    print("Rules: exactly 1 image + 3 videos, no retries, stop on any failure, manifest saved incrementally.")
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
        "reference_image_prompt": REFERENCE_IMAGE_PROMPT,
        "action_prompt": ACTION_PROMPT,
        "aspect_ratio": ASPECT_RATIO,
        "max_spend_usd": MAX_SPEND_USD,
        "estimated_total_cost_usd": total_cost,
        "reference_image": None,
        "candidates": [],
        "actual_total_cost_usd": None,
    }
    save_manifest(manifest)

    # --- The one shared reference image -------------------------------------
    print("\n[image] Generating shared reference image (FLUX pro v1.1)...")
    image_path = OUTPUT_DIR / "reference_image.jpg"
    t0 = time.monotonic()
    try:
        image_result = image_provider.generate_image(image_request, str(image_path))
    except ImageProviderError as e:
        fail(f"Reference image generation failed: {e}")
    image_seconds = time.monotonic() - t0
    print(f"        Done in {image_seconds:.1f}s -> {image_path} (${image_result.cost_usd:.4f})")

    manifest["reference_image"] = {
        "model": FLUX_PRO.model_id,
        "prompt": REFERENCE_IMAGE_PROMPT,
        "image_path": str(image_path),
        "cost_usd": image_result.cost_usd,
        "generated_at": _now(),
        "generation_seconds": round(image_seconds, 2),
    }
    save_manifest(manifest)

    # --- Each candidate, from the SAME reference image -----------------------
    for c in CANDIDATES:
        label = c["label"]
        video_config = c["video_config"]
        video_provider = video_providers[label]
        video_path = OUTPUT_DIR / f"{label}.mp4"

        request = VideoGenerationRequest(
            prompt=ACTION_PROMPT,
            reference_image_path=str(image_path),
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
            "prompt": ACTION_PROMPT,
            "reference_image_path": str(image_path),
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

    actual_total = round(
        manifest["reference_image"]["cost_usd"] + sum(c["actual_cost_usd"] for c in manifest["candidates"]), 4
    )
    manifest["actual_total_cost_usd"] = actual_total
    save_manifest(manifest)

    print("\n" + "=" * 70)
    print("DONE - all 3 candidates generated from the same reference image and action")
    print("=" * 70)
    print(f"Reference image: {image_path}")
    for c in manifest["candidates"]:
        print(f"{c['label']:16s}: {c['video_path']}  (${c['actual_cost_usd']:.4f})")
    print(f"Total actual cost: ${actual_total:.4f}")
    print(f"Full manifest (prompts, models, job ids, costs, timestamps): {MANIFEST_PATH}")
    print("\nNo further generation will happen automatically.")
    print("Review the 3 clips side by side against the shared bake-off criteria, then decide on next steps.")


if __name__ == "__main__":
    main()
