"""Builds the studio snapshot: one payload with everything the studio UI renders.

Agent status is derived fresh from imported stage / approval / budget state and
the real job table on every call - never stored, never animated on a timer - so
the avatars can only ever show what production state actually says.
"""
import json
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import quote

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.studio.actions import get_action, stage_intent
from app.studio.attempt_status import attempt_phase, orphan_job_entries
from app.studio.execution import execution_info
from app.studio.media_probe import AudioProbe, ffprobe_available, probe_audio
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


def _is_file(path: str | None) -> bool:
    return bool(path) and Path(path).is_file()


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


_MODEL_LABELS = {
    "alibaba/wan-3.0/image-to-video": ("Wan 3.0", "fal"),
    # Higgsfield entries carry "provider" in the manifest; this fallback only covers older records.
    "bytedance/seedance-2.5/image-to-video": ("Seedance 2.5", "Higgsfield"),
    "kling-video/o3/first-last-frame": ("Kling O3", "Higgsfield"),
    "fal-ai/kling-video/v3/standard/image-to-video": ("Kling v3 Standard", "fal"),
    "fal-ai/kling-video/v3/pro/image-to-video": ("Kling v3 Pro", "fal"),
    "fal-ai/veo3.1/fast/first-last-frame-to-video": ("Veo 3.1 Fast (first/last)", "fal"),
    "bytedance/seedance-2.0/image-to-video": ("Seedance 2.0", "fal"),
}


def _read_manifest(path: str | None) -> dict:
    try:
        return json.loads(Path(path).read_text()) if path else {}
    except (OSError, ValueError):
        return {}


def _attempt_out(key: str, entry: dict, is_primary: bool, verdicts: dict[str, dict]) -> dict:
    """One provider attempt of a stage, straight from its manifest entry (read-only, no provider calls)."""
    model = entry.get("video_model") or entry.get("image_model")
    model_label, inferred_provider = _MODEL_LABELS.get(model, (model, None))
    payload = entry.get("payload") or {}
    output = entry.get("raw_video_path") or entry.get("output_path")
    job_id = entry.get("provider_job_id")
    if entry.get("status") in ("cancelled", "failed"):
        status = entry["status"]
    elif entry.get("completed_at") and output:
        status = "complete"
    elif job_id:
        status = "in_flight"  # submitted; the runner (or a free recover) finishes it
    else:
        status = "not_started"
    verdict = verdicts.get(job_id) if job_id else None
    _, _, n = key.partition("__attempt")
    output_exists = _is_file(output)
    return {
        "key": key, "is_primary": is_primary,
        "label": "Primary result" if is_primary else f"Attempt {n}",
        "attempt_number": int(n) if n.isdigit() else None,
        # Live lifecycle, derived only from what is persisted in the manifest (survives restarts):
        # submitted | queued | generating | downloading | complete | failed | cancelled | not_started
        "phase": attempt_phase(entry, output_exists),
        "provider_status": entry.get("provider_status"),
        "status_checked_at": entry.get("status_checked_at"),
        "local_file_exists": output_exists,
        "ended_at": entry.get("completed_at") or entry.get("failed_at") or entry.get("cancelled_at"),
        "error": entry.get("error"),
        "last_check_error": entry.get("last_check_error"),
        "provider": {"higgsfield": "Higgsfield", "fal": "fal"}.get(entry.get("provider") or "", entry.get("provider"))
        or inferred_provider,
        "model": model, "model_label": model_label, "provider_job_id": job_id, "status": status,
        "estimated_cost_usd": entry.get("estimated_cost_usd"), "actual_cost_usd": entry.get("actual_cost_usd"),
        "submitted_at": entry.get("submitted_at"), "completed_at": entry.get("completed_at"),
        "resolution": payload.get("resolution") or entry.get("resolution"),
        "duration_seconds": payload.get("duration") or entry.get("duration_seconds"),
        "audio": (payload["generate_audio"] if "generate_audio" in payload else None),
        "output_path": output, "output_url": media_url(output, _is_file(output)),
        "start_frame_url": media_url(entry.get("start_frame_path"), _is_file(entry.get("start_frame_path"))),
        "end_frame_url": media_url(entry.get("end_frame_path"), _is_file(entry.get("end_frame_path"))),
        "verdict": None if verdict is None else {k: verdict.get(k) for k in
                                                 ("verdict", "failure_class", "continuity", "note", "findings",
                                                  "decided_at")},
        "note": entry.get("note"),
    }


def stage_attempts(manifest: dict, key: str) -> list[dict]:
    """The stage's primary result plus every archived / comparison attempt (<key>__attemptN).
    Empty when the stage has only its primary result, so ordinary stages are unchanged."""
    extra = sorted((k for k, v in manifest.items() if isinstance(v, dict) and k.startswith(f"{key}__attempt")),
                   key=lambda k: int("".join(ch for ch in k.partition("__attempt")[2] if ch.isdigit()) or 0))
    if not extra:
        return []
    verdicts = {a.get("provider_job_id"): a for a in manifest.get("proof_attempts", []) if a.get("provider_job_id")}
    primary = manifest.get(key)
    out = [_attempt_out(key, primary, True, verdicts)] if isinstance(primary, dict) else []
    return out + [_attempt_out(k, manifest[k], False, verdicts) for k in extra]


def _stage_out(s: StudioStage, project_slug: str, next_stage: StudioStage | None, last_job: StudioJob | None,
               manifest: dict | None = None) -> dict:
    return {
        "attempts": stage_attempts(manifest or {}, s.key),
        "key": s.key, "label": s.label, "order": s.order, "kind": s.kind.value, "room_id": s.room_id,
        "status": s.status.value, "script_path": s.script_path, "model": s.model,
        "duration_seconds": s.duration_seconds, "planned_cost_usd": s.planned_cost_usd,
        "estimated_cost_usd": s.estimated_cost_usd, "actual_cost_usd": s.actual_cost_usd,
        "completed_at": _iso(s.completed_at),
        "error_message": s.error_message, "provider_job_id": s.provider_job_id,
        "storyboard_checkpoint_path": s.storyboard_checkpoint_path,
        "storyboard_checkpoint_url": media_url(s.storyboard_checkpoint_path, _is_file(s.storyboard_checkpoint_path)),
        "target_frame_path": s.target_frame_path,
        "target_frame_url": media_url(s.target_frame_path, _is_file(s.target_frame_path)),
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


ASSEMBLY_AUDIO_NOTE = (
    "Final assembly keeps each clip's source audio, retimed with atempo by the same factor as its "
    "video (silence where a clip has none), as AAC 44.1 kHz stereo. Masters assembled before this "
    "change are silent."
)


def _probe_stage(s: StudioStage) -> AudioProbe:
    if not s.latest_output_exists:
        return AudioProbe(has_audio=None, error="file missing")
    return probe_audio(s.latest_output_path)


def audio_report(stages: list[StudioStage]) -> dict:
    """SOURCE AUDIO = audio streams already embedded in generated clips, read from the
    files with ffprobe. SOUND DESIGN = deliberate post-production audio (not built yet)."""
    clips = []
    for s in stages:
        if s.kind == StageKind.VIDEO and s.status == StageStatus.COMPLETE and s.latest_output_path:
            clips.append({"stage_key": s.key, "label": s.label, "file": Path(s.latest_output_path).name,
                          **_probe_stage(s).as_dict()})
    assembly = next((s for s in reversed(stages) if s.kind == StageKind.ASSEMBLY), None)
    final = None
    if assembly and assembly.status == StageStatus.COMPLETE and assembly.latest_output_path:
        final = {"stage_key": assembly.key, "label": assembly.label,
                 "file": Path(assembly.latest_output_path).name, **_probe_stage(assembly).as_dict()}
    with_audio = sum(c["has_audio"] is True for c in clips)
    if final is None:
        final_status = "not_assembled"
    elif final["has_audio"] is True:
        final_status = "preserved"
    elif final["has_audio"] is False:
        final_status = "discarded" if with_audio else "no_source_audio"
    else:
        final_status = "unknown"
    return {
        "ffprobe_available": ffprobe_available(),
        "clips": clips,
        "clips_total": len(clips),
        "clips_with_audio": with_audio,
        "clips_unknown": sum(c["has_audio"] is None for c in clips),
        "final": final,
        "final_status": final_status,
        "assembly_code_note": ASSEMBLY_AUDIO_NOTE,
        "sound_design_implemented": False,
    }


def _sound_booth(audio: dict) -> dict:
    if not audio["ffprobe_available"]:
        return _out(AgentStatus.IDLE, "ffprobe not found on PATH - source audio can't be inspected.")
    total, found, unknown = audio["clips_total"], audio["clips_with_audio"], audio["clips_unknown"]
    if total == 0:
        reason = "No generated clips yet - nothing to inspect."
    elif unknown == total:
        reason = f"Source audio could not be determined for {total} clip(s) (unreadable or missing files)."
    elif found == 0:
        reason = "Source audio detected: none"
    else:
        reason = f"Source audio detected: {found}/{total} generated clips"
    if unknown and unknown != total:
        reason += f" ({unknown} unreadable)"
    final_text = {
        "not_assembled": "Source audio - final cut not assembled yet",
        "preserved": "Source audio - preserved in the final cut",
        "discarded": "Source audio - discarded by an older assembly (re-run Final Assembly to keep it)",
        "no_source_audio": "Source audio - none to keep; final cut is silent",
        "unknown": "Source audio - final cut could not be checked",
    }[audio["final_status"]]
    return _out(AgentStatus.IDLE, reason, final_text,
                "Additional sound design (music, SFX, voice) - not implemented yet.")


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


def _derive_agent(room_id: str, st: _State, audio: dict | None = None) -> dict:
    stages, budget, frontier, running = st.stages, st.budget, st.frontier, st.running
    mine = [s for s in stages if s.room_id == room_id]
    review_pending = frontier is not None and frontier.approval_state == ApprovalStatus.PENDING
    rejected = frontier is not None and frontier.approval_state == ApprovalStatus.REJECTED

    if room_id == "sound_booth":
        return _sound_booth(audio if audio is not None else audio_report(stages))

    if room_id == "analytics_observatory":
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
    manifest = _read_manifest(project.source_path)  # provider attempts are read live, not imported
    if project.source_path:  # a submitted job recorded only in job.json still shows (never invisible)
        manifest = manifest | orphan_job_entries(Path(project.source_path), manifest)
    stage_keys = {s.id: s.key for s in stages}
    approvals = db.scalars(select(StudioApproval).where(StudioApproval.project_id == project.id)).all()
    events = db.scalars(select(StudioEvent).where(StudioEvent.project_id == project.id)).all()
    events.sort(key=lambda e: _naive(e.occurred_at or e.created_at), reverse=True)
    jobs = db.scalars(select(StudioJob).where(StudioJob.project_id == project.id)).all()
    budget = project.budget
    st = _State(stages, approvals, jobs, budget)
    agents = {a.id: a for a in db.scalars(select(StudioAgent)).all()}
    audio = audio_report(stages)

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
                      **_derive_agent(room.id, st, audio)},
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
                              st.last_job.get(s.key), manifest) for s in stages],
        "rooms": rooms,
        "approvals": [_approval_out(a, stage_keys) for a in approvals],
        "events": [_event_out(e, stage_keys) for e in events[:60]],
        "jobs": [job_out(j) for j in jobs_sorted[:15]],
        "audio": audio,
        "active_job": job_out(st.running) if st.running else None,
    }
