"""Builds the studio snapshot: one payload with everything the studio UI renders.

Agent status is derived fresh from imported stage / approval / budget state and
the real job table on every call - never stored, never animated on a timer - so
the avatars can only ever show what production state actually says.
"""
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import quote

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.studio.actions import get_action, stage_intent
from app.studio.execution import execution_info
from app.studio.models import (
    ACTIVE_JOB_STATUSES,
    AgentStatus,
    ApprovalStatus,
    JobStatus,
    Severity,
    StageKind,
    StageStatus,
    StudioAgent,
    StudioApproval,
    StudioEvent,
    StudioJob,
    StudioProject,
    StudioStage,
)
from app.studio.rooms import ROOMS

_SEVERITY_RANK = {s: i for i, s in enumerate(Severity)}
_STAGE_ROOMS = ("continuity_office", "build_logic_workshop", "render_bay", "edit_suite")
PHASE_LABEL = {
    JobStatus.QUEUED: "Queued in studio",
    JobStatus.SUBMITTING: "Submitting",
    JobStatus.PROVIDER_QUEUED: "Queued at provider",
    JobStatus.GENERATING: "Generating",
    JobStatus.DOWNLOADING: "Downloading",
    JobStatus.SYNCING: "Syncing manifest",
    JobStatus.SUCCEEDED: "Complete",
    JobStatus.FAILED: "Failed",
}


def _iso(dt: datetime | None) -> str | None:
    if dt is None:
        return None
    return (dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)).isoformat()


def _naive(dt: datetime | None) -> datetime | None:
    return dt.astimezone(timezone.utc).replace(tzinfo=None) if dt and dt.tzinfo else dt


def media_url(path: str | None, exists: bool | None) -> str | None:
    return f"/studio/media?path={quote(path)}" if path and exists else None


def job_out(job: StudioJob, full_log: bool = False) -> dict:
    lines = (job.log or "").splitlines()
    return {
        "id": job.id, "stage_key": job.stage_key, "mode": job.mode, "action": job.action,
        "execution_mode": job.execution_mode, "is_paid": job.is_paid, "status": job.status.value,
        "phase_label": PHASE_LABEL[job.status], "active": job.status in ACTIVE_JOB_STATUSES,
        "expected_cost_usd": job.expected_cost_usd, "actual_cost_usd": job.actual_cost_usd,
        "provider_job_id": job.provider_job_id, "output_paths": job.output_paths or [],
        "error": job.error, "script_path": job.script_path,
        "created_at": _iso(job.created_at), "started_at": _iso(job.started_at),
        "phase_changed_at": _iso(job.phase_changed_at), "completed_at": _iso(job.completed_at),
        "log_tail": lines if full_log else lines[-14:],
    }


def _stage_out(s: StudioStage, project_slug: str, next_stage: StudioStage | None, last_job: StudioJob | None) -> dict:
    return {
        "key": s.key, "label": s.label, "order": s.order, "kind": s.kind.value, "room_id": s.room_id,
        "status": s.status.value, "script_path": s.script_path, "model": s.model,
        "duration_seconds": s.duration_seconds, "planned_cost_usd": s.planned_cost_usd,
        "estimated_cost_usd": s.estimated_cost_usd, "actual_cost_usd": s.actual_cost_usd,
        "completed_at": _iso(s.completed_at),
        "error_message": s.error_message, "provider_job_id": s.provider_job_id,
        "storyboard_checkpoint_path": s.storyboard_checkpoint_path,
        "previous_frame_path": s.previous_frame_path, "previous_frame_exists": s.previous_frame_exists,
        "previous_frame_url": media_url(s.previous_frame_path, s.previous_frame_exists),
        "latest_output_path": s.latest_output_path, "latest_output_exists": s.latest_output_exists,
        "latest_output_url": media_url(s.latest_output_path, s.latest_output_exists),
        "latest_output_name": Path(s.latest_output_path).name if s.latest_output_path else None,
        "approval_state": s.approval_state.value if s.approval_state else None,
        "continuity_severity": s.continuity_severity.value if s.continuity_severity else None,
        "continuity_note": s.continuity_note,
        "build_logic_severity": s.build_logic_severity.value if s.build_logic_severity else None,
        "build_logic_note": s.build_logic_note,
        "requires_human_review": s.requires_human_review,
        "launchable": get_action(project_slug, s.key) is not None,
        "intent": stage_intent(project_slug, s.key),
        "next_stage_key": next_stage.key if next_stage else None,
        "last_job": job_out(last_job) if last_job else None,
    }


def _event_out(e: StudioEvent, stage_keys: dict[str, str]) -> dict:
    return {
        "id": e.id, "type": e.type, "severity": e.severity.value, "message": e.message,
        "room_id": e.room_id,
        "stage_key": stage_keys.get(e.stage_id) if e.stage_id else (e.payload or {}).get("stage_key"),
        "requires_human_review": e.requires_human_review,
        "occurred_at": _iso(e.occurred_at or e.created_at),
    }


def _approval_out(a: StudioApproval, stage_keys: dict[str, str]) -> dict:
    return {
        "id": a.id, "title": a.title, "status": a.status.value, "room_id": a.room_id,
        "stage_key": stage_keys.get(a.stage_id) if a.stage_id else None,
        "estimated_cost_usd": a.estimated_cost_usd, "requires_human_review": a.requires_human_review,
        "decided_via": a.decided_via, "note": a.note, "decided_at": _iso(a.decided_at),
    }


class _State:
    """Everything agent derivation needs about one project, computed once."""

    def __init__(self, stages, approvals, jobs, budget):
        self.stages = stages
        self.by_key = {s.key: s for s in stages}
        self.budget = budget
        self.pending = [a for a in approvals if a.status == ApprovalStatus.PENDING]
        self.running = next((j for j in jobs if j.status in ACTIVE_JOB_STATUSES), None)
        self.last_job = {}
        for j in sorted(jobs, key=lambda j: _naive(j.created_at)):
            self.last_job[j.stage_key] = j
        done = [s for s in stages if s.status == StageStatus.COMPLETE]
        self.frontier = done[-1] if done else None
        self.next_pending = next((s for s in stages if s.status == StageStatus.PENDING), None)
        self.budget_block = None
        if self.next_pending and budget and budget.cap_usd is not None and self.next_pending.planned_cost_usd:
            if budget.spent_usd + self.next_pending.planned_cost_usd > budget.cap_usd + 1e-9:
                self.budget_block = (f"{self.next_pending.label} could cost up to ${self.next_pending.planned_cost_usd:.2f} "
                                     f"but only ${budget.cap_usd - budget.spent_usd:.2f} of the ${budget.cap_usd:.2f} "
                                     "cap remains - no paid launch is allowed.")

    def failed_job(self, stage: StudioStage) -> StudioJob | None:
        job = self.last_job.get(stage.key)
        if job is None or job.status != JobStatus.FAILED:
            return None
        if stage.status == StageStatus.COMPLETE and stage.completed_at and job.completed_at \
                and _naive(stage.completed_at) > _naive(job.completed_at):
            return None  # a later success superseded it
        return job


def _out(status, reason, task=None, action=None, needs_you=False, phase=None):
    return {"status": status.value, "status_reason": reason, "current_task": task, "next_action": action,
            "requires_human_review": needs_you, "job_phase": phase}


def _derive_agent(room_id: str, st: _State) -> dict:
    stages, budget, frontier, running = st.stages, st.budget, st.frontier, st.running
    mine = [s for s in stages if s.room_id == room_id]
    review_pending = frontier is not None and frontier.approval_state == ApprovalStatus.PENDING
    rejected = frontier is not None and frontier.approval_state == ApprovalStatus.REJECTED

    if room_id in ("sound_booth", "analytics_observatory"):
        return _out(AgentStatus.IDLE, "No data source yet - nothing in the pipeline feeds this room.")

    if room_id == "command_deck":
        if running is not None:
            label = st.by_key[running.stage_key].label
            return _out(AgentStatus.WORKING, f"Producing {label}", label, "Wait for the output, then review it.",
                        phase=PHASE_LABEL[running.status])
        if review_pending:
            return _out(AgentStatus.WAITING_FOR_APPROVAL, "Waiting on you: review the latest output.",
                        f"Review {frontier.label}", "Approve & Continue, Approve Only, Reject or Retry.", True)
        if rejected:
            return _out(AgentStatus.BLOCKED, f"You rejected {frontier.label}.", f"Decide on {frontier.label}",
                        "Retry it, or approve it anyway.", True)
        if all(s.status == StageStatus.COMPLETE for s in stages):
            return _out(AgentStatus.COMPLETE, "Every stage is complete.")
        return _out(AgentStatus.IDLE, "No review pending.", None,
                    f"Next stage: {st.next_pending.label}" if st.next_pending else None)

    if room_id == "screening_room":
        if review_pending:
            return _out(AgentStatus.WAITING_FOR_APPROVAL, "Waiting on you: output ready for review.",
                        f"Review {frontier.label}", "Watch it, then approve or reject.", True)
        if rejected:
            approval_note = frontier.label
            return _out(AgentStatus.BLOCKED, f"You rejected {approval_note} - it needs a retry or an override.",
                        f"Rejected: {frontier.label}", "Retry (paid, confirmed) or approve anyway.", True)
        return _out(AgentStatus.IDLE, "Nothing awaiting review.")

    if room_id == "finance_room":
        if budget is None:
            return _out(AgentStatus.IDLE, "No budget recorded.")
        cap = f"${budget.cap_usd:.2f}" if budget.cap_usd is not None else "no cap"
        summary = f"${budget.spent_usd:.2f} spent of {cap}"
        if budget.over_cap:
            return _out(AgentStatus.BLOCKED, f"Over cap: {summary}. No paid launch is allowed.", summary,
                        "Stop and review spend.", True)
        if st.budget_block:
            return _out(AgentStatus.BLOCKED, st.budget_block, summary, "Raise the cap or cut a stage.", True)
        if running is not None and running.is_paid:
            return _out(AgentStatus.WORKING, f"Paid job running: up to ${running.expected_cost_usd or 0:.2f}",
                        summary, "Records the real cost when the job finishes.", phase=PHASE_LABEL[running.status])
        return _out(AgentStatus.IDLE, summary, "Tracking spend against the cap",
                    f"${budget.planned_remaining_spend_usd:.2f} planned for remaining stages")

    if room_id == "library_archive":
        missing = [s for s in stages if s.latest_output_exists is False or s.previous_frame_exists is False]
        files = sum(bool(s.latest_output_path) for s in stages)
        if missing:
            return _out(AgentStatus.BLOCKED, f"{len(missing)} stage(s) reference files missing on disk.",
                        f"Indexing {files} recorded outputs", "Restore or regenerate the missing files.")
        return _out(AgentStatus.IDLE, f"{files} recorded outputs, all present on disk.", f"Indexing {files} recorded outputs")

    if room_id == "story_lab":
        shots = [s for s in stages if s.kind == StageKind.VIDEO]
        todo = [s for s in shots if s.status != StageStatus.COMPLETE]
        return _out(AgentStatus.IDLE, f"{len(shots)} shot prompts defined in the stage scripts.",
                    None, f"Prompt for {todo[0].label} is ready in {todo[0].script_path}" if todo else None)

    # Stage-owning rooms.
    if not mine:
        return _out(AgentStatus.IDLE, "No stages assigned in this project.")
    if running is not None and st.by_key.get(running.stage_key) in mine:
        label = st.by_key[running.stage_key].label
        verb = "Retrying" if running.mode == "retry" else "Generating"
        return _out(AgentStatus.WORKING, f"{verb} {label} ({running.execution_mode})", label,
                    "The output appears here for your review when it finishes.", phase=PHASE_LABEL[running.status])
    for s in mine:
        job = st.failed_job(s)
        if job is not None:
            return _out(AgentStatus.FAILED, (job.error or "Job failed.").splitlines()[0], s.label,
                        "Inspect the error, then retry when ready.", True)
    if frontier in mine and review_pending:
        nxt = next((s for s in stages if s.order > frontier.order), None)
        return _out(AgentStatus.WAITING_FOR_APPROVAL, "WAITING FOR YOUR APPROVAL - new output ready.",
                    f"Review {frontier.label}",
                    f"Approve & Continue launches {nxt.label}" if nxt else "Approve to finish the project.", True)
    if frontier in mine and rejected:
        return _out(AgentStatus.BLOCKED, "You rejected this output - it needs attention.", frontier.label,
                    "Retry (paid, confirmed) or approve anyway.", True)
    started = [s for s in mine if s.status == StageStatus.STARTED]
    if started:
        return _out(AgentStatus.BLOCKED, "Manifest shows a started job with no completion - a terminal run in "
                    "flight or interrupted.", started[0].label,
                    f"Check or recover job {started[0].provider_job_id or '(unknown id)'}", True)
    nxt = st.next_pending
    if nxt is not None and nxt in mine:
        if st.budget_block:
            return _out(AgentStatus.BLOCKED, st.budget_block, nxt.label, "Needs a budget decision.", True)
        cost = f" (up to ${nxt.planned_cost_usd:.2f})" if nxt.planned_cost_usd else ""
        if frontier is not None and frontier.approval_state == ApprovalStatus.APPROVED:
            return _out(AgentStatus.WAITING_FOR_APPROVAL, f"{frontier.label} is approved; waiting for your go.",
                        f"{nxt.label}{cost}", f"Approve & Continue on {frontier.label} launches this.", True)
        return _out(AgentStatus.WAITING_FOR_APPROVAL, "Next in line; waiting for your review of the stage before.",
                    f"{nxt.label}{cost}", f"Launches after you approve {frontier.label if frontier else 'the previous stage'}.")
    if all(s.status == StageStatus.COMPLETE for s in mine):
        return _out(AgentStatus.COMPLETE, f"All {len(mine)} stage(s) complete.")
    upcoming = next(s for s in mine if s.status != StageStatus.COMPLETE)
    done = sum(s.status == StageStatus.COMPLETE for s in mine)
    return _out(AgentStatus.IDLE, f"{done}/{len(mine)} stage(s) complete; upstream work comes first.",
                None, f"Later: {upcoming.label}")


def build_snapshot(db: Session, slug: str | None = None) -> dict:
    projects = db.scalars(select(StudioProject).order_by(StudioProject.slug)).all()
    project_list = [{"slug": p.slug, "name": p.name, "is_active": p.is_active, "source": p.source.value}
                    for p in projects]
    project = next((p for p in projects if p.slug == slug), None) if slug else \
        next((p for p in projects if p.is_active), projects[0] if projects else None)
    execution = execution_info()
    if project is None:
        return {"projects": project_list, "project": None, "execution": execution}

    stages = list(project.stages)
    stage_keys = {s.id: s.key for s in stages}
    approvals = db.scalars(select(StudioApproval).where(StudioApproval.project_id == project.id)).all()
    events = db.scalars(select(StudioEvent).where(StudioEvent.project_id == project.id)).all()
    events.sort(key=lambda e: _naive(e.occurred_at or e.created_at), reverse=True)
    jobs = db.scalars(select(StudioJob).where(StudioJob.project_id == project.id)).all()
    budget = project.budget
    st = _State(stages, approvals, jobs, budget)
    agents = {a.id: a for a in db.scalars(select(StudioAgent)).all()}

    rooms = []
    for room in ROOMS:
        agent = agents.get(room.id)
        room_events = [e for e in events if e.room_id == room.id and e.severity != Severity.INFO]
        worst = max((e.severity for e in room_events), key=_SEVERITY_RANK.get, default=None)
        rooms.append({
            "id": room.id, "name": room.name, "floor": room.floor, "col": room.col,
            "data_source": room.data_source,
            "stage_keys": [s.key for s in stages if s.room_id == room.id],
            "warning_count": len(room_events), "worst_severity": worst.value if worst else None,
            "agent": {"name": agent.name if agent else room.agent_name,
                      "role": agent.role if agent else room.agent_role,
                      **_derive_agent(room.id, st)},
        })

    jobs_sorted = sorted(jobs, key=lambda j: _naive(j.created_at), reverse=True)
    production_stage = project.production_stage
    if st.running is not None:
        production_stage = f"{PHASE_LABEL[st.running.status]}: {st.by_key[st.running.stage_key].label}"

    return {
        "projects": project_list,
        "execution": execution,
        "project": {
            "slug": project.slug, "name": project.name, "source": project.source.value,
            "is_demo": project.source.value != "manifest",
            "production_stage": production_stage, "current_stage_key": project.current_stage_key,
            "frontier_stage_key": st.frontier.key if st.frontier else None,
            "manifest_path": project.source_path,
            "last_imported_at": _iso(project.last_imported_at),
            "stages_complete": sum(s.status == StageStatus.COMPLETE for s in stages),
            "stages_total": len(stages),
        },
        "budget": None if budget is None else {
            "cap_usd": budget.cap_usd, "cap_source": budget.cap_source, "spent_usd": budget.spent_usd,
            "remaining_usd": budget.remaining_usd, "planned_remaining_spend_usd": budget.planned_remaining_spend_usd,
            "over_cap": budget.over_cap, "plan_exceeds_cap": budget.plan_exceeds_cap,
            "next_stage_block": st.budget_block,
        },
        "stages": [_stage_out(s, project.slug, next((n for n in stages if n.order > s.order), None),
                              st.last_job.get(s.key)) for s in stages],
        "rooms": rooms,
        "approvals": [_approval_out(a, stage_keys) for a in approvals],
        "events": [_event_out(e, stage_keys) for e in events[:60]],
        "jobs": [job_out(j) for j in jobs_sorted[:15]],
        "active_job": job_out(st.running) if st.running else None,
    }
