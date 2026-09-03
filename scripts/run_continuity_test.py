#!/usr/bin/env python3
"""3-SHOT REAL fal.ai CONTINUITY EXPERIMENT.

This is deliberately a research probe, not the final ~60-75s / 13-16 shot
architecture - the question it answers is: how much visual drift
accumulates across sequential Wan Turbo generations when each stage is
seeded from the actual last frame of the previous one, instead of an
independently-imagined starting frame?

Strategy - "last-frame propagation":
    Shot 1: ONE FLUX schnell text-to-image call produces the only
            from-scratch reference image (empty cave, materials staged).
            Wan Turbo animates it.
    Shot 2: the LAST FRAME of shot 1's video (extracted locally with
            ffmpeg - free, no API call) becomes shot 2's reference image
            directly. Wan Turbo animates from those exact pixels.
    Shot 3: same idea, seeded from shot 2's last frame.

No new FLUX calls after shot 1 - the whole point is that shots 2 and 3
inherit the real pixels of what came before, not a fresh reinterpretation
of a text description.

Safety, matching the pattern established in run_first_fal_test.py:
  - Exactly 1 FalImageProvider.generate_image() call and exactly 3
    FalVideoProvider.submit_video_job() calls. No loop that could ever
    submit a 4th, no regeneration path.
  - No automatic retries anywhere - any failure at any stage stops the
    whole script immediately via fail().
  - Total cost is computed and checked against MAX_SPEND_USD BEFORE any
    network call; a single "type yes" confirmation gates the entire chain.
  - Every stage's state (prompts, reference image source, job id,
    status/result URLs, costs, timestamps) is written to manifest.json
    incrementally, so a failure partway through still leaves a full
    diagnostic trail and a recoverable job (see recover_fal_video_job.py).

Usage (from the repo root, with FAL_API_KEY set in your .env, and ffmpeg
on PATH):
    python -m scripts.run_continuity_test
    python -m scripts.run_continuity_test --frame-offset 0.5
    python -m scripts.run_continuity_test --yes
"""
import argparse
import json
import shutil
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
from app.providers.image.fal import FLUX_SCHNELL, FalImageProvider
from app.providers.video.fal import WAN_TURBO, FalVideoProvider
from app.services.frame_extraction import FrameExtractionError, extract_last_frame

MAX_SPEND_USD = 0.20
RESOLUTION = "480p"
ASPECT_RATIO = "9:16"
DEFAULT_FRAME_OFFSET_SECONDS = 0.3
POLL_INTERVAL_SECONDS = 3
MAX_WAIT_SECONDS = 300  # per video stage; if hit, recover_fal_video_job.py can check on it later

OUTPUT_DIR = Path(__file__).resolve().parent.parent / "data" / "fal_continuity_test"
MANIFEST_PATH = OUTPUT_DIR / "manifest.json"

# --- Continuity bible: repeated verbatim in every prompt so the model is
# re-anchored on the fixed elements every single time, on top of whatever
# visual continuity the propagated reference image itself provides. ------
CONTINUITY_BIBLE = (
    "A single lone male construction worker: weathered grey t-shirt, faded orange hard hat, "
    "brown leather tool belt, sturdy brown work boots, medium build, consistent appearance "
    "throughout. Location: the interior of a dramatic, rugged natural sea cave on a rocky "
    "coastline, rough damp grey stone walls and ceiling, a wide natural opening showing the "
    "ocean and sky with natural daylight streaming in. Material palette so far: raw timber "
    "framing, light-toned concrete, natural stone - no painted drywall, no finished surfaces, "
    "no glass, no furniture, no decor anywhere yet. Camera and style: handheld phone-quality "
    "documentary footage in the style of a viral construction/transformation video, natural "
    "available light only, no cinematic camera movement, slightly imperfect handheld framing, "
    "realistic and unpolished, not cinematic."
)

SHOT1_IMAGE_PROMPT = (
    CONTINUITY_BIBLE + " The cave interior is completely raw and empty. Construction materials "
    "and tools have just been delivered and are neatly staged on the bare cave floor: stacked "
    "lumber, bags of concrete mix, coiled rope, a wheelbarrow, hand tools. Absolutely no floor, "
    "no platform, no walls, no framing of any kind exists yet - nothing has been built. This is "
    "the very beginning, site preparation only. Photo-realistic establishing shot, vertical 9:16."
)

SHOT1_VIDEO_PROMPT = (
    CONTINUITY_BIBLE + " The worker performs site preparation: clearing loose rock and debris "
    "from the cave floor, organizing the staged materials and tools, measuring and marking out "
    "a floor plan with stakes and string. No floor, platform, or structure of any kind is built "
    "during this clip - preparation only, nothing constructed yet."
)

SHOT2_VIDEO_PROMPT = (
    CONTINUITY_BIBLE + " Continuing directly on from the same staged materials: the worker is "
    "now visibly building a raised wooden floor and platform frame, positioning joists and "
    "securing platform boards above the cave floor using the staged lumber. The platform is "
    "partially built and taking clear shape. There are still absolutely no walls, no window "
    "framing, no roof, no furniture, and no finished interior of any kind - only the raised "
    "floor/platform structure itself is present."
)

SHOT3_VIDEO_PROMPT = (
    CONTINUITY_BIBLE + " The raised floor/platform built in the previous stage remains exactly "
    "as it was, fully intact, unchanged. The worker is now erecting the first large vertical "
    "wall and window framing structure, raw unfinished timber studs rising up from the edge of "
    "that same floor. The framing is structural only: there is no drywall, no insulation, no "
    "glass in the window openings, no cabinetry, no furniture, and no final decor of any kind - "
    "just the bare vertical wall/window frame going up."
)


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
    parser = argparse.ArgumentParser(description="3-shot real fal.ai continuity experiment.")
    parser.add_argument(
        "--frame-offset",
        type=float,
        default=DEFAULT_FRAME_OFFSET_SECONDS,
        help=f"Seconds before each clip's end to extract the propagated frame from (default {DEFAULT_FRAME_OFFSET_SECONDS})",
    )
    parser.add_argument("--yes", action="store_true", help="Skip the 'type yes' confirmation prompt")
    args = parser.parse_args()

    if not shutil.which("ffmpeg"):
        fail(
            "ffmpeg was not found on PATH - it's required to extract propagated reference frames "
            "between stages. Install it (e.g. https://ffmpeg.org/download.html or "
            "`winget install ffmpeg` on Windows) and try again."
        )

    key_preview = f"{settings.fal_api_key[:6]}..." if settings.fal_api_key else None
    print(f"FAL_API_KEY loaded from .env: {'yes (' + key_preview + ')' if key_preview else 'NO'}")
    if not settings.fal_api_key:
        fail("FAL_API_KEY is not set. Add FAL_API_KEY=your_key_here to your .env file and try again.")

    image_provider = FalImageProvider(FLUX_SCHNELL)
    video_provider = FalVideoProvider(WAN_TURBO)

    image_request = ImageGenerationRequest(prompt=SHOT1_IMAGE_PROMPT, width=576, height=1024)
    image_cost = image_provider.estimate_cost(image_request)
    video_cost_preview = video_provider.estimate_cost(
        VideoGenerationRequest(prompt="p", aspect_ratio=ASPECT_RATIO, extra_params={"resolution": RESOLUTION})
    )
    total_cost = round(image_cost + 3 * video_cost_preview, 4)

    print("=" * 70)
    print("3-SHOT REAL fal.ai CONTINUITY EXPERIMENT - THIS WILL SPEND REAL MONEY")
    print("=" * 70)
    print(f"Image model:     {FLUX_SCHNELL.model_id}  (shot 1 only)")
    print(f"Video model:     {WAN_TURBO.submit_path}  (all 3 shots)")
    print(f"Resolution:      {RESOLUTION}    Aspect ratio: {ASPECT_RATIO}")
    print(f"Frame offset:    {args.frame_offset}s before each clip's end (propagated to the next shot)")
    print(f"Continuity bible:\n  {CONTINUITY_BIBLE}")
    print(f"\nShot 1 image prompt:\n  {SHOT1_IMAGE_PROMPT}")
    print(f"\nShot 1 video prompt:\n  {SHOT1_VIDEO_PROMPT}")
    print(f"\nShot 2 video prompt:\n  {SHOT2_VIDEO_PROMPT}")
    print(f"\nShot 3 video prompt:\n  {SHOT3_VIDEO_PROMPT}")
    print(
        f"\nEstimated cost: ${image_cost:.4f} (1 image) + 3 x ${video_cost_preview:.4f} (video) "
        f"= ${total_cost:.4f}"
    )
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
        "continuity_bible": CONTINUITY_BIBLE,
        "frame_extraction_offset_seconds": args.frame_offset,
        "resolution": RESOLUTION,
        "aspect_ratio": ASPECT_RATIO,
        "max_spend_usd": MAX_SPEND_USD,
        "estimated_total_cost_usd": total_cost,
        "reference_image": None,
        "shots": [],
        "actual_total_cost_usd": None,
    }
    save_manifest(manifest)

    # --- Shot 1's reference image: the only FLUX call in this whole script --
    print("\n[image] Generating shot 1's reference image (FLUX schnell)...")
    image_path = OUTPUT_DIR / "shot1_reference.jpg"
    t0 = time.monotonic()
    try:
        image_result = image_provider.generate_image(image_request, str(image_path))
    except ImageProviderError as e:
        fail(f"Reference image generation failed: {e}")
    image_seconds = time.monotonic() - t0
    print(f"        Done in {image_seconds:.1f}s -> {image_path} (${image_result.cost_usd:.4f})")

    manifest["reference_image"] = {
        "prompt": SHOT1_IMAGE_PROMPT,
        "image_path": str(image_path),
        "cost_usd": image_result.cost_usd,
        "generated_at": _now(),
        "generation_seconds": round(image_seconds, 2),
    }
    save_manifest(manifest)

    def run_video_stage(shot_number: int, prompt: str, reference_image_path: Path, source_desc: dict) -> Path:
        """Submits, polls (no retries), and downloads exactly one video.
        Returns the local path of the downloaded clip. Every state change
        is saved to the manifest immediately, before moving on."""
        video_path = OUTPUT_DIR / f"shot{shot_number}_video.mp4"
        request = VideoGenerationRequest(
            prompt=prompt,
            reference_image_path=str(reference_image_path),
            aspect_ratio=ASPECT_RATIO,
            extra_params={"resolution": RESOLUTION, "enable_prompt_expansion": False},
        )

        print(f"\n[shot {shot_number}] Submitting video job (reference: {reference_image_path.name})...")
        t_submit = time.monotonic()
        try:
            submitted = video_provider.submit_video_job(request)
        except VideoProviderError as e:
            fail(f"Shot {shot_number} submission failed: {e}")
        print(f"          Submitted. Provider job id: {submitted.provider_job_id} "
              f"(estimated ${submitted.estimated_cost_usd:.4f})")

        stage_entry = {
            "shot_number": shot_number,
            "video_prompt": prompt,
            **source_desc,
            "provider_job_id": submitted.provider_job_id,
            "status_url": submitted.meta.get("status_url"),
            "response_url": submitted.meta.get("response_url"),
            "estimated_cost_usd": submitted.estimated_cost_usd,
            "actual_cost_usd": None,
            "video_path": None,
            "submitted_at": _now(),
            "completed_at": None,
        }
        manifest["shots"].append(stage_entry)
        save_manifest(manifest)

        print(f"          Polling (no retries on error - any failure stops the whole script)...")
        result = None
        while True:
            elapsed = time.monotonic() - t_submit
            if elapsed > MAX_WAIT_SECONDS:
                fail(
                    f"Shot {shot_number}: gave up after {elapsed:.0f}s waiting (job may still complete and "
                    f"be billed on fal.ai's side - check https://fal.ai/dashboard/billing). To check on it "
                    f"later without spending anything again, run:\n"
                    f"      python -m scripts.recover_fal_video_job {submitted.provider_job_id}"
                )
            try:
                result = video_provider.get_job_status(submitted.provider_job_id, meta=submitted.meta)
            except VideoProviderError as e:
                fail(
                    f"Shot {shot_number} status check failed: {e}\n"
                    f"      To check on it later without spending anything again, run:\n"
                    f"      python -m scripts.recover_fal_video_job {submitted.provider_job_id}"
                )
            if result.status == ProviderJobState.PROCESSING:
                print(f"          ...still processing ({elapsed:.0f}s elapsed)")
                time.sleep(POLL_INTERVAL_SECONDS)
                continue
            break

        if result.status == ProviderJobState.FAILED:
            fail(f"Shot {shot_number}: provider reported generation failure: {result.error_message}")

        try:
            video_provider.download_result(submitted.provider_job_id, result.output_url, str(video_path))
        except VideoProviderError as e:
            fail(
                f"Shot {shot_number} download failed (already billed, only the local save failed): {e}\n"
                f"      To retry just the download, run:\n"
                f"      python -m scripts.recover_fal_video_job {submitted.provider_job_id}"
            )

        video_seconds = time.monotonic() - t_submit
        actual_cost = result.actual_cost_usd if result.actual_cost_usd is not None else submitted.estimated_cost_usd
        stage_entry["actual_cost_usd"] = actual_cost
        stage_entry["video_path"] = str(video_path)
        stage_entry["completed_at"] = _now()
        stage_entry["generation_seconds"] = round(video_seconds, 2)
        save_manifest(manifest)

        print(f"          Completed in {video_seconds:.1f}s -> {video_path} (${actual_cost:.4f})")
        return video_path

    def propagate_frame(shot_number: int, source_video: Path) -> Path:
        frame_path = OUTPUT_DIR / f"shot{shot_number}_reference.jpg"
        print(f"\n[frame] Extracting propagated reference frame for shot {shot_number} "
              f"from {source_video.name} ({args.frame_offset}s before the end)...")
        try:
            extract_last_frame(source_video, frame_path, offset_seconds=args.frame_offset)
        except FrameExtractionError as e:
            fail(f"Frame extraction for shot {shot_number} failed: {e}")
        print(f"        Saved -> {frame_path}")
        return frame_path

    # --- Shot 1: video from the FLUX reference image -------------------------
    video1_path = run_video_stage(
        1, SHOT1_VIDEO_PROMPT, image_path,
        {
            "reference_image_path": str(image_path),
            "reference_image_source": "flux_text_to_image",
            "extraction_source_video": None,
            "extraction_offset_seconds": None,
        },
    )

    # --- Shot 2: seeded from shot 1's last frame ------------------------------
    frame2_path = propagate_frame(2, video1_path)
    video2_path = run_video_stage(
        2, SHOT2_VIDEO_PROMPT, frame2_path,
        {
            "reference_image_path": str(frame2_path),
            "reference_image_source": "extracted_frame",
            "extraction_source_video": str(video1_path),
            "extraction_offset_seconds": args.frame_offset,
        },
    )

    # --- Shot 3: seeded from shot 2's last frame ------------------------------
    frame3_path = propagate_frame(3, video2_path)
    run_video_stage(
        3, SHOT3_VIDEO_PROMPT, frame3_path,
        {
            "reference_image_path": str(frame3_path),
            "reference_image_source": "extracted_frame",
            "extraction_source_video": str(video2_path),
            "extraction_offset_seconds": args.frame_offset,
        },
    )

    actual_total = round(
        manifest["reference_image"]["cost_usd"] + sum(s["actual_cost_usd"] for s in manifest["shots"]), 4
    )
    manifest["actual_total_cost_usd"] = actual_total
    save_manifest(manifest)

    print("\n" + "=" * 70)
    print("DONE - all 3 shots generated")
    print("=" * 70)
    print(f"Reference image: {image_path}")
    for shot in manifest["shots"]:
        print(f"Shot {shot['shot_number']}: {shot['video_path']}  (${shot['actual_cost_usd']:.4f}, "
              f"reference: {shot['reference_image_path']})")
    print(f"Total actual cost: ${actual_total:.4f}")
    print(f"Full manifest (prompts, job ids, timestamps, costs): {MANIFEST_PATH}")
    print("\nNo further generation will happen automatically.")
    print("Review the 3 clips yourself for continuity and drift, then decide on next steps.")


if __name__ == "__main__":
    main()
