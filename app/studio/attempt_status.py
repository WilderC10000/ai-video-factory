"""Live status of provider attempts (<stage>__attemptN manifest entries), persisted in the manifest.

The manifest is the only state: whoever checks a job - the proof runner's poll loop or the studio -
writes the provider's answer back into the attempt's entry (`provider_status`, `status_checked_at`,
then `raw_video_path`/`completed_at` or `status: failed`). The studio snapshot derives the phase
from those persisted fields alone, so an unfinished attempt shows up the moment its job id is
recorded and still shows after a backend restart.

check_attempt() is a single FREE status read (plus the download when the provider reports the
clip done). It never submits, resubmits or retries a generation.
"""
import json
import os
from datetime import datetime, timezone
from pathlib import Path

from app.providers.base import ProviderJobState, VideoProviderError

# What the studio shows, in lifecycle order.
PHASES = ("not_started", "submitted", "queued", "generating", "downloading", "complete", "failed", "cancelled")
TERMINAL = ("complete", "failed", "cancelled")
_FAL_PHASE = {"IN_QUEUE": "queued", "IN_PROGRESS": "generating", "DOWNLOADING": "downloading"}

# A runner that is actively polling refreshes status_checked_at at least this often; while it is
# fresh the studio leaves the job to the runner instead of checking it too.
HEARTBEAT_FRESH_SECONDS = 45


class AttemptCheckError(Exception):
    pass


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _parse(ts: str | None) -> datetime | None:
    if not ts:
        return None
    dt = datetime.fromisoformat(ts)
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def attempt_phase(entry: dict, output_exists: bool) -> str:
    if entry.get("status") in ("cancelled", "failed"):
        return entry["status"]
    if entry.get("completed_at") and output_exists:
        return "complete"
    if not entry.get("provider_job_id"):
        return "not_started"
    return _FAL_PHASE.get((entry.get("provider_status") or "").upper(), "submitted")


def is_unfinished(entry: dict) -> bool:
    return bool(entry.get("provider_job_id")) and not entry.get("completed_at") and \
        entry.get("status") not in ("cancelled", "failed")


def heartbeat_fresh(entry: dict, now: datetime | None = None) -> bool:
    checked = _parse(entry.get("status_checked_at"))
    return checked is not None and ((now or _now()) - checked).total_seconds() < HEARTBEAT_FRESH_SECONDS


def raw_output_path(manifest_path: Path, key: str, model: str) -> Path:
    """Where a fal attempt's clip is downloaded: <project>/clips/<attempt key>_fal_<model slug>_raw.mp4."""
    return Path(manifest_path).parent / "clips" / f"{key}_fal_{model.replace('/', '_').replace('.', '-')}_raw.mp4"


def orphan_job_entries(manifest_path: Path, manifest: dict) -> dict[str, dict]:
    """Jobs whose job.json exists under provider_tests/ but whose manifest entry is missing (e.g. a crash
    between the two writes) - shown as submitted so no live job is ever invisible."""
    found = {}
    for job_file in (Path(manifest_path).parent / "provider_tests").glob("*/job.json"):
        try:
            setup = json.loads((job_file.parent / "setup.json").read_text())
            job = json.loads(job_file.read_text())
        except (OSError, ValueError):
            continue
        key = setup.get("attempt_key")
        if key and job.get("provider_job_id") and not (manifest.get(key) or {}).get("provider_job_id"):
            found[key] = {"provider": "fal", "video_model": (setup.get("model") or {}).get("endpoint_id"),
                          "provider_job_id": job["provider_job_id"], "meta": job.get("meta"),
                          "estimated_cost_usd": (setup.get("cost") or {}).get("expected_usd"),
                          "status_source": str(job_file)}
    return found


def _write_manifest(manifest_path: Path, manifest: dict) -> None:
    """Atomic replace, so a reader (or a concurrent writer's re-read) never sees a half-written file."""
    tmp = Path(manifest_path).with_suffix(".json.tmp")
    tmp.write_text(json.dumps(manifest, indent=2))
    os.replace(tmp, manifest_path)


def _update(manifest_path: Path, key: str, **fields) -> dict:
    manifest = json.loads(Path(manifest_path).read_text())  # re-read right before writing
    manifest[key].update(fields)
    _write_manifest(manifest_path, manifest)
    return manifest[key]


def fal_provider_for(entry: dict):
    from app.providers.video.fal import FAL_VIDEO_MODELS, FalVideoProvider

    if entry.get("provider") != "fal" or entry.get("video_model") not in FAL_VIDEO_MODELS:
        raise AttemptCheckError(f"Live checks cover fal attempts only (this is {entry.get('provider')} "
                                f"{entry.get('video_model')}).")
    return FalVideoProvider(FAL_VIDEO_MODELS[entry["video_model"]])


def check_attempt(manifest_path: Path, key: str, *, provider=None, force: bool = False) -> dict:
    """One free status check of a submitted attempt; persists the answer and returns the entry.

    Skipped (entry returned unchanged) when the attempt is finished, or - unless `force` - when a
    runner checked it within HEARTBEAT_FRESH_SECONDS. On COMPLETED the clip is downloaded and the
    estimated cost recorded as the actual cost; on FAILED the provider's error is recorded.
    """
    manifest = json.loads(Path(manifest_path).read_text())
    entry = manifest.get(key)
    if not isinstance(entry, dict) or not entry.get("provider_job_id"):
        raise AttemptCheckError(f"No submitted job recorded for {key}.")
    if not is_unfinished(entry) or (not force and heartbeat_fresh(entry)):
        return entry
    provider = provider or fal_provider_for(entry)
    job_id = entry["provider_job_id"]
    try:
        result = provider.get_job_status(job_id, entry.get("meta"))
    except VideoProviderError as e:  # transient (network, 5xx): recorded, the job stays unfinished
        return _update(manifest_path, key, status_checked_at=_now().isoformat(), last_check_error=str(e)[:500])
    checked = _now().isoformat()
    if result.status == ProviderJobState.PROCESSING:
        return _update(manifest_path, key, status_checked_at=checked, last_check_error=None,
                       provider_status=(result.meta or {}).get("provider_status") or "IN_PROGRESS")
    if result.status == ProviderJobState.FAILED:
        return _update(manifest_path, key, status="failed", provider_status="FAILED", failed_at=checked,
                       status_checked_at=checked, error=result.error_message, last_check_error=None)
    output = Path(entry.get("planned_output_path")
                  or raw_output_path(manifest_path, key, entry.get("video_model") or "model"))
    _update(manifest_path, key, provider_status="DOWNLOADING", status_checked_at=checked, last_check_error=None)
    provider.download_result(job_id, result.output_url, str(output))
    done = _now().isoformat()
    return _update(manifest_path, key, provider_status="COMPLETED", raw_video_path=str(output), completed_at=done,
                   status_checked_at=done, actual_cost_usd=entry.get("estimated_cost_usd"))
