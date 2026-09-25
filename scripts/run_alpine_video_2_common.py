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

execute_video_shot() / execute_edit() are the non-interactive service form of
each stage (used by the FORMA Virtual Studio job runner); run_gated_video_shot()
/ run_gated_edit() are the CLI wrappers that add the interactive approval and
spend prompts on top, so every stage script still runs from the terminal.
"""
import dataclasses
import hashlib
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


class PipelineStepError(Exception):
    """A pipeline step refused or failed. Nothing further was generated."""


def fail(message: str) -> None:
    print(f"\nSTOPPED: {message}")
    print("No retry, no further generation - the script is exiting now.")
    sys.exit(1)


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def load_manifest(manifest_path: Path | None = None) -> dict:
    path = manifest_path or MANIFEST_PATH
    if path.exists():
        return json.loads(path.read_text())
    return {"experiment": "alpine_video_2", "created_at": now(), "budget_cap_usd": BUDGET_CAP_USD}


def save_manifest(manifest: dict, manifest_path: Path | None = None) -> None:
    path = manifest_path or MANIFEST_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(manifest, indent=2))


def spent_so_far(manifest: dict | None = None) -> float:
    manifest = manifest if manifest is not None else load_manifest()
    total = 0.0
    for value in manifest.values():
        if isinstance(value, dict) and value.get("actual_cost_usd") is not None:
            total += value["actual_cost_usd"]
    return round(total, 4)


def remaining_budget(manifest: dict | None = None) -> float:
    return round(BUDGET_CAP_USD - spent_so_far(manifest), 4)


def check_budget(estimated_cost: float, manifest_path: Path | None = None) -> str:
    """Hard cross-script guard: raise PipelineStepError if this call would push
    total real spend past the budget cap, independent of the calling stage's own
    per-stage MAX_SPEND_USD cap. Returns a one-line summary when it's allowed."""
    manifest = load_manifest(manifest_path)
    cap = manifest.get("budget_cap_usd", BUDGET_CAP_USD)
    if cap is None:
        raise PipelineStepError(
            "This project's manifest has no budget_cap_usd set. Set one explicitly before any paid call. "
            "Nothing was generated."
        )
    spent = spent_so_far(manifest)
    remaining = round(cap - spent, 4)
    if estimated_cost > remaining:
        raise PipelineStepError(
            f"This call's estimated cost ${estimated_cost:.2f} would exceed the remaining hard "
            f"budget (${remaining:.2f} of ${cap:.2f} left, ${spent:.2f} already spent "
            "across this video). Stopping - hard budget protection. Nothing was generated."
        )
    return f"Budget check: ${spent:.2f} spent, ${remaining:.2f} remaining of ${cap:.2f} cap."


def enforce_budget(estimated_cost: float) -> None:
    """CLI form of check_budget(): prints the summary or exits."""
    try:
        print(check_budget(estimated_cost))
    except PipelineStepError as e:
        fail(str(e))


def archive_attempt(stage_key: str, output_path: Path, manifest_path: Path | None = None) -> str | None:
    """Before re-running a stage that already has a manifest entry, keep the old
    attempt instead of overwriting it: the entry moves to `<key>__attemptN` (so
    its real spend still counts in spent_so_far) and its output file is renamed
    to `<name>.attemptN<ext>`. Returns the archive key, or None if nothing existed."""
    manifest = load_manifest(manifest_path)
    entry = manifest.get(stage_key)
    if not isinstance(entry, dict):
        return None
    n = 1
    while f"{stage_key}__attempt{n}" in manifest:
        n += 1
    archive_key = f"{stage_key}__attempt{n}"
    for field_name in ("raw_video_path", "output_path"):
        recorded = entry.get(field_name)
        if recorded and Path(recorded).is_file():
            src = Path(recorded)
            dst = src.with_name(f"{src.stem}.attempt{n}{src.suffix}")
            src.rename(dst)
            entry[field_name] = str(dst)
    if output_path.is_file():  # an output with no manifest record (e.g. crashed after download)
        output_path.rename(output_path.with_name(f"{output_path.stem}.attempt{n}{output_path.suffix}"))
    entry["archived_at"] = now()
    manifest[archive_key] = entry
    del manifest[stage_key]
    save_manifest(manifest, manifest_path)
    return archive_key


@dataclasses.dataclass(frozen=True)
class VideoShotSpec:
    """Everything one Wan image-to-video stage needs. Each shot script defines one as SPEC."""

    shot_key: str
    title: str
    upstream_path: Path
    upstream_label: str
    needs_frame_extraction: bool
    start_frame_path: Path
    prompt: str
    duration_seconds: float
    max_spend_usd: float
    raw_output_path: Path
    job_state_path: Path
    review_checklist: list[str]
    next_step_note: str
    # First/last-frame conditioning: the approved still the clip must end on (None = start frame only).
    end_frame_path: Path | None = None
    # Turn off fal's LLM prompt rewriting so precise continuity wording reaches the model unaltered.
    disable_prompt_expansion: bool = False


@dataclasses.dataclass(frozen=True)
class ImageGenerateSpec:
    """One Nano Banana Pro text-to-image still (e.g. an establishing checkpoint)."""

    key: str
    title: str
    prompt: str
    output_image_path: Path
    max_spend_usd: float
    review_checklist: list[str]
    next_step_note: str
    aspect_ratio: str = "9:16"
    resolution: str = "1K"


@dataclasses.dataclass(frozen=True)
class EditSpec:
    """Everything one Nano Banana Pro EDIT checkpoint stage needs. Each edit script defines one as SPEC."""

    edit_key: str
    title: str
    upstream_path: Path
    upstream_label: str
    needs_frame_extraction: bool
    start_frame_path: Path
    edit_prompt: str
    output_image_path: Path
    max_spend_usd: float
    review_checklist: list[str]
    next_step_note: str


def _noop(*_args, **_kwargs) -> None:
    return None


def _prepare_start_frame(spec, log) -> None:
    from app.services.frame_extraction import FrameExtractionError, extract_last_frame

    if not spec.upstream_path.exists():
        raise PipelineStepError(f"{spec.upstream_path} not found - {spec.upstream_label} has not been generated yet.")
    if spec.needs_frame_extraction:
        log(f"Extracting the real last frame of {spec.upstream_path.name} locally (no API call)...")
        try:
            extract_last_frame(spec.upstream_path, spec.start_frame_path)
        except FrameExtractionError as e:
            raise PipelineStepError(f"Frame extraction failed: {e}") from e
        log(f"      Done -> {spec.start_frame_path} ({spec.upstream_path.name} was only read, never modified)")


def default_video_provider(spec: VideoShotSpec):
    from app.providers.video.fal import WAN_3_0_STANDARD, FalVideoProvider

    return FalVideoProvider(dataclasses.replace(WAN_3_0_STANDARD, extra_payload={"duration": int(spec.duration_seconds)}))


def default_image_provider():
    from app.providers.image.fal import NANO_BANANA_PRO_EDIT, FalImageProvider

    return FalImageProvider(NANO_BANANA_PRO_EDIT)


def execute_video_shot(
    spec: VideoShotSpec,
    *,
    video_provider=None,
    manifest_path: Path | None = None,
    confirm_spend=None,
    on_phase=None,
    log=print,
    poll_interval_seconds: float = 3.0,
    timeout_seconds: float = 300.0,
) -> dict:
    """Run one Wan shot end to end with no interactive prompts. Upstream approval
    must already have been given by the caller. `confirm_spend(provider, request,
    cost)` is called after every budget check and before any spend; returning
    False cancels with nothing generated. `on_phase(phase, detail)` reports real
    job state: submitting, provider_queued, generating, downloading. Raises
    PipelineStepError on any refusal or failure."""
    from app.providers.base import ProviderJobState, VideoGenerationRequest, VideoProviderError

    on_phase = on_phase or _noop
    _prepare_start_frame(spec, log)
    if spec.end_frame_path is not None and not Path(spec.end_frame_path).is_file():
        raise PipelineStepError(f"End frame {spec.end_frame_path} not found - its checkpoint still must exist first.")
    # Output folders exist before anything is spent: a failure to write the job state or the
    # download after submission would otherwise strand an already-billed job.
    spec.job_state_path.parent.mkdir(parents=True, exist_ok=True)
    spec.raw_output_path.parent.mkdir(parents=True, exist_ok=True)

    video_provider = video_provider or default_video_provider(spec)
    extra_params = {"resolution": RESOLUTION}
    if spec.disable_prompt_expansion:
        extra_params["enable_prompt_expansion"] = False
    video_request = VideoGenerationRequest(
        prompt=spec.prompt,
        reference_image_path=str(spec.start_frame_path),
        end_image_path=str(spec.end_frame_path) if spec.end_frame_path is not None else None,
        aspect_ratio=ASPECT_RATIO,
        duration_seconds=spec.duration_seconds,
        extra_params=extra_params,
    )
    video_cost = video_provider.estimate_cost(video_request)
    if video_cost > spec.max_spend_usd:
        raise PipelineStepError(
            f"Estimated cost ${video_cost:.4f} exceeds the ${spec.max_spend_usd:.2f} cap. Nothing was generated."
        )
    log(check_budget(video_cost, manifest_path))
    if confirm_spend is not None and not confirm_spend(video_provider, video_request, video_cost):
        raise PipelineStepError("Cancelled. Nothing was generated.")

    model_name = getattr(getattr(video_provider, "model_config", None), "submit_path", type(video_provider).__name__)
    manifest = load_manifest(manifest_path)
    manifest[spec.shot_key] = {
        "video_model": model_name,
        "resolution": RESOLUTION,
        "aspect_ratio": ASPECT_RATIO,
        "duration_seconds": spec.duration_seconds,
        "video_prompt": spec.prompt,
        "start_frame_path": str(spec.start_frame_path),
        "end_frame_path": str(spec.end_frame_path) if spec.end_frame_path is not None else None,
        # Exact frames used, so a clip can be recognised as stale if a still is later replaced.
        "start_frame_sha256": hashlib.sha256(Path(spec.start_frame_path).read_bytes()).hexdigest(),
        "end_frame_sha256": (hashlib.sha256(Path(spec.end_frame_path).read_bytes()).hexdigest()
                             if spec.end_frame_path is not None else None),
        "max_spend_usd": spec.max_spend_usd,
        "estimated_cost_usd": video_cost,
        "raw_video_path": None,
        "actual_cost_usd": None,
        "completed_at": None,
    }
    save_manifest(manifest, manifest_path)

    on_phase("submitting", None)
    log(f"\nSubmitting {spec.title} video generation job ({RESOLUTION})...")
    t0 = time.monotonic()
    try:
        submitted = video_provider.submit_video_job(video_request)
    except VideoProviderError as e:
        raise PipelineStepError(f"Video submission failed: {e}") from e
    log(f"      Submitted. Provider job id: {submitted.provider_job_id}")
    # Record the job id immediately, not only on completion, so it can never be lost if this
    # process stops, times out or is superseded before the job finishes.
    manifest = load_manifest(manifest_path)
    manifest[spec.shot_key]["provider_job_id"] = submitted.provider_job_id
    save_manifest(manifest, manifest_path)
    on_phase("provider_queued", submitted.provider_job_id)

    spec.job_state_path.write_text(json.dumps({"provider_job_id": submitted.provider_job_id, "meta": submitted.meta}, indent=2))
    log(f"      Job state saved to: {spec.job_state_path}")

    recover = f"      To recover: python -m scripts.recover_fal_video_job {submitted.provider_job_id}"
    log("      Polling for completion (no retries on error - any failure stops here)...")
    while True:
        elapsed = time.monotonic() - t0
        if elapsed > timeout_seconds:
            raise PipelineStepError(f"Gave up after {elapsed:.0f}s. To recover: python -m scripts.recover_fal_video_job {submitted.provider_job_id}")
        try:
            result = video_provider.get_job_status(submitted.provider_job_id, meta=submitted.meta)
        except VideoProviderError as e:
            raise PipelineStepError(f"Status check failed: {e}\n{recover}") from e
        if result.status == ProviderJobState.PROCESSING:
            provider_status = (result.meta or {}).get("provider_status")
            on_phase("provider_queued" if provider_status == "IN_QUEUE" else "generating", provider_status)
            log(f"      ...still processing ({elapsed:.0f}s elapsed)")
            time.sleep(poll_interval_seconds)
            continue
        break

    if result.status == ProviderJobState.FAILED:
        raise PipelineStepError(f"Provider reported generation failure: {result.error_message}")

    log(f"      Completed in {time.monotonic() - t0:.1f}s")
    on_phase("downloading", None)
    try:
        video_provider.download_result(submitted.provider_job_id, result.output_url, str(spec.raw_output_path))
    except VideoProviderError as e:
        raise PipelineStepError(f"Download failed (generation already billed): {e}\n{recover}") from e

    actual_cost = result.actual_cost_usd if result.actual_cost_usd is not None else submitted.estimated_cost_usd
    manifest = load_manifest(manifest_path)
    manifest[spec.shot_key]["provider_job_id"] = submitted.provider_job_id
    manifest[spec.shot_key]["raw_video_path"] = str(spec.raw_output_path)
    manifest[spec.shot_key]["actual_cost_usd"] = actual_cost
    manifest[spec.shot_key]["completed_at"] = now()
    save_manifest(manifest, manifest_path)
    return {
        "output_path": str(spec.raw_output_path),
        "actual_cost_usd": actual_cost,
        "estimated_cost_usd": video_cost,
        "provider_job_id": submitted.provider_job_id,
    }


def recover_video_shot(
    spec: VideoShotSpec,
    *,
    video_provider=None,
    manifest_path: Path | None = None,
    on_phase=None,
    log=print,
    wait: bool = True,
    poll_interval_seconds: float = 10.0,
    timeout_seconds: float = 2700.0,
) -> dict:
    """Finish an ALREADY-SUBMITTED shot without ever submitting again.

    Uses the provider job id and status/response URLs saved in spec.job_state_path at
    submission time, polls the provider's status (free GET requests), and - once the
    existing job has completed - downloads the result into spec.raw_output_path and
    completes the shot's existing manifest entry (provider job id and cost preserved).
    There is deliberately no code path here that calls submit_video_job.

    Returns {"status": "completed" | "queued" | "generating", ...}. Raises
    PipelineStepError if there is nothing to recover or the provider reports failure."""
    from app.providers.base import ProviderJobState, VideoProviderError

    on_phase = on_phase or _noop
    manifest = load_manifest(manifest_path)
    entry = manifest.get(spec.shot_key)
    if not isinstance(entry, dict):
        raise PipelineStepError(f"{spec.shot_key} has no manifest entry - it was never submitted, nothing to recover.")
    if entry.get("completed_at"):
        return {"status": "completed", "output_path": entry.get("raw_video_path"),
                "actual_cost_usd": entry.get("actual_cost_usd"), "provider_job_id": entry.get("provider_job_id"),
                "note": "already complete - nothing to do"}
    try:
        state = json.loads(spec.job_state_path.read_text())
    except (OSError, ValueError) as e:
        raise PipelineStepError(f"No saved job state at {spec.job_state_path} ({e}) - cannot identify the provider job.") from e
    job_id, meta = state.get("provider_job_id"), state.get("meta") or {}
    if not job_id:
        raise PipelineStepError(f"{spec.job_state_path} has no provider_job_id - cannot recover.")

    video_provider = video_provider or default_video_provider(spec)
    log(f"Recovering existing provider job {job_id} for {spec.shot_key} (status checks only; nothing is resubmitted).")
    t0 = time.monotonic()
    while True:
        try:
            result = video_provider.get_job_status(job_id, meta=meta)
        except VideoProviderError as e:
            raise PipelineStepError(f"Status check failed: {e}. Nothing was resubmitted; safe to try recovery again.") from e
        if result.status != ProviderJobState.PROCESSING:
            break
        provider_status = (result.meta or {}).get("provider_status")
        phase = "provider_queued" if provider_status == "IN_QUEUE" else "generating"
        on_phase(phase, job_id)
        elapsed = time.monotonic() - t0
        log(f"      ...{provider_status or 'processing'} ({elapsed:.0f}s)")
        if not wait:
            return {"status": "queued" if phase == "provider_queued" else "generating", "provider_job_id": job_id,
                    "provider_status": provider_status}
        if elapsed > timeout_seconds:
            raise PipelineStepError(f"Still {provider_status or 'processing'} after {elapsed:.0f}s. The provider job "
                                    f"{job_id} is untouched - run recovery again later.")
        time.sleep(poll_interval_seconds)

    if result.status == ProviderJobState.FAILED:
        raise PipelineStepError(f"Provider reported failure for existing job {job_id}: {result.error_message}")

    on_phase("downloading", job_id)
    spec.raw_output_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        video_provider.download_result(job_id, result.output_url, str(spec.raw_output_path))
    except VideoProviderError as e:
        raise PipelineStepError(f"Download failed: {e}. The job is complete at the provider; retry recovery.") from e

    actual_cost = result.actual_cost_usd if result.actual_cost_usd is not None else entry.get("estimated_cost_usd")
    manifest = load_manifest(manifest_path)
    manifest[spec.shot_key].update({
        "raw_video_path": str(spec.raw_output_path),
        "actual_cost_usd": actual_cost,
        "provider_job_id": job_id,
        "recovered_at": now(),
        "completed_at": now(),
    })
    save_manifest(manifest, manifest_path)
    log(f"      Recovered -> {spec.raw_output_path} (${actual_cost:.4f}, provider job {job_id})")
    return {"status": "completed", "output_path": str(spec.raw_output_path), "actual_cost_usd": actual_cost,
            "provider_job_id": job_id}


def execute_edit(
    spec: EditSpec,
    *,
    image_provider=None,
    manifest_path: Path | None = None,
    confirm_spend=None,
    on_phase=None,
    log=print,
) -> dict:
    """Run one checkpoint edit end to end with no interactive prompts (see execute_video_shot)."""
    from app.providers.base import ImageEditRequest, ImageProviderError

    on_phase = on_phase or _noop
    _prepare_start_frame(spec, log)

    spec.output_image_path.parent.mkdir(parents=True, exist_ok=True)  # before any spend
    image_provider = image_provider or default_image_provider()
    edit_request = ImageEditRequest(prompt=spec.edit_prompt, reference_image_paths=[str(spec.start_frame_path)])
    cost = image_provider.estimate_edit_cost()
    if cost > spec.max_spend_usd:
        raise PipelineStepError(f"Estimated cost ${cost:.4f} exceeds the ${spec.max_spend_usd:.2f} cap. Nothing was generated.")
    log(check_budget(cost, manifest_path))
    if confirm_spend is not None and not confirm_spend(image_provider, edit_request, cost):
        raise PipelineStepError("Cancelled. Nothing was generated.")

    model_name = getattr(getattr(image_provider, "model_config", None), "model_id", type(image_provider).__name__)
    manifest = load_manifest(manifest_path)
    manifest[spec.edit_key] = {
        "image_model": model_name,
        "source_frame_path": str(spec.start_frame_path),
        "edit_prompt": spec.edit_prompt,
        "max_spend_usd": spec.max_spend_usd,
        "estimated_cost_usd": cost,
        "output_path": None,
        "actual_cost_usd": None,
        "completed_at": None,
    }
    save_manifest(manifest, manifest_path)

    on_phase("generating", None)
    log(f"\nRequesting {spec.title} -> {spec.output_image_path.name} ...")
    try:
        result = image_provider.edit_image(edit_request, str(spec.output_image_path))
    except ImageProviderError as e:
        raise PipelineStepError(f"Edit failed: {e}") from e
    log(f"      Done -> {spec.output_image_path} (${result.cost_usd:.4f})")

    manifest = load_manifest(manifest_path)
    manifest[spec.edit_key]["output_path"] = str(spec.output_image_path)
    manifest[spec.edit_key]["actual_cost_usd"] = result.cost_usd
    manifest[spec.edit_key]["completed_at"] = now()
    save_manifest(manifest, manifest_path)
    return {"output_path": str(spec.output_image_path), "actual_cost_usd": result.cost_usd, "estimated_cost_usd": cost}


def default_generate_provider():
    # Same model constant and request shape as the proven scripts/run_alpine_video_2_site_reference.py.
    from app.providers.image.fal import NANO_BANANA_PRO_GENERATE, FalImageProvider

    return FalImageProvider(NANO_BANANA_PRO_GENERATE)


def execute_generate(
    spec: ImageGenerateSpec,
    *,
    image_provider=None,
    manifest_path: Path | None = None,
    confirm_spend=None,
    on_phase=None,
    log=print,
) -> dict:
    """Generate one still from text with no interactive prompts (see execute_video_shot)."""
    from app.providers.base import ImageGenerationRequest, ImageProviderError

    on_phase = on_phase or _noop
    image_provider = image_provider or default_generate_provider()
    request = ImageGenerationRequest(
        prompt=spec.prompt, extra_params={"aspect_ratio": spec.aspect_ratio, "resolution": spec.resolution}
    )
    cost = image_provider.estimate_cost(request)
    if cost > spec.max_spend_usd:
        raise PipelineStepError(f"Estimated cost ${cost:.4f} exceeds the ${spec.max_spend_usd:.2f} cap. Nothing was generated.")
    log(check_budget(cost, manifest_path))
    if confirm_spend is not None and not confirm_spend(image_provider, request, cost):
        raise PipelineStepError("Cancelled. Nothing was generated.")

    model_name = getattr(getattr(image_provider, "model_config", None), "model_id", type(image_provider).__name__)
    manifest = load_manifest(manifest_path)
    manifest[spec.key] = {
        "image_model": model_name,
        "image_prompt": spec.prompt,
        "max_spend_usd": spec.max_spend_usd,
        "estimated_cost_usd": cost,
        "output_path": None,
        "actual_cost_usd": None,
        "completed_at": None,
    }
    save_manifest(manifest, manifest_path)

    on_phase("generating", None)
    log(f"\nGenerating {spec.title} -> {spec.output_image_path.name} ...")
    spec.output_image_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        result = image_provider.generate_image(request, str(spec.output_image_path))
    except ImageProviderError as e:
        raise PipelineStepError(f"Image generation failed: {e}") from e
    log(f"      Done -> {spec.output_image_path} (${result.cost_usd:.4f})")

    manifest = load_manifest(manifest_path)
    manifest[spec.key]["output_path"] = str(spec.output_image_path)
    manifest[spec.key]["actual_cost_usd"] = result.cost_usd
    manifest[spec.key]["completed_at"] = now()
    save_manifest(manifest, manifest_path)
    return {"output_path": str(spec.output_image_path), "actual_cost_usd": result.cost_usd, "estimated_cost_usd": cost}


# --- CLI wrappers: same prompts and output as before the service split -------------------


def _cli_preamble(spec) -> None:
    from app.config import settings

    key_preview = f"{settings.fal_api_key[:6]}..." if settings.fal_api_key else None
    print(f"FAL_API_KEY loaded from .env: {'yes (' + key_preview + ')' if key_preview else 'NO'}")
    if not settings.fal_api_key:
        fail("FAL_API_KEY is not set. Add FAL_API_KEY=your_key_here to your .env file and try again.")

    if not spec.upstream_path.exists():
        fail(f"{spec.upstream_path} not found - {spec.upstream_label} has not been generated yet.")

    print(f"\nUpstream file found: {spec.upstream_path}")
    approval = input(
        f"Have you reviewed and approved {spec.upstream_path.name}? Type 'yes' to confirm before "
        "proceeding (anything else stops here, nothing generated): "
    ).strip().lower()
    if approval != "yes":
        print(f"Stopped - {spec.upstream_label} was not confirmed as approved. Nothing was generated.")
        sys.exit(0)


def _cli_confirm(skip_confirm: bool, cost: float) -> bool:
    if skip_confirm:
        return True
    answer = input(f"\nType 'yes' to spend up to ${cost:.4f} and proceed: ").strip().lower()
    if answer != "yes":
        print("Cancelled. Nothing was generated.")
        sys.exit(0)
    return True


def run_gated_video_shot(spec: VideoShotSpec | None = None, **kwargs) -> None:
    """Generic hard-gated Wan 3.0 shot runner shared by every Video #2 shot
    script (CLI). `needs_frame_extraction=True` extracts a real last frame from
    upstream_path (a video) into start_frame_path first; False means
    upstream_path IS already a still image, used directly as the start
    frame (start_frame_path is then set equal to upstream_path by the
    caller)."""
    spec = spec or VideoShotSpec(**kwargs)
    skip_confirm = "--yes" in sys.argv[1:]
    _cli_preamble(spec)

    def confirm(provider, _request, video_cost: float) -> bool:
        print("=" * 70)
        print(f"FORMA VIDEO #2 - {spec.title} - THIS WILL SPEND REAL MONEY")
        print("=" * 70)
        print(f"Video model: {provider.model_config.submit_path}  ({RESOLUTION}, {ASPECT_RATIO}, {spec.duration_seconds:.0f}s)")
        print(f"Source image: {spec.start_frame_path}")
        print(f"\nVideo prompt:\n  {spec.prompt}")
        print(f"\nEstimated cost: ${video_cost:.4f}")
        print(f"Hard cap:       ${spec.max_spend_usd:.2f}")
        print("=" * 70)
        return _cli_confirm(skip_confirm, video_cost)

    try:
        result = execute_video_shot(spec, confirm_spend=confirm)
    except PipelineStepError as e:
        fail(str(e))

    print("\n" + "=" * 70)
    print(f"{spec.title} DONE - stopping completely, as required.")
    print("=" * 70)
    print(f"Raw:      {spec.raw_output_path}")
    print(f"Cost:     ${result['actual_cost_usd']:.4f}")
    print(f"Manifest: {MANIFEST_PATH}")
    print(f"\nSTOP HERE. Review {spec.raw_output_path.name} against:")
    for i, item in enumerate(spec.review_checklist, 1):
        print(f"  {i}. {item}")
    print(f"\n{spec.next_step_note}")


def run_gated_edit(spec: EditSpec | None = None, **kwargs) -> None:
    """Generic hard-gated NANO_BANANA_PRO_EDIT runner shared by every
    Video #2 jump-cut/transition script (CLI)."""
    from app.providers.image.fal import NANO_BANANA_PRO_EDIT

    spec = spec or EditSpec(**kwargs)
    skip_confirm = "--yes" in sys.argv[1:]
    _cli_preamble(spec)

    def confirm(_provider, _request, cost: float) -> bool:
        print("=" * 70)
        print(f"FORMA VIDEO #2 - {spec.title} - THIS WILL SPEND REAL MONEY")
        print("=" * 70)
        print(f"Model: {NANO_BANANA_PRO_EDIT.model_id}  (image edit)")
        print(f"Source image: {spec.start_frame_path}")
        print(f"\nEdit prompt:\n  {spec.edit_prompt}")
        print(f"\nEstimated cost: ${cost:.4f}")
        print(f"Hard cap:       ${spec.max_spend_usd:.2f}")
        print("=" * 70)
        return _cli_confirm(skip_confirm, cost)

    try:
        result = execute_edit(spec, confirm_spend=confirm)
    except PipelineStepError as e:
        fail(str(e))

    print("\n" + "=" * 70)
    print(f"{spec.title} DONE - stopping completely, as required.")
    print("=" * 70)
    print(f"Output:   {spec.output_image_path}")
    print(f"Cost:     ${result['actual_cost_usd']:.4f}")
    print(f"Manifest: {MANIFEST_PATH}")
    print(f"\nSTOP HERE. Review {spec.output_image_path.name} against:")
    for i, item in enumerate(spec.review_checklist, 1):
        print(f"  {i}. {item}")
    print(f"\n{spec.next_step_note}")
