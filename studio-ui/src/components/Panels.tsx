import { useState } from "react";
import { SEVERITY_LABEL, timeAgo, usd } from "../format";
import type { Approval, Budget, ProjectInfo, Snapshot, Stage, StudioEvent } from "../types";
import { StageThumb } from "./StageThumb";

export function ProjectPanel({
  project,
  projects,
  stages,
  syncing,
  onSwitch,
  onResync,
  onSelectStage,
}: {
  project: ProjectInfo;
  projects: Snapshot["projects"];
  stages: Stage[];
  syncing: boolean;
  onSwitch: (slug: string) => void;
  onResync: () => void;
  onSelectStage: (s: Stage) => void;
}) {
  const latest = [...stages].reverse().find((s) => s.status === "complete" && s.latest_output_url);
  const pct = project.stages_total ? (project.stages_complete / project.stages_total) * 100 : 0;
  return (
    <section className="panel">
      <div className="panel__head">
        <h2>Active project</h2>
        <span className={`source-badge ${project.is_demo ? "is-demo" : ""}`}>
          {project.is_demo ? "DEMO DATA" : "Live · from manifest"}
        </span>
      </div>
      <select className="project-select" value={project.slug} onChange={(e) => onSwitch(e.target.value)}>
        {projects.map((p) => (
          <option key={p.slug} value={p.slug}>
            {p.name}
          </option>
        ))}
      </select>
      <div className="kv">
        <span>Production stage</span>
        <b>{project.production_stage}</b>
      </div>
      <div className="progress" title={`${project.stages_complete}/${project.stages_total} stages complete`}>
        <span style={{ width: `${pct}%` }} />
      </div>
      <div className="kv kv--row">
        <span>{project.stages_complete}/{project.stages_total} stages complete</span>
      </div>
      {latest && (
        <button type="button" className="preview" onClick={() => onSelectStage(latest)}>
          <StageThumb stage={latest} controls={false} />
          <span className="preview__label">
            Latest output · <b>{latest.label}</b>
          </span>
        </button>
      )}
      <div className="sync-row">
        <span>Synced {timeAgo(project.last_imported_at)}</span>
        <button type="button" className="btn" onClick={onResync} disabled={syncing}>
          {syncing ? "Syncing…" : "Re-sync manifests"}
        </button>
      </div>
    </section>
  );
}

export function BudgetPanel({ budget }: { budget: Budget | null }) {
  if (!budget) return null;
  const cap = budget.cap_usd;
  const pct = (n: number) => (cap ? `${Math.min(100, (n / cap) * 100)}%` : "0%");
  return (
    <section className="panel">
      <div className="panel__head">
        <h2>Budget</h2>
        {budget.over_cap && <span className="sev-chip sev--critical">Over cap</span>}
        {!budget.over_cap && budget.plan_exceeds_cap && <span className="sev-chip sev--medium">Plan exceeds cap</span>}
      </div>
      <div className="budget-grid">
        <div><span>Total budget</span><b>{usd(cap)}</b></div>
        <div><span>Spent</span><b>{usd(budget.spent_usd)}</b></div>
        <div><span>Remaining</span><b className={budget.over_cap ? "is-critical" : ""}>{usd(budget.remaining_usd)}</b></div>
      </div>
      <div className="finance__bar finance__bar--lg">
        <span className="finance__spent" style={{ width: pct(budget.spent_usd) }} />
        <span className="finance__planned" style={{ width: pct(budget.planned_remaining_spend_usd) }} />
      </div>
      <div className="legend">
        <span><i className="legend__spent" /> Spent</span>
        <span><i className="legend__planned" /> Planned for remaining stages · {usd(budget.planned_remaining_spend_usd)}</span>
      </div>
      {budget.cap_source && <p className="fineprint">Cap source: {budget.cap_source}</p>}
    </section>
  );
}

export function AttentionPanel({
  approvals,
  events,
  onOpen,
}: {
  approvals: Approval[];
  events: StudioEvent[];
  onOpen: (roomId: string, stageKey?: string) => void;
}) {
  const pending = approvals.filter((a) => a.status === "pending");
  const warnings = events.filter((e) => e.severity !== "info");
  return (
    <section className="panel">
      <div className="panel__head">
        <h2>Approvals &amp; warnings</h2>
        <span className="count">{pending.length + warnings.length}</span>
      </div>
      {pending.length === 0 && warnings.length === 0 && <p className="empty">Nothing needs attention.</p>}
      <ul className="attn">
        {pending.map((a) => (
          <li key={a.id}>
            <button type="button" className="attn__item attn__item--you" onClick={() => onOpen(a.room_id ?? "screening_room", a.stage_key ?? undefined)}>
              <span className="needs-you">Waiting on you</span>
              <span className="attn__text">{a.title}</span>
            </button>
          </li>
        ))}
        {warnings.map((e) => (
          <li key={e.id}>
            <button type="button" className="attn__item" onClick={() => onOpen(e.room_id ?? "command_deck", e.stage_key ?? undefined)}>
              <span className={`sev-chip sev--${e.severity}`}>{SEVERITY_LABEL[e.severity]}</span>
              {e.requires_human_review && <span className="needs-you">You</span>}
              <span className="attn__text">{e.message}</span>
            </button>
          </li>
        ))}
      </ul>
    </section>
  );
}

export function ActivityPanel({
  events,
  roomNames,
  onOpen,
}: {
  events: StudioEvent[];
  roomNames: Record<string, string>;
  onOpen: (roomId: string, stageKey?: string) => void;
}) {
  const [limit, setLimit] = useState(12);
  return (
    <section className="panel">
      <div className="panel__head">
        <h2>Activity</h2>
        <span className="count">{events.length}</span>
      </div>
      <ol className="log">
        {events.slice(0, limit).map((e) => (
          <li key={e.id}>
            <button type="button" className="log__item" onClick={() => e.room_id && onOpen(e.room_id, e.stage_key ?? undefined)}>
              <span className={`log__dot sev--${e.severity}`} />
              <span className="log__msg">{e.message}</span>
              <span className="log__meta">
                {e.room_id ? roomNames[e.room_id] : "Studio"} · {timeAgo(e.occurred_at)}
              </span>
            </button>
          </li>
        ))}
      </ol>
      {events.length > limit && (
        <button type="button" className="btn btn--ghost" onClick={() => setLimit(limit + 20)}>
          Show more
        </button>
      )}
    </section>
  );
}
