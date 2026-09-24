"""Studio decisions and launches: approve / reject / approve-and-continue / retry.

Safety rules enforced here (and again inside the pipeline itself):
- nothing launches unless execution is enabled (mock sandbox or live);
- a paid launch is refused if spent + the stage's cap would exceed the budget cap,
  with spent re-read from the manifest immediately before deciding;
- one active job per project, enforced by a process lock and a unique DB column;
- a repeated request_id (double click) returns the existing job, never a new one;
- every launch needs confirmed=True, sent only by the confirm panel.
"""
import threading
import uuid
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.studio.actions import get_action
from app.studio.execution import execution_info, mode_problems
from app.studio.importers.manifest_importer import import_project
from app.studio.importers.stage_maps import PROJECTS_BY_SLUG
from app.studio.jobs import JobRunner, _event
from app.studio.models import (
    ACTIVE_JOB_STATUSES,
    ApprovalStatus,
    JobStatus,
    Severity,
    StageStatus,
    StudioApproval,
    StudioEvent,
    StudioJob,
    StudioProject,
    StudioStage,
)

_LAUNCH_LOCK = threading.Lock()


class ControlError(Exception):
    def __init__(self, status_code: int, message: str, problems: list[str] | None = None):
        super().__init__(message)
        self.status_code, self.message, self.problems = status_code, message, problems or [message]


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _project(db: Session, slug: str) -> StudioProject:
    project = db.scalar(select(StudioProject).where(StudioProject.slug == slug))
    if project is None:
        raise ControlError(404, f"Studio project {slug} not found")
    return project


def _stage(project: StudioProject, key: str) -> StudioStage:
    stage = next((s for s in project.stages if s.key == key), None)
    if stage is None:
        raise ControlError(404, f"Stage {key} not found in {project.slug}")
    return stage


def _next_stage(project: StudioProject, stage: StudioStage) -> StudioStage | None:
    return next((s for s in project.stages if s.order > stage.order), None)


def active_job(db: Session, project_id: str) -> StudioJob | None:
    return db.scalar(select(StudioJob).where(StudioJob.project_id == project_id,
                                             StudioJob.status.in_(ACTIVE_JOB_STATUSES)))


def latest_job(db: Session, project_id: str, stage_key: str) -> StudioJob | None:
    return db.scalar(select(StudioJob).where(StudioJob.project_id == project_id, StudioJob.stage_key == stage_key)
                     .order_by(StudioJob.created_at.desc()).limit(1))


def record_decision(db: Session, slug: str, key: str, decision: str, note: str | None = None) -> StudioApproval:
    if decision not in ("approve", "reject"):
        raise ControlError(400, "decision must be 'approve' or 'reject'")
    project = _project(db, slug)
    stage = _stage(project, key)
    if stage.status != StageStatus.COMPLETE:
        raise ControlError(409, f"{stage.label} has no finished output to {decision} yet.")

    dedupe_key = f"{slug}:{key}:gate"
    approval = db.scalar(select(StudioApproval).where(StudioApproval.dedupe_key == dedupe_key))
    if approval is None:
        approval = StudioApproval(dedupe_key=dedupe_key, project_id=project.id, stage_id=stage.id,
                                  room_id="screening_room", title=f"Review {stage.label}")
        db.add(approval)
    status = ApprovalStatus.APPROVED if decision == "approve" else ApprovalStatus.REJECTED
    note = (note or "").strip() or None
    approval.status, approval.decided_via, approval.decided_at = status, "studio", _utcnow()
    approval.note, approval.output_completed_at = note, stage.completed_at
    stage.approval_state = status
    stage.requires_human_review = status == ApprovalStatus.REJECTED

    verb = "Approved" if status == ApprovalStatus.APPROVED else "Rejected"
    db.add(StudioEvent(
        dedupe_key=f"{slug}:{key}:decision:{uuid.uuid4().hex}", project_id=project.id, stage_id=stage.id,
        room_id=stage.room_id, agent_id=stage.room_id, type="decision",
        severity=Severity.INFO if status == ApprovalStatus.APPROVED else Severity.MEDIUM,
        requires_human_review=status == ApprovalStatus.REJECTED, occurred_at=_utcnow(),
        message=f"You {verb.lower()} {stage.label}{f': {note}' if note else ''}",
        payload={"decision": decision, "note": note},
    ))
    db.commit()
    return approval


def launch_plan(db: Session, slug: str, key: str, mode: str, *, resync: bool = True) -> dict:
    """Everything the confirm panel shows, plus whether the launch is allowed and why not."""
    if mode not in ("continue", "retry"):
        raise ControlError(400, "mode must be 'continue' or 'retry'")
    project = _project(db, slug)
    if resync:  # re-read the manifest so spend and stage state are current
        import_project(db, PROJECTS_BY_SLUG[slug])
        db.commit()
        db.refresh(project)
    stage = _stage(project, key)
    target = _next_stage(project, stage) if mode == "continue" else stage
    problems: list[str] = list(mode_problems())
    warnings: list[str] = []

    running = active_job(db, project.id)
    if running is not None:
        problems.append(f"A job is already running for this project ({running.stage_key}, {running.status.value}).")

    action = get_action(slug, target.key) if target else None
    if target is None:
        problems.append(f"{stage.label} is the last stage - there is nothing after it to launch.")
    elif action is None:
        problems.append(f"{target.label} can't be launched from the studio yet - run {target.script_path} from the terminal.")

    if target is not None and mode == "continue":
        if stage.status != StageStatus.COMPLETE:
            problems.append(f"{stage.label} has no finished output to approve yet.")
        if target.status == StageStatus.COMPLETE:
            problems.append(f"{target.label} has already been generated - use Retry on it instead.")
        elif target.status == StageStatus.STARTED:
            problems.append(f"The manifest shows {target.label} started but never completed (a terminal run in flight "
                            "or interrupted). Check it before launching again.")
    if target is not None and mode == "retry":
        last = latest_job(db, project.id, target.key)
        failed_here = last is not None and last.status == JobStatus.FAILED
        if target.status == StageStatus.PENDING:
            problems.append(f"{target.label} has never run - approve the stage before it and continue instead.")
        elif target.status == StageStatus.STARTED and not failed_here:
            problems.append(f"The manifest shows {target.label} started but never completed, and no failed studio job "
                            "explains it. It may still be running from the terminal - check before retrying.")
        downstream = [s for s in project.stages if s.order > target.order and s.status != StageStatus.PENDING]
        if downstream:
            problems.append(f"Later stages ({', '.join(s.label for s in downstream)}) are already built on this "
                            "output - retrying it would break the chain.")
        if target.status == StageStatus.STARTED and target.provider_job_id:
            warnings.append(f"The failed attempt had provider job {target.provider_job_id}; it may already be "
                            f"billed. Consider `python -m scripts.recover_fal_video_job {target.provider_job_id}` first.")
        if target.status == StageStatus.COMPLETE:
            warnings.append("The current output and its manifest entry are kept as an archived attempt, "
                            "and its spend stays counted.")

    budget = project.budget
    paid = bool(action and action.paid)
    estimate = (target.planned_cost_usd or 0.0) if (target and paid) else 0.0
    spent = budget.spent_usd if budget else 0.0
    cap = budget.cap_usd if budget else None
    remaining = round(cap - spent, 4) if cap is not None else None
    after = round(remaining - estimate, 4) if remaining is not None else None
    if paid and cap is None:
        problems.append("No budget cap is recorded for this project, so no paid launch is allowed.")
    elif paid and spent + estimate > cap + 1e-9:
        problems.append(f"Budget: {target.label} could cost up to ${estimate:.2f}, but only ${remaining:.2f} of the "
                        f"${cap:.2f} cap remains (${spent:.2f} spent).")

    return {
        "mode": mode,
        "reviewed_stage": {"key": stage.key, "label": stage.label, "status": stage.status.value,
                           "approval_state": stage.approval_state.value if stage.approval_state else None},
        "target_stage": None if target is None else {
            "key": target.key, "label": target.label, "room_id": target.room_id, "script_path": target.script_path},
        "action": action.kind.value if action else None,
        "paid": paid,
        "estimated_cost_usd": estimate,
        "spent_usd": spent,
        "cap_usd": cap,
        "remaining_usd": remaining,
        "remaining_after_usd": after,
        "allowed": not problems,
        "problems": problems,
        "warnings": warnings,
        "execution": execution_info(),
    }


def launch(db: Session, runner: JobRunner, slug: str, key: str, *, mode: str, request_id: str,
           confirmed: bool, approve_first: bool = False, note: str | None = None) -> StudioJob:
    if not request_id:
        raise ControlError(400, "request_id is required")
    existing = db.scalar(select(StudioJob).where(StudioJob.request_id == request_id))
    if existing is not None:  # the same confirm click arriving twice
        return existing
    if not confirmed:
        raise ControlError(400, "Launching requires explicit confirmation.")

    if mode == "continue":
        stage = _stage(_project(db, slug), key)
        if approve_first and stage.approval_state != ApprovalStatus.APPROVED:
            record_decision(db, slug, key, "approve", note)
        elif stage.approval_state != ApprovalStatus.APPROVED:
            raise ControlError(409, f"{stage.label} must be approved before the next stage can run.")

    with _LAUNCH_LOCK:
        existing = db.scalar(select(StudioJob).where(StudioJob.request_id == request_id))
        if existing is not None:
            return existing
        plan = launch_plan(db, slug, key, mode)
        if not plan["allowed"]:
            code = 402 if any(p.startswith("Budget") for p in plan["problems"]) else 409
            raise ControlError(code, plan["problems"][0], plan["problems"])
        project = _project(db, slug)
        target = plan["target_stage"]
        job = StudioJob(
            project_id=project.id, stage_key=target["key"], mode=mode, action=plan["action"],
            script_path=target["script_path"], execution_mode=plan["execution"]["mode"], is_paid=plan["paid"],
            status=JobStatus.QUEUED, active_lock=project.id, request_id=request_id,
            expected_cost_usd=plan["estimated_cost_usd"],
        )
        db.add(job)
        try:
            db.flush()
        except IntegrityError:
            db.rollback()
            raise ControlError(409, "Another job for this project was started at the same moment.") from None
        spend = f"up to ${plan['estimated_cost_usd']:.2f}" if plan["paid"] else "no spend"
        _event(db, job, project, "started",
               f"{'Retrying' if mode == 'retry' else 'Launched'} {target['label']} "
               f"({plan['execution']['mode']}, {spend})")
        db.commit()
    runner.submit(job.id)
    return job
