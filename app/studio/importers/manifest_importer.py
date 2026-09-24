"""Mirror real FORMA production manifests into the studio_* tables.

READ-ONLY with respect to the pipeline: manifests, job-state files and media
are only ever opened for reading (bytes are read once, hashed, then parsed).
Nothing under the data directory is created, modified or deleted.

Idempotent: stages are upserted by (project, key), approvals and events by a
deterministic dedupe_key, so re-running the import never duplicates rows.
Events are write-once history; a stage's live flags (e.g. latest_output_exists)
always reflect the latest import.

Approval inference: every pipeline script asks "Have you reviewed and approved
<upstream output>?" before it spends, so a completed stage whose downstream
stage has since started is recorded as approved via the pipeline gate, and the
newest completed stage with nothing downstream is a pending human review.
"""
import hashlib
import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import settings
from app.studio.importers.stage_maps import PROJECTS, PROJECTS_BY_SLUG, ProjectDef, StageDef
from app.studio.models import (
    ApprovalStatus,
    ProjectSource,
    Severity,
    StageStatus,
    StudioAgent,
    StudioApproval,
    StudioBudget,
    StudioEvent,
    StudioProject,
    StudioStage,
)
from app.studio.rooms import ROOMS



def default_data_dir() -> Path:
    """The data root the studio mirrors: ./data, or the sandbox copy in mock mode."""
    return settings.studio_data_path


# Manifest fields that hold a stage's newest output / its conditioning frame, in priority order.
_OUTPUT_FIELDS = ("raw_video_path", "output_path", "final_visual_master_path", "rough_assembly_path")
_PREVIOUS_FRAME_FIELDS = ("start_frame_path", "source_frame_path")
# Manifest entries that are pipeline bookkeeping, not stages.
_META_KEYS = {"proof_gate"}


@dataclass
class ImportResult:
    slug: str
    found: bool
    error: str | None = None
    stages_complete: int = 0
    stages_total: int = 0
    events_created: int = 0
    approvals_created: int = 0
    approvals_updated: int = 0
    spent_usd: float = 0.0
    cap_usd: float | None = None
    warnings: list[str] = field(default_factory=list)


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _parse_ts(value) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None


def _first(entry: dict, fields: tuple[str, ...]) -> str | None:
    for f in fields:
        if isinstance(entry.get(f), str) and entry[f]:
            return entry[f]
    return None


def _exists(path: str | None) -> bool | None:
    return None if path is None else Path(path).is_file()


def _read_job_id(project_dir: Path, stage_def: StageDef) -> str | None:
    if not stage_def.job_state_file:
        return None
    path = project_dir / stage_def.job_state_file
    try:
        data = json.loads(path.read_bytes())
    except (OSError, ValueError):
        return None
    job_id = data.get("provider_job_id") if isinstance(data, dict) else None
    return job_id if isinstance(job_id, str) else None


def _naive(dt: datetime) -> datetime:
    """SQLite drops tzinfo on read; compare timestamps as naive UTC."""
    return dt.astimezone(timezone.utc).replace(tzinfo=None) if dt.tzinfo else dt


def _cost(value) -> float | None:
    return float(value) if isinstance(value, (int, float)) and not isinstance(value, bool) else None


class _Recorder:
    """Insert-if-absent helpers keyed by dedupe_key, counting what was actually new."""

    def __init__(self, db: Session, project: StudioProject, result: ImportResult):
        self.db, self.project, self.result = db, project, result

    def event(self, key: str, *, type: str, message: str, severity: Severity = Severity.INFO,
              stage: StudioStage | None = None, room_id: str | None = None, payload: dict | None = None,
              requires_human_review: bool = False, occurred_at: datetime | None = None) -> None:
        dedupe_key = f"{self.project.slug}:{key}"
        if self.db.scalar(select(StudioEvent.id).where(StudioEvent.dedupe_key == dedupe_key)):
            return
        room = room_id or (stage.room_id if stage else None)
        self.db.add(StudioEvent(
            dedupe_key=dedupe_key, project_id=self.project.id, stage_id=stage.id if stage else None,
            room_id=room, agent_id=room, type=type, severity=severity, message=message, payload=payload,
            requires_human_review=requires_human_review, occurred_at=occurred_at,
        ))
        self.result.events_created += 1
        if severity != Severity.INFO:
            self.result.warnings.append(message)


def import_project(db: Session, pdef: ProjectDef, data_dir: Path | None = None) -> ImportResult:
    data_dir = data_dir or default_data_dir()
    result = ImportResult(slug=pdef.slug, found=False, stages_total=len(pdef.stages))
    project_dir = data_dir / pdef.slug
    manifest_path = project_dir / "manifest.json"

    try:
        raw = manifest_path.read_bytes()
    except FileNotFoundError:
        result.error = f"No manifest at {manifest_path} - skipped."
        return result
    except OSError as e:
        result.error = f"Could not read {manifest_path}: {e}"
        return result
    try:
        manifest = json.loads(raw)
        if not isinstance(manifest, dict):
            raise ValueError("top level is not an object")
    except ValueError as e:
        result.error = f"Manifest {manifest_path} is not valid JSON ({e}) - skipped, nothing changed."
        return result
    result.found = True

    project = db.scalar(select(StudioProject).where(StudioProject.slug == pdef.slug))
    if project is None:
        project = StudioProject(slug=pdef.slug, name=pdef.name, source=ProjectSource.MANIFEST,
                                source_path=str(manifest_path))
        db.add(project)
        db.flush()
    project.name = pdef.name
    project.source_path = str(manifest_path)
    project.manifest_sha256 = hashlib.sha256(raw).hexdigest()
    project.last_imported_at = _utcnow()
    rec = _Recorder(db, project, result)

    # --- stages -------------------------------------------------------------
    existing = {s.key: s for s in project.stages}
    stages: list[StudioStage] = []
    for order, sdef in enumerate(pdef.stages):
        entry = manifest.get(sdef.key)
        entry = entry if isinstance(entry, dict) else None
        stage = existing.get(sdef.key)
        if stage is None:
            stage = StudioStage(project_id=project.id, key=sdef.key)
            db.add(stage)
            project.stages.append(stage)
        stage.label, stage.order, stage.kind, stage.room_id = sdef.label, order, sdef.kind, sdef.room_id
        stage.script_path, stage.planned_cost_usd = sdef.script, sdef.planned_cost_usd

        if entry is None:
            stage.status = StageStatus.PENDING
            entry = {}
        elif _parse_ts(entry.get("completed_at")) is not None:
            stage.status = StageStatus.COMPLETE
        else:
            stage.status = StageStatus.STARTED

        stage.model = entry.get("video_model") or entry.get("image_model")
        stage.duration_seconds = _cost(entry.get("duration_seconds") or entry.get("final_duration_seconds"))
        stage.estimated_cost_usd = _cost(entry.get("estimated_cost_usd"))
        stage.actual_cost_usd = _cost(entry.get("actual_cost_usd"))
        stage.completed_at = _parse_ts(entry.get("completed_at"))
        stage.provider_job_id = _read_job_id(project_dir, sdef) if stage.status != StageStatus.PENDING else None
        stage.latest_output_path = _first(entry, _OUTPUT_FIELDS)
        stage.latest_output_exists = _exists(stage.latest_output_path)
        stage.previous_frame_path = _first(entry, _PREVIOUS_FRAME_FIELDS)
        stage.previous_frame_exists = _exists(stage.previous_frame_path)
        stage.target_frame_path = _first(entry, ("end_frame_path",))
        stage.storyboard_checkpoint_path = str(project_dir / sdef.storyboard_ref) if sdef.storyboard_ref else None
        # No continuity/build-logic review exists in the pipeline yet: those stay null
        # until real agents produce them.
        stage.error_message = None
        stage.requires_human_review = False
        stages.append(stage)
    db.flush()

    for stage in stages:
        if stage.status == StageStatus.COMPLETE:
            cost = f"${stage.actual_cost_usd:.2f}" if stage.actual_cost_usd is not None else "no spend"
            rec.event(f"{stage.key}:completed", type="stage_completed", stage=stage,
                      occurred_at=stage.completed_at, payload={"actual_cost_usd": stage.actual_cost_usd},
                      message=f"{stage.label} completed ({cost}{', ' + stage.model if stage.model else ''})")
        if stage.status == StageStatus.STARTED:
            stage.requires_human_review = True
            recover = (f" Recover with: python -m scripts.recover_fal_video_job {stage.provider_job_id}"
                       if stage.provider_job_id else "")
            stage.error_message = "Manifest entry was written but never completed: job in flight or interrupted."
            rec.event(f"{stage.key}:started_incomplete", type="warning", severity=Severity.HIGH, stage=stage,
                      requires_human_review=True, payload={"provider_job_id": stage.provider_job_id},
                      message=f"{stage.label} started but never completed - in flight or interrupted.{recover}")
        if stage.status == StageStatus.COMPLETE and stage.latest_output_path and not stage.latest_output_exists:
            rec.event(f"{stage.key}:missing_output:{stage.latest_output_path}", type="warning",
                      severity=Severity.MEDIUM, stage=stage, room_id="library_archive",
                      message=f"{stage.label}: recorded output file is missing on disk ({stage.latest_output_path})")
        if stage.previous_frame_path and not stage.previous_frame_exists:
            rec.event(f"{stage.key}:missing_previous_frame:{stage.previous_frame_path}", type="warning",
                      severity=Severity.LOW, stage=stage, room_id="library_archive",
                      message=f"{stage.label}: recorded start/source frame is missing ({stage.previous_frame_path})")

    known = {s.key for s in pdef.stages}
    for key, value in manifest.items():
        base_key, _, attempt = key.partition("__attempt")
        if isinstance(value, dict) and attempt and base_key in known:
            cost = _cost(value.get("actual_cost_usd"))
            rec.event(f"archived:{key}", type="note", room_id="library_archive",
                      occurred_at=_parse_ts(value.get("archived_at")),
                      message=f"Earlier attempt {attempt} of '{base_key}' kept as an archived record"
                              f"{f' (${cost:.2f}, still counted in spend)' if cost else ''}.")
            continue
        if isinstance(value, dict) and key not in known and key not in _META_KEYS:
            rec.event(f"untracked:{key}", type="warning", severity=Severity.LOW, room_id="command_deck",
                      message=f"Manifest entry '{key}' is not in the studio's stage map - not shown as a stage.")
    for i, note in enumerate(pdef.notes):
        rec.event(f"note:{i}", type="note", room_id="finance_room", message=note)

    # --- approvals (the pipeline's human review gates) ------------------------
    started_idx = [i for i, s in enumerate(stages) if s.status != StageStatus.PENDING]
    last_started = max(started_idx, default=-1)
    for i, stage in enumerate(stages):
        if stage.status != StageStatus.COMPLETE:
            stage.approval_state = ApprovalStatus.PENDING if i == last_started + 1 and last_started >= 0 else None
            continue
        nxt = stages[i + 1] if i + 1 < len(stages) else None
        downstream_ran = i < last_started
        output_name = Path(stage.latest_output_path).name if stage.latest_output_path else stage.label
        title = f"Review {output_name}"
        if nxt is not None:
            cost = f" (${nxt.planned_cost_usd:.2f})" if nxt.planned_cost_usd else ""
            title += f" and authorize {nxt.label}{cost}"
        dedupe_key = f"{project.slug}:{stage.key}:gate"
        approval = db.scalar(select(StudioApproval).where(StudioApproval.dedupe_key == dedupe_key))
        if approval is None:
            approval = StudioApproval(
                dedupe_key=dedupe_key, project_id=project.id, stage_id=stage.id, room_id="screening_room",
                title=title, status=ApprovalStatus.APPROVED if downstream_ran else ApprovalStatus.PENDING,
                estimated_cost_usd=nxt.planned_cost_usd if nxt else None, requires_human_review=True,
                output_completed_at=stage.completed_at,
            )
            if downstream_ran:
                approval.decided_via = "pipeline"
                approval.note = "Inferred: the next stage ran after the pipeline's review gate."
            db.add(approval)
            result.approvals_created += 1
            if not downstream_ran:
                db.flush()
                rec.event(f"{stage.key}:approval_requested", type="approval_requested", stage=stage,
                          room_id="screening_room", requires_human_review=True, occurred_at=stage.completed_at,
                          message=f"Waiting on you: {title}")
        elif (approval.output_completed_at is not None and stage.completed_at is not None
              and _naive(approval.output_completed_at) != _naive(stage.completed_at)):
            # A newer attempt of this stage exists (e.g. after a retry): the earlier
            # decision was about a different output, so the gate opens again.
            previous = approval.status.value
            approval.status, approval.decided_via, approval.decided_at = ApprovalStatus.PENDING, None, None
            approval.note = f"New attempt produced; the previous attempt was {previous}."
            approval.title, approval.output_completed_at = title, stage.completed_at
            approval.estimated_cost_usd = nxt.planned_cost_usd if nxt else None
            result.approvals_updated += 1
            rec.event(f"{stage.key}:new_attempt:{stage.completed_at.isoformat()}", type="approval_requested",
                      stage=stage, room_id="screening_room", requires_human_review=True,
                      occurred_at=stage.completed_at, message=f"Waiting on you: new attempt - {title}")
        elif approval.decided_via != "studio":
            approval.output_completed_at = approval.output_completed_at or stage.completed_at
            approval.title = title
            approval.estimated_cost_usd = nxt.planned_cost_usd if nxt else None
            if downstream_ran and approval.status == ApprovalStatus.PENDING:
                approval.status, approval.decided_via = ApprovalStatus.APPROVED, "pipeline"
                approval.note = "Inferred: the next stage ran after the pipeline's review gate."
                approval.decided_at = _utcnow()
                result.approvals_updated += 1
                rec.event(f"{stage.key}:approval_inferred", type="decision", stage=stage,
                          room_id="screening_room", message=f"Approved via pipeline gate: {title}")
        stage.approval_state = approval.status
        stage.requires_human_review = approval.status in (ApprovalStatus.PENDING, ApprovalStatus.REJECTED)

    # --- budget -----------------------------------------------------------------
    # Same rule as the pipeline's own spent_so_far(): every manifest entry's actual cost.
    spent = round(sum(_cost(v.get("actual_cost_usd")) or 0.0 for v in manifest.values() if isinstance(v, dict)), 4)
    manifest_cap = _cost(manifest.get("budget_cap_usd"))
    cap = manifest_cap if manifest_cap is not None else pdef.cap_usd
    cap_source = "manifest budget_cap_usd" if manifest_cap is not None else pdef.cap_source
    planned = round(sum(
        (s.estimated_cost_usd if s.status == StageStatus.STARTED and s.estimated_cost_usd is not None
         else s.planned_cost_usd or 0.0)
        for s in stages if s.status in (StageStatus.PENDING, StageStatus.STARTED)
    ), 4)
    budget = project.budget or StudioBudget(project_id=project.id)
    project.budget = budget
    budget.cap_usd, budget.cap_source, budget.spent_usd = cap, cap_source, spent
    budget.remaining_usd = round(cap - spent, 4) if cap is not None else None
    budget.planned_remaining_spend_usd = planned
    budget.over_cap = cap is not None and spent > cap
    budget.plan_exceeds_cap = cap is not None and spent + planned > cap + 1e-9
    result.spent_usd, result.cap_usd = spent, cap

    if budget.over_cap:
        rec.event(f"budget:over_cap:{spent}", type="warning", severity=Severity.CRITICAL, room_id="finance_room",
                  requires_human_review=True, message=f"Spend ${spent:.2f} exceeds the ${cap:.2f} cap.")
    elif budget.plan_exceeds_cap:
        rec.event(f"budget:plan_exceeds_cap:{planned}", type="warning", severity=Severity.MEDIUM,
                  room_id="finance_room",
                  message=f"Remaining planned stages (${planned:.2f}) exceed the remaining budget "
                          f"(${budget.remaining_usd:.2f}).")
    next_stage = next((s for s in stages if s.status == StageStatus.PENDING), None)
    if (next_stage and budget.remaining_usd is not None and next_stage.planned_cost_usd
            and next_stage.planned_cost_usd > budget.remaining_usd):
        rec.event(f"{next_stage.key}:blocked_budget", type="warning", severity=Severity.HIGH, stage=next_stage,
                  requires_human_review=True, room_id="finance_room",
                  message=f"{next_stage.label} is blocked: its ${next_stage.planned_cost_usd:.2f} cap exceeds the "
                          f"${budget.remaining_usd:.2f} remaining.")

    # --- project stage summary --------------------------------------------------
    current = next((s for s in stages if s.status != StageStatus.COMPLETE), None)
    frontier = next((s for s in reversed(stages) if s.status == StageStatus.COMPLETE), None)
    awaiting = frontier is not None and frontier.approval_state == ApprovalStatus.PENDING
    rejected = frontier is not None and frontier.approval_state == ApprovalStatus.REJECTED
    project.current_stage_key = current.key if current else None
    if current is None:
        project.production_stage = "Complete - final cut awaiting review" if awaiting else "Complete"
    elif current.status == StageStatus.STARTED:
        project.production_stage = f"{current.label} - in flight or interrupted"
    elif rejected:
        project.production_stage = f"You rejected {frontier.label} - retry it or approve anyway"
    elif awaiting:
        project.production_stage = f"Awaiting review of {frontier.label}; next: {current.label}"
    else:
        project.production_stage = f"Next: {current.label}"

    result.stages_complete = sum(s.status == StageStatus.COMPLETE for s in stages)
    return result


def ensure_agents(db: Session) -> None:
    """One agent row per room. Existing rows keep their status; only identity fields are refreshed."""
    for room in ROOMS:
        agent = db.get(StudioAgent, room.id)
        if agent is None:
            db.add(StudioAgent(id=room.id, room_id=room.id, name=room.agent_name, role=room.agent_role,
                               status_reason=None if room.data_source else "No data source yet"))
        else:
            agent.name, agent.role = room.agent_name, room.agent_role


def import_all(db: Session, data_dir: Path | None = None, slugs: list[str] | None = None) -> list[ImportResult]:
    defs = [PROJECTS_BY_SLUG[s] for s in slugs] if slugs else PROJECTS
    results = [import_project(db, pdef, data_dir) for pdef in defs]
    ensure_agents(db)
    db.flush()
    if db.scalar(select(StudioProject.id).where(StudioProject.is_active.is_(True))) is None:
        first = next((r for r in results if r.found), None)
        if first:
            db.scalar(select(StudioProject).where(StudioProject.slug == first.slug)).is_active = True
    db.commit()
    return results
