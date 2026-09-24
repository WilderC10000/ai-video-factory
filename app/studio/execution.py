"""Run one launchable stage through the real pipeline code, in the configured mode.

live     - the stage's own SPEC / assemble_final with the real fal providers, on the
           real ./data manifests. Paid.
mock     - the same pipeline functions with mock providers ($0.00), and every
           path remapped from ./data into the sandbox copy, so real project files
           and manifests can never be touched.
disabled - nothing runs.
"""
import dataclasses
from pathlib import Path

from app.config import ROOT_DIR, settings
from app.studio.actions import StageAction
from app.studio.models import StageKind

REAL_DATA_DIR = (ROOT_DIR / "data").resolve()
EXECUTION_MODES = ("disabled", "mock", "live")


class ExecutionRefused(Exception):
    pass


def execution_mode() -> str:
    mode = settings.studio_execution_mode.strip().lower()
    return mode if mode in EXECUTION_MODES else "disabled"


def data_root() -> Path:
    return settings.studio_data_path


def mode_problems() -> list[str]:
    """Why launching is impossible in the current configuration (empty = OK)."""
    mode = execution_mode()
    if mode == "disabled":
        return ["Execution is disabled (STUDIO_EXECUTION_MODE=disabled). Approvals are recorded; "
                "run the stage script from the terminal, or restart the backend in mock or live mode."]
    root = data_root()
    if mode == "mock" and root == REAL_DATA_DIR:
        return ["Mock mode must run against a sandbox copy, not ./data. Set STUDIO_DATA_DIR to the "
                "sandbox created by `python -m scripts.studio_sandbox`."]
    if mode == "live":
        if root != REAL_DATA_DIR:
            return ["Live mode runs the pipeline on ./data; STUDIO_DATA_DIR must be ./data."]
        if not settings.fal_api_key:
            return ["Live mode needs FAL_API_KEY in .env."]
    return []


def execution_info() -> dict:
    problems = mode_problems()
    return {
        "mode": execution_mode(),
        "launch_enabled": not problems,
        "problems": problems,
        "sandbox": execution_mode() == "mock",
        "data_root": str(data_root()),
    }


def _remap(path: Path, root: Path) -> Path:
    """Point a pipeline path at `root` instead of ./data (identity in live mode)."""
    path = Path(path)
    resolved = path.resolve()
    if root == REAL_DATA_DIR or not resolved.is_relative_to(REAL_DATA_DIR):
        return path
    return root / resolved.relative_to(REAL_DATA_DIR)


def _remap_spec(spec, root: Path):
    changes = {f.name: _remap(getattr(spec, f.name), root)
               for f in dataclasses.fields(spec) if isinstance(getattr(spec, f.name), Path)}
    return dataclasses.replace(spec, **changes)


def _mock_video_provider():
    import shutil
    import subprocess

    from app.providers.video.mock import MockVideoProvider, VideoPricingConfig

    class SandboxVideoProvider(MockVideoProvider):
        """Mock provider whose "output" is a 2s still of the shot's own start frame at
        the real clips' 480x854 - obviously not a render, but concat-compatible, so
        the whole chain through final assembly can be exercised for $0.00."""

        name = "sandbox-mock-video"

        def submit_video_job(self, request):
            submitted = super().submit_video_job(request)
            self._jobs[submitted.provider_job_id]["still"] = request.reference_image_path
            return submitted

        def download_result(self, provider_job_id, output_url, destination_path):
            still = self._jobs.get(provider_job_id, {}).get("still")
            ffmpeg = shutil.which("ffmpeg")
            if not (still and ffmpeg):
                return super().download_result(provider_job_id, output_url, destination_path)
            Path(destination_path).parent.mkdir(parents=True, exist_ok=True)
            subprocess.run(
                [ffmpeg, "-y", "-loglevel", "error", "-loop", "1", "-i", still, "-t", "2", "-r", "30",
                 "-vf", "scale=480:854:force_original_aspect_ratio=decrease,pad=480:854:(ow-iw)/2:(oh-ih)/2,"
                        "setsar=1,format=yuv420p",
                 "-c:v", "libx264", destination_path],
                check=True, capture_output=True,
            )
            return destination_path

    # $0.00 so the sandbox manifest never records a simulated "spend".
    return SandboxVideoProvider(VideoPricingConfig(billing="flat", price_by_resolution={"480p": 0.0, "720p": 0.0}))


def _mock_image_provider():
    from app.providers.image.mock import MockImageProvider

    return MockImageProvider(cost_per_megapixel=0.0)


def run_action(action: StageAction, *, retry: bool, on_phase, log) -> dict:
    """Execute the stage. Returns the pipeline function's result dict; raises on failure."""
    problems = mode_problems()
    if problems:
        raise ExecutionRefused(problems[0])
    mode, root = execution_mode(), data_root()
    manifest_path = root / action.project_slug / "manifest.json"
    log(f"[studio] {mode.upper()} run of {action.stage.label} ({action.module_name}); manifest: {manifest_path}")

    if action.kind == StageKind.ASSEMBLY:
        module = action.module()
        on_phase("generating", None)
        return module.assemble_final(
            [(name, _remap(p, root), factor) for name, p, factor in module.CLIP_SPECS],
            _remap(module.FINAL_DIR, root),
            _remap(module.FINAL_VISUAL_MASTER_PATH, root),
            manifest_path,
            log,
        )

    from scripts import run_alpine_video_2_common as pipeline

    spec = _remap_spec(action.spec(), root)

    def confirmed(*_args) -> bool:
        # The explicit confirmation is the click in the studio's confirm panel, made
        # before this job existed. This runs only after the pipeline's own upstream,
        # cap and budget checks pass, immediately before anything is spent - so a
        # refused retry never archives (hides) the current attempt.
        if retry:
            output = spec.raw_output_path if action.kind == StageKind.VIDEO else spec.output_image_path
            archived = pipeline.archive_attempt(action.stage.key, output, manifest_path)
            if archived:
                log(f"[studio] Previous attempt kept as manifest entry '{archived}' (its spend still counts).")
        return True

    if action.kind == StageKind.VIDEO:
        return pipeline.execute_video_shot(
            spec,
            video_provider=_mock_video_provider() if mode == "mock" else None,
            manifest_path=manifest_path,
            confirm_spend=confirmed,
            on_phase=on_phase,
            log=log,
            poll_interval_seconds=0.5 if mode == "mock" else 3.0,
            timeout_seconds=900.0,
        )
    return pipeline.execute_edit(
        spec,
        image_provider=_mock_image_provider() if mode == "mock" else None,
        manifest_path=manifest_path,
        confirm_spend=confirmed,
        on_phase=on_phase,
        log=log,
    )
