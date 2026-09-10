"""FORMA VIDEO #2 - SHARED CONSTANTS AND HELPERS.

Turquoise Alpine Lake -> Modern Glass A-Frame Hideaway. Imported by every
stage script in this pipeline so the location bible, cabin spec, paths,
manifest helpers, and the hard cross-script budget guard are defined
exactly once.

BUDGET_CAP_USD is the absolute hard ceiling for this video ($6.50,
per explicit authorization) - enforce_budget() sums every real spend
already recorded in the shared manifest and refuses any call that would
push total spend past the cap, regardless of that call's own per-stage
MAX_SPEND_USD. This is real cross-script protection, not just each
script's own local cap.
"""
import dataclasses
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
OUTPUT_DIR = REPO_ROOT / "data" / "alpine_video_2"
MANIFEST_PATH = OUTPUT_DIR / "manifest.json"

ASPECT_RATIO = "9:16"
RESOLUTION = "480p"
BUDGET_CAP_USD = 6.50
MAX_SPEND_USD_EDIT = 0.15  # flat rate, zero margin, every NANO_BANANA_PRO_EDIT call

# Locked visual anchors for the site - established by the reference image
# and repeated in every prompt so the environment stays "co-star, not
# background" throughout the build (FORMA's landscape-equity rule).
LOCATION_BIBLE = (
    "a dramatic rocky peninsula on the shore of an intensely turquoise glacial lake, "
    "huge snowcapped mountains filling the horizon behind it, dark evergreen forest along "
    "portions of the shoreline, dramatic clouds moving around the distant peaks, and warm "
    "late-afternoon natural light with visible reflections and gentle water movement on the lake"
)

# Locked visual anchors for the structure - a scale reference, not an
# engineering spec; real generated pixels always outrank these numbers.
CABIN_SPEC = (
    "a compact modern glass A-frame hideaway, approximately 10 to 12 feet wide and 14 to 16 "
    "feet long, with a steep symmetrical A-frame roof reaching approximately 12 to 14 feet at "
    "its peak, single-story with a compact loftless feel, natural timber structural ribs, dark "
    "charcoal exterior cladding, and a large lake-facing glass facade - small enough that one "
    "builder plausibly constructs it alone, never a mansion, no second story, no extra wings, "
    "no oversized balcony"
)


def fail(message: str) -> None:
    print(f"\nSTOPPED: {message}")
    print("No retry, no further generation - the script is exiting now.")
    sys.exit(1)


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def load_manifest() -> dict:
    if MANIFEST_PATH.exists():
        return json.loads(MANIFEST_PATH.read_text())
    return {"experiment": "alpine_video_2", "created_at": now(), "budget_cap_usd": BUDGET_CAP_USD}


def save_manifest(manifest: dict) -> None:
    MANIFEST_PATH.parent.mkdir(parents=True, exist_ok=True)
    MANIFEST_PATH.write_text(json.dumps(manifest, indent=2))


def spent_so_far(manifest: dict | None = None) -> float:
    manifest = manifest if manifest is not None else load_manifest()
    total = 0.0
    for value in manifest.values():
        if isinstance(value, dict) and value.get("actual_cost_usd") is not None:
            total += value["actual_cost_usd"]
    return round(total, 4)


def remaining_budget(manifest: dict | None = None) -> float:
    return round(BUDGET_CAP_USD - spent_so_far(manifest), 4)


def enforce_budget(estimated_cost: float) -> None:
    """Hard cross-script guard: refuse this call if it would push total
    real spend past BUDGET_CAP_USD, independent of the calling script's
    own per-stage MAX_SPEND_USD cap."""
    manifest = load_manifest()
    spent = spent_so_far(manifest)
    remaining = round(BUDGET_CAP_USD - spent, 4)
    if estimated_cost > remaining:
        fail(
            f"This call's estimated cost ${estimated_cost:.2f} would exceed the remaining hard "
            f"budget (${remaining:.2f} of ${BUDGET_CAP_USD:.2f} left, ${spent:.2f} already spent "
            "across this video). Stopping - hard budget protection. Nothing was generated."
        )
    print(f"Budget check: ${spent:.2f} spent, ${remaining:.2f} remaining of ${BUDGET_CAP_USD:.2f} cap.")


def run_gated_video_shot(
    *,
    shot_key: str,
    title: str,
    upstream_path: Path,
    upstream_label: str,
    needs_frame_extraction: bool,
    start_frame_path: Path,
    prompt: str,
    duration_seconds: float,
    max_spend_usd: float,
    raw_output_path: Path,
    job_state_path: Path,
    review_checklist: list[str],
    next_step_note: str,
) -> None:
    """Generic hard-gated Wan 3.0 shot runner shared by every Video #2 shot
    script. `needs_frame_extraction=True` extracts a real last frame from
    upstream_path (a video) into start_frame_path first; False means
    upstream_path IS already a still image, used directly as the start
    frame (start_frame_path is then set equal to upstream_path by the
    caller)."""
    from app.config import settings
    from app.providers.base import ProviderJobState, VideoGenerationRequest, VideoProviderError
    from app.providers.video.fal import WAN_3_0_STANDARD, FalVideoProvider
    from app.services.frame_extraction import FrameExtractionError, extract_last_frame

    skip_confirm = "--yes" in sys.argv[1:]

    key_preview = f"{settings.fal_api_key[:6]}..." if settings.fal_api_key else None
    print(f"FAL_API_KEY loaded from .env: {'yes (' + key_preview + ')' if key_preview else 'NO'}")
    if not settings.fal_api_key:
        fail("FAL_API_KEY is not set. Add FAL_API_KEY=your_key_here to your .env file and try again.")

    if not upstream_path.exists():
        fail(f"{upstream_path} not found - {upstream_label} has not been generated yet.")

    print(f"\nUpstream file found: {upstream_path}")
    approval = input(
        f"Have you reviewed and approved {upstream_path.name}? Type 'yes' to confirm before "
        "proceeding (anything else stops here, nothing generated): "
    ).strip().lower()
    if approval != "yes":
        print(f"Stopped - {upstream_label} was not confirmed as approved. Nothing was generated.")
        sys.exit(0)

    if needs_frame_extraction:
        print(f"\nExtracting the real last frame of {upstream_path.name} locally (no API call)...")
        try:
            extract_last_frame(upstream_path, start_frame_path)
        except FrameExtractionError as e:
            fail(f"Frame extraction failed: {e}")
        print(f"      Done -> {start_frame_path} ({upstream_path.name} was only read, never modified)")

    video_provider = FalVideoProvider(dataclasses.replace(WAN_3_0_STANDARD, extra_payload={"duration": int(duration_seconds)}))
    video_request = VideoGenerationRequest(
        prompt=prompt,
        reference_image_path=str(start_frame_path),
        aspect_ratio=ASPECT_RATIO,
        duration_seconds=duration_seconds,
        extra_params={"resolution": RESOLUTION},
    )
    video_cost = video_provider.estimate_cost(video_request)

    print("=" * 70)
    print(f"FORMA VIDEO #2 - {title} - THIS WILL SPEND REAL MONEY")
    print("=" * 70)
    print(f"Video model: {video_provider.model_config.submit_path}  ({RESOLUTION}, {ASPECT_RATIO}, {duration_seconds:.0f}s)")
    print(f"Source image: {start_frame_path}")
    print(f"\nVideo prompt:\n  {prompt}")
    print(f"\nEstimated cost: ${video_cost:.4f}")
    print(f"Hard cap:       ${max_spend_usd:.2f}")
    print("=" * 70)

    if video_cost > max_spend_usd:
        fail(f"Estimated cost ${video_cost:.4f} exceeds the ${max_spend_usd:.2f} cap. Nothing was generated.")
    enforce_budget(video_cost)

    if not skip_confirm:
        answer = input(f"\nType 'yes' to spend up to ${video_cost:.4f} and proceed: ").strip().lower()
        if answer != "yes":
            print("Cancelled. Nothing was generated.")
            sys.exit(0)

    manifest = load_manifest()
    manifest[shot_key] = {
        "video_model": video_provider.model_config.submit_path,
        "resolution": RESOLUTION,
        "aspect_ratio": ASPECT_RATIO,
        "duration_seconds": duration_seconds,
        "video_prompt": prompt,
        "start_frame_path": str(start_frame_path),
        "max_spend_usd": max_spend_usd,
        "estimated_cost_usd": video_cost,
        "raw_video_path": None,
        "actual_cost_usd": None,
        "completed_at": None,
    }
    save_manifest(manifest)

    print(f"\nSubmitting {title} video generation job (Wan 3.0 standard, {RESOLUTION})...")
    t0 = time.monotonic()
    try:
        submitted = video_provider.submit_video_job(video_request)
    except VideoProviderError as e:
        fail(f"Video submission failed: {e}")
    print(f"      Submitted. Provider job id: {submitted.provider_job_id}")

    job_state_path.write_text(json.dumps({"provider_job_id": submitted.provider_job_id, "meta": submitted.meta}, indent=2))
    print(f"      Job state saved to: {job_state_path}")

    print("      Polling for completion (no retries on error - any failure stops here)...")
    result = None
    while True:
        elapsed = time.monotonic() - t0
        if elapsed > 300:
            fail(
                f"Gave up after {elapsed:.0f}s. To recover: "
                f"python -m scripts.recover_fal_video_job {submitted.provider_job_id}"
            )
        try:
            result = video_provider.get_job_status(submitted.provider_job_id, meta=submitted.meta)
        except VideoProviderError as e:
            fail(
                f"Status check failed: {e}\n"
                f"      To recover: python -m scripts.recover_fal_video_job {submitted.provider_job_id}"
            )
        if result.status == ProviderJobState.PROCESSING:
            print(f"      ...still processing ({elapsed:.0f}s elapsed)")
            time.sleep(3)
            continue
        break

    if result.status == ProviderJobState.FAILED:
        fail(f"Provider reported generation failure: {result.error_message}")

    print(f"      Completed in {time.monotonic() - t0:.1f}s")

    try:
        video_provider.download_result(submitted.provider_job_id, result.output_url, str(raw_output_path))
    except VideoProviderError as e:
        fail(
            f"Download failed (generation already billed): {e}\n"
            f"      To recover: python -m scripts.recover_fal_video_job {submitted.provider_job_id}"
        )

    actual_cost = result.actual_cost_usd if result.actual_cost_usd is not None else submitted.estimated_cost_usd
    manifest[shot_key]["raw_video_path"] = str(raw_output_path)
    manifest[shot_key]["actual_cost_usd"] = actual_cost
    manifest[shot_key]["completed_at"] = now()
    save_manifest(manifest)

    print("\n" + "=" * 70)
    print(f"{title} DONE - stopping completely, as required.")
    print("=" * 70)
    print(f"Raw:      {raw_output_path}")
    print(f"Cost:     ${actual_cost:.4f}")
    print(f"Manifest: {MANIFEST_PATH}")
    print(f"\nSTOP HERE. Review {raw_output_path.name} against:")
    for i, item in enumerate(review_checklist, 1):
        print(f"  {i}. {item}")
    print(f"\n{next_step_note}")


def run_gated_edit(
    *,
    edit_key: str,
    title: str,
    upstream_path: Path,
    upstream_label: str,
    needs_frame_extraction: bool,
    start_frame_path: Path,
    edit_prompt: str,
    output_image_path: Path,
    max_spend_usd: float,
    review_checklist: list[str],
    next_step_note: str,
) -> None:
    """Generic hard-gated NANO_BANANA_PRO_EDIT runner shared by every
    Video #2 jump-cut/transition script."""
    from app.config import settings
    from app.providers.base import ImageEditRequest, ImageProviderError
    from app.providers.image.fal import NANO_BANANA_PRO_EDIT, FalImageProvider
    from app.services.frame_extraction import FrameExtractionError, extract_last_frame

    skip_confirm = "--yes" in sys.argv[1:]

    key_preview = f"{settings.fal_api_key[:6]}..." if settings.fal_api_key else None
    print(f"FAL_API_KEY loaded from .env: {'yes (' + key_preview + ')' if key_preview else 'NO'}")
    if not settings.fal_api_key:
        fail("FAL_API_KEY is not set. Add FAL_API_KEY=your_key_here to your .env file and try again.")

    if not upstream_path.exists():
        fail(f"{upstream_path} not found - {upstream_label} has not been generated yet.")

    print(f"\nUpstream file found: {upstream_path}")
    approval = input(
        f"Have you reviewed and approved {upstream_path.name}? Type 'yes' to confirm before "
        "proceeding (anything else stops here, nothing generated): "
    ).strip().lower()
    if approval != "yes":
        print(f"Stopped - {upstream_label} was not confirmed as approved. Nothing was generated.")
        sys.exit(0)

    if needs_frame_extraction:
        print(f"\nExtracting the real last frame of {upstream_path.name} locally (no API call)...")
        try:
            extract_last_frame(upstream_path, start_frame_path)
        except FrameExtractionError as e:
            fail(f"Frame extraction failed: {e}")
        print(f"      Done -> {start_frame_path} ({upstream_path.name} was only read, never modified)")

    image_provider = FalImageProvider(NANO_BANANA_PRO_EDIT)
    edit_request = ImageEditRequest(prompt=edit_prompt, reference_image_paths=[str(start_frame_path)])
    cost = image_provider.estimate_edit_cost()

    print("=" * 70)
    print(f"FORMA VIDEO #2 - {title} - THIS WILL SPEND REAL MONEY")
    print("=" * 70)
    print(f"Model: {NANO_BANANA_PRO_EDIT.model_id}  (image edit)")
    print(f"Source image: {start_frame_path}")
    print(f"\nEdit prompt:\n  {edit_prompt}")
    print(f"\nEstimated cost: ${cost:.4f}")
    print(f"Hard cap:       ${max_spend_usd:.2f}")
    print("=" * 70)

    if cost > max_spend_usd:
        fail(f"Estimated cost ${cost:.4f} exceeds the ${max_spend_usd:.2f} cap. Nothing was generated.")
    enforce_budget(cost)

    if not skip_confirm:
        answer = input(f"\nType 'yes' to spend up to ${cost:.4f} and proceed: ").strip().lower()
        if answer != "yes":
            print("Cancelled. Nothing was generated.")
            sys.exit(0)

    manifest = load_manifest()
    manifest[edit_key] = {
        "image_model": NANO_BANANA_PRO_EDIT.model_id,
        "source_frame_path": str(start_frame_path),
        "edit_prompt": edit_prompt,
        "max_spend_usd": max_spend_usd,
        "estimated_cost_usd": cost,
        "output_path": None,
        "actual_cost_usd": None,
        "completed_at": None,
    }
    save_manifest(manifest)

    print(f"\nRequesting {title} -> {output_image_path.name} ...")
    try:
        result = image_provider.edit_image(edit_request, str(output_image_path))
    except ImageProviderError as e:
        fail(f"Edit failed: {e}")
    print(f"      Done -> {output_image_path} (${result.cost_usd:.4f})")

    manifest[edit_key]["output_path"] = str(output_image_path)
    manifest[edit_key]["actual_cost_usd"] = result.cost_usd
    manifest[edit_key]["completed_at"] = now()
    save_manifest(manifest)

    print("\n" + "=" * 70)
    print(f"{title} DONE - stopping completely, as required.")
    print("=" * 70)
    print(f"Output:   {output_image_path}")
    print(f"Cost:     ${result.cost_usd:.4f}")
    print(f"Manifest: {MANIFEST_PATH}")
    print(f"\nSTOP HERE. Review {output_image_path.name} against:")
    for i, item in enumerate(review_checklist, 1):
        print(f"  {i}. {item}")
    print(f"\n{next_step_note}")
