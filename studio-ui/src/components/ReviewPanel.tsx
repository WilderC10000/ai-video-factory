import { useEffect, useMemo, useState } from "react";
import { ApiError, api } from "../api";
import { isVideo, usd } from "../format";
import type { Budget, Execution, Job, LaunchMode, LaunchPlan, Stage } from "../types";
import { JobProgress } from "./JobProgress";

interface Props {
  projectSlug: string;
  stage: Stage;
  stages: Stage[];
  budget: Budget | null;
  execution: Execution;
  activeJob: Job | null;
  onChanged: () => void;
}

type Panel = null | "continue" | "retry" | "reject" | "generate";

function newRequestId(): string {
  return typeof crypto !== "undefined" && "randomUUID" in crypto
    ? crypto.randomUUID().replace(/-/g, "")
    : `${Date.now()}${Math.random().toString(16).slice(2)}`;
}

function MainMedia({ stage }: { stage: Stage }) {
  const [loop, setLoop] = useState(true);
  if (!stage.latest_output_url) {
    return (
      <div className="review__media review__media--empty">
        {stage.latest_output_exists === false
          ? "The recorded output file is missing on disk."
          : stage.status === "started"
            ? "Started but never completed - no output yet."
            : "Not generated yet."}
      </div>
    );
  }
  if (isVideo(stage)) {
    return (
      <div className="review__media">
        <video
          key={stage.latest_output_url}
          src={stage.latest_output_url}
          poster={stage.previous_frame_url ?? undefined}
          controls
          playsInline
          loop={loop}
          preload="metadata"
        />
        <label className="review__loop">
          <input type="checkbox" checked={loop} onChange={(e) => setLoop(e.target.checked)} /> Loop
        </label>
      </div>
    );
  }
  return (
    <div className="review__media">
      <a href={stage.latest_output_url} target="_blank" rel="noreferrer" title="Open full size">
        <img src={stage.latest_output_url} alt={stage.label} />
      </a>
    </div>
  );
}

function Compare({ stage }: { stage: Stage }) {
  const cell = (label: string, url: string | null, empty: string, video = false) => (
    <figure className="compare__cell">
      {url ? (
        video ? (
          <video src={`${url}#t=0.5`} muted playsInline preload="metadata" />
        ) : (
          <img src={url} alt={label} />
        )
      ) : (
        <div className="thumb thumb--empty">{empty}</div>
      )}
      <figcaption>{label}</figcaption>
    </figure>
  );
  return (
    <div className="compare">
      <div className="compare__head">
        <h4>Continuity comparison</h4>
        <span className="fineprint">Checked by eye for now; the Continuity Agent will compare these later.</span>
      </div>
      <div className="compare__row">
        {cell("Storyboard checkpoint", stage.storyboard_checkpoint_url, stage.storyboard_checkpoint_path ? "File missing" : "No storyboard yet")}
        {cell("Previous actual frame", stage.previous_frame_url, stage.previous_frame_path ? "File missing" : "None recorded")}
        {stage.target_frame_path && cell("Target end frame (pinned)", stage.target_frame_url, "File missing")}
        {cell("Latest output", stage.latest_output_url, "Not generated", isVideo(stage))}
      </div>
    </div>
  );
}

function LaunchConfirm({
  projectSlug,
  stage,
  mode,
  onCancel,
  onLaunched,
  onApproveOnly,
}: {
  projectSlug: string;
  stage: Stage;
  mode: LaunchMode;
  onCancel: () => void;
  onLaunched: () => void;
  onApproveOnly: () => void;
}) {
  const [plan, setPlan] = useState<LaunchPlan | null>(null);
  const [error, setError] = useState<string[] | null>(null);
  const [submitting, setSubmitting] = useState(false);
  // One id per opened panel: a double click or a retried request can only ever map to one job.
  const requestId = useMemo(newRequestId, []);

  useEffect(() => {
    let live = true;
    api
      .launchPreview(projectSlug, stage.key, mode)
      .then((p) => live && setPlan(p))
      .catch((e: unknown) => live && setError([e instanceof Error ? e.message : String(e)]));
    return () => {
      live = false;
    };
  }, [projectSlug, stage.key, mode]);

  const confirm = async () => {
    if (submitting || !plan?.allowed) return;
    setSubmitting(true);
    setError(null);
    try {
      await api.launch(projectSlug, stage.key, {
        mode,
        request_id: requestId,
        confirmed: true,
        approve_first: mode === "continue",
      });
      onLaunched();
    } catch (e) {
      setError(e instanceof ApiError && e.problems.length ? e.problems : [e instanceof Error ? e.message : String(e)]);
      setSubmitting(false);
    }
  };

  const live = plan?.execution.mode === "live";
  return (
    <div className={`confirm ${live ? "confirm--live" : ""}`}>
      <div className="confirm__title">
        {mode === "continue" ? "Approve & Continue" : mode === "retry" ? "Retry this stage" : "Generate this stage"}
        {plan && (
          <span className={`mode-badge mode-badge--${plan.execution.mode}`}>
            {plan.execution.mode === "live" ? "LIVE · real money" : plan.execution.mode === "mock" ? "MOCK · $0.00" : "EXECUTION OFF"}
          </span>
        )}
      </div>
      {!plan && !error && <p className="fineprint">Checking budget and pipeline state…</p>}
      {plan && (
        <>
          <dl className="confirm__grid">
            <dt>{mode === "continue" ? "Approves" : mode === "retry" ? "Re-runs" : "Generates"}</dt>
            <dd>{mode === "continue" ? plan.reviewed_stage.label : plan.target_stage?.label}</dd>
            {mode === "continue" && (
              <>
                <dt>Then launches</dt>
                <dd>{plan.target_stage?.label ?? "—"}</dd>
              </>
            )}
            <dt>{mode === "retry" ? "Estimated retry cost" : "Estimated cost"}</dt>
            <dd>{plan.paid ? `up to ${usd(plan.estimated_cost_usd)} (stage cap)` : "no spend (local)"}</dd>
            <dt>Already spent</dt>
            <dd>{usd(plan.spent_usd)}</dd>
            <dt>Remaining budget</dt>
            <dd>{usd(plan.remaining_usd)} of {usd(plan.cap_usd)}</dd>
            <dt>Remaining after</dt>
            <dd className={plan.remaining_after_usd != null && plan.remaining_after_usd < 0 ? "is-critical" : ""}>
              {usd(plan.remaining_after_usd)}
            </dd>
            {plan.target_stage?.script_path && (
              <>
                <dt>Pipeline script</dt>
                <dd>
                  <code>{plan.target_stage.script_path}</code>
                </dd>
              </>
            )}
          </dl>
          {plan.warnings.map((w) => (
            <p key={w} className="confirm__warning">⚠ {w}</p>
          ))}
          {plan.problems.map((p) => (
            <p key={p} className="confirm__problem">✕ {p}</p>
          ))}
        </>
      )}
      {error?.map((e) => (
        <p key={e} className="confirm__problem">✕ {e}</p>
      ))}
      <div className="confirm__actions">
        <button type="button" className="btn btn--ghost-inline" onClick={onCancel} disabled={submitting}>
          Cancel
        </button>
        {mode === "continue" && plan && !plan.allowed && stage.approval_state !== "approved" && (
          <button type="button" className="btn" onClick={onApproveOnly}>
            Approve only instead
          </button>
        )}
        <button
          type="button"
          className={`btn ${live ? "btn--danger" : "btn--primary"}`}
          onClick={confirm}
          disabled={!plan?.allowed || submitting}
        >
          {submitting
            ? "Launching…"
            : plan?.paid
              ? `Confirm · ${live ? "spend" : "mock"} up to ${usd(plan.estimated_cost_usd)}`
              : "Confirm · run locally"}
        </button>
      </div>
    </div>
  );
}

export function ReviewPanel({ projectSlug, stage, stages, budget, execution, activeJob, onChanged }: Props) {
  const [panel, setPanel] = useState<Panel>(null);
  const [note, setNote] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    setPanel(null);
    setNote("");
    setError(null);
  }, [stage.key]);

  const next = stages.find((s) => s.key === stage.next_stage_key) ?? null;
  const jobHere = activeJob && activeJob.stage_key === stage.key ? activeJob : null;
  const anyJob = !!activeJob;
  const hasOutput = stage.status === "complete";
  const lastFailed = stage.last_job?.status === "failed";
  const canRetry = stage.launchable && (hasOutput || lastFailed) && !anyJob;
  const approved = stage.approval_state === "approved";

  const decide = async (decision: "approve" | "reject") => {
    setBusy(true);
    setError(null);
    try {
      await api.decide(projectSlug, stage.key, decision, decision === "reject" ? note : undefined);
      setPanel(null);
      setNote("");
      onChanged();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  };

  const stateChip =
    stage.approval_state === "rejected" ? (
      <span className="state-chip state-chip--rejected">Rejected · needs attention</span>
    ) : stage.approval_state === "pending" && hasOutput ? (
      <span className="state-chip state-chip--waiting">Waiting for your approval</span>
    ) : approved ? (
      <span className="state-chip state-chip--approved">Approved</span>
    ) : null;

  return (
    <section className="review">
      <div className="review__title">
        <h3>{stage.label}</h3>
        {stateChip}
      </div>

      <MainMedia stage={stage} />

      {stage.status === "pending" && (
        <div className="review__generate">
          <button
            type="button"
            className="btn btn--primary"
            disabled={!stage.launchable || anyJob || busy}
            title={!stage.launchable ? "This stage can only be run from its script in the terminal" : undefined}
            onClick={() => setPanel(panel === "generate" ? null : "generate")}
          >
            Generate this stage…
          </button>
          <span className="fineprint">Runs only this one stage, after a cost check and your confirmation.</span>
        </div>
      )}

      <div className="review__controls">
        <button
          type="button"
          className="btn btn--primary"
          disabled={!hasOutput || anyJob || busy || !next}
          title={!next ? "This is the last stage" : anyJob ? "A job is running" : undefined}
          onClick={() => setPanel(panel === "continue" ? null : "continue")}
        >
          Approve &amp; Continue
        </button>
        <button type="button" className="btn" disabled={!hasOutput || approved || busy} onClick={() => decide("approve")}>
          Approve only
        </button>
        <button
          type="button"
          className="btn btn--warn"
          disabled={!hasOutput || busy || !!jobHere}
          onClick={() => setPanel(panel === "reject" ? null : "reject")}
        >
          Reject
        </button>
        <button
          type="button"
          className="btn"
          disabled={!canRetry || busy}
          title={!stage.launchable ? "This stage can only be re-run from its script in the terminal" : undefined}
          onClick={() => setPanel(panel === "retry" ? null : "retry")}
        >
          Retry…
        </button>
      </div>
      {!execution.launch_enabled && (panel === null || panel === "reject") && (
        <p className="fineprint review__exec-note">
          Launching is off ({execution.mode}). Approve / Reject are recorded; Continue and Retry will explain why they can't run.
        </p>
      )}
      {error && <p className="confirm__problem">✕ {error}</p>}

      {panel === "continue" && (
        <LaunchConfirm
          projectSlug={projectSlug}
          stage={stage}
          mode="continue"
          onCancel={() => setPanel(null)}
          onLaunched={() => {
            setPanel(null);
            onChanged();
          }}
          onApproveOnly={() => decide("approve")}
        />
      )}
      {panel === "generate" && (
        <LaunchConfirm
          projectSlug={projectSlug}
          stage={stage}
          mode="generate"
          onCancel={() => setPanel(null)}
          onLaunched={() => {
            setPanel(null);
            onChanged();
          }}
          onApproveOnly={() => decide("approve")}
        />
      )}
      {panel === "retry" && (
        <LaunchConfirm
          projectSlug={projectSlug}
          stage={stage}
          mode="retry"
          onCancel={() => setPanel(null)}
          onLaunched={() => {
            setPanel(null);
            onChanged();
          }}
          onApproveOnly={() => decide("approve")}
        />
      )}
      {panel === "reject" && (
        <div className="confirm">
          <div className="confirm__title">Reject this output</div>
          <p className="fineprint">Recorded only. Nothing is regenerated and nothing is spent.</p>
          <textarea
            className="note"
            rows={3}
            placeholder="What's wrong? (optional)"
            value={note}
            onChange={(e) => setNote(e.target.value)}
          />
          <div className="confirm__actions">
            <button type="button" className="btn btn--ghost-inline" onClick={() => setPanel(null)} disabled={busy}>
              Cancel
            </button>
            <button type="button" className="btn btn--warn" onClick={() => decide("reject")} disabled={busy}>
              {busy ? "Saving…" : "Confirm reject"}
            </button>
          </div>
        </div>
      )}

      {stage.last_job && (stage.last_job.active || stage.last_job.status === "failed" || stage.last_job.mode === "retry") && (
        <JobProgress job={stage.last_job} />
      )}

      <dl className="review__facts">
        <dt>Actual cost</dt>
        <dd>{stage.actual_cost_usd != null ? usd(stage.actual_cost_usd) : stage.planned_cost_usd ? `planned up to ${usd(stage.planned_cost_usd)}` : "no spend"}</dd>
        <dt>Next planned stage</dt>
        <dd>{next ? next.label : "— (last stage)"}</dd>
        <dt>Expected next cost</dt>
        <dd>{next ? (next.planned_cost_usd ? `up to ${usd(next.planned_cost_usd)}` : "no spend (local)") : "—"}</dd>
        <dt>Remaining budget</dt>
        <dd>
          {usd(budget?.remaining_usd)} of {usd(budget?.cap_usd)}
        </dd>
      </dl>

      {stage.intent && (
        <div className="intent">
          <h4>What was supposed to happen</h4>
          {stage.intent.checklist.length > 0 && (
            <ul>
              {stage.intent.checklist.map((c) => (
                <li key={c}>{c}</li>
              ))}
            </ul>
          )}
          {stage.intent.prompt && (
            <details>
              <summary>Generation prompt</summary>
              <p className="intent__prompt">{stage.intent.prompt}</p>
            </details>
          )}
          {stage.intent.note && <p className="fineprint">{stage.intent.note}</p>}
        </div>
      )}

      <Compare stage={stage} />
    </section>
  );
}
