"""Background execution of studio jobs.

One worker thread per job calls the real pipeline function (app.studio.execution),
recording every real phase change, log line, cost and produced file on the
StudioJob row, then re-imports the project's manifest so the new output shows up
in the studio. A job runs exactly once: there is no automatic retry anywhere.
"""
import threading
import uuid
from concurrent.futures import Future, ThreadPoolExecutor
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from app.studio.actions import get_action
from app.studio.execution import run_action
from app.studio.importers.manifest_importer import import_project
from app.studio.importers.stage_maps import PROJECTS_BY_SLUG
from app.studio.models import ACTIVE_JOB_STATUSES, JobStatus, Severity, StudioEvent, StudioJob, StudioProject

_PHASES = {
    "submitting": JobStatus.SUBMITTING,
    "provider_queued": JobStatus.PROVIDER_QUEUED,
    "generating": JobStatus.GENERATING,
    "downloading": JobStatus.DOWNLOADING,
}
_MAX_LOG_CHARS = 60_000


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _event(db: Session, job: StudioJob, project: StudioProject, suffix: str, message: str,
           severity: Severity = Severity.INFO, needs_you: bool = False) -> None:
    from app.studio.importers.stage_maps import PROJECTS_BY_SLUG as defs

    room = next((s.room_id for s in defs[project.slug].stages if s.key == job.stage_key), None)
    db.add(StudioEvent(
        dedupe_key=f"{project.slug}:job:{job.id}:{suffix}", project_id=project.id, room_id=room, agent_id=room,
        type=f"job_{suffix}", severity=severity, message=message, requires_human_review=needs_you,
        payload={"job_id": job.id, "stage_key": job.stage_key}, occurred_at=_utcnow(),
    ))


class JobRunner:
    def __init__(self, session_factory: sessionmaker, max_workers: int = 2):
        self._session_factory = session_factory
        self._executor = ThreadPoolExecutor(max_workers=max_workers, thread_name_prefix="studio-job")
        self._futures: dict[str, Future] = {}

    def submit(self, job_id: str) -> Future:
        future = self._executor.submit(self._run, job_id)
        self._futures[job_id] = future
        return future

    def wait(self, job_id: str, timeout: float = 60.0) -> None:
        future = self._futures.get(job_id)
        if future is not None:
            future.result(timeout=timeout)

    def recover_stale_jobs(self) -> int:
        """At startup: any job still marked active was cut off by a restart. Mark it
        failed (never re-run it) and release its lock."""
        with self._session_factory() as db:
            stale = db.scalars(select(StudioJob).where(StudioJob.status.in_(ACTIVE_JOB_STATUSES))).all()
            for job in stale:
                job.status, job.active_lock, job.completed_at = JobStatus.FAILED, None, _utcnow()
                job.error = ("The backend restarted while this job was running. It was NOT re-run. If a provider "
                             "job id is shown, check it (python -m scripts.recover_fal_video_job <id>) before retrying.")
            db.commit()
            return len(stale)

    def _run(self, job_id: str) -> None:
        db = self._session_factory()
        lock = threading.Lock()
        try:
            job = db.get(StudioJob, job_id)
            project = db.get(StudioProject, job.project_id)
            action = get_action(project.slug, job.stage_key)
            job.started_at = job.phase_changed_at = _utcnow()
            db.commit()

            def log(line: str = "") -> None:
                with lock:
                    job.log = (job.log + str(line).rstrip("\n") + "\n")[-_MAX_LOG_CHARS:]
                    db.commit()

            def on_phase(phase: str, detail: str | None) -> None:
                status = _PHASES.get(phase)
                with lock:
                    if phase == "provider_queued" and detail and not job.provider_job_id:
                        job.provider_job_id = detail
                    if status is not None and job.status != status:
                        job.status, job.phase_changed_at = status, _utcnow()
                    db.commit()

            try:
                if action is None:
                    raise RuntimeError(f"{job.stage_key} has no studio action.")
                result = run_action(action, retry=job.mode == "retry", on_phase=on_phase, log=log)
            except Exception as e:  # noqa: BLE001 - every failure is recorded, none is retried
                db.rollback()
                job = db.get(StudioJob, job_id)
                job.status, job.error, job.completed_at, job.active_lock = JobStatus.FAILED, str(e), _utcnow(), None
                _event(db, job, project, "failed", f"{action.stage.label if action else job.stage_key} failed: {e}",
                       Severity.HIGH, needs_you=True)
                db.commit()
                self._resync(db, project)
                return

            job.status, job.phase_changed_at = JobStatus.SYNCING, _utcnow()
            job.actual_cost_usd = result.get("actual_cost_usd")
            job.provider_job_id = job.provider_job_id or result.get("provider_job_id")
            job.output_paths = [result["output_path"]] if result.get("output_path") else []
            db.commit()
            self._resync(db, project)
            job.status, job.completed_at, job.active_lock = JobStatus.SUCCEEDED, _utcnow(), None
            cost = f" (${job.actual_cost_usd:.2f})" if job.actual_cost_usd is not None else ""
            _event(db, job, project, "succeeded", f"{action.stage.label} generated{cost} - ready for your review")
            db.commit()
        finally:
            db.close()

    @staticmethod
    def _resync(db: Session, project: StudioProject) -> None:
        try:
            import_project(db, PROJECTS_BY_SLUG[project.slug])
            db.commit()
        except Exception:  # noqa: BLE001 - a failed re-sync must not mask the job result
            db.rollback()


def new_request_id() -> str:
    return uuid.uuid4().hex


_runner: JobRunner | None = None


def get_runner() -> JobRunner:
    global _runner
    if _runner is None:
        from app.db import SessionLocal

        _runner = JobRunner(SessionLocal)
    return _runner
