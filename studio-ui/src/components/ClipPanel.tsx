import { useEffect, useState } from "react";
import { ApiError, api } from "../api";
import type { Attempt, ClipPlan, Execution } from "../types";

const STATE_TEXT: Record<ClipPlan["state"], string> = {
  blocked: "Blocked",
  ready: "Ready - needs a spend approval",
  budget_approved: "Spend approved - ready to submit",
  submitted: "Submitted",
  queued: "Queued at fal",
  generating: "Generating",
  downloading: "Downloading",
  review: "Waiting for your review",
  accepted: "Accepted",
  stale: "Stale - an anchor still changed",
};

const money = (n: number | null | undefined, digits = 3) => (n == null ? "—" : `$${n.toFixed(digits)}`);

/** A spec-driven clip: route, estimate, one spend approval per job, the paid submit, and the review verdict. */
export function ClipPanel({
  projectSlug,
  plan,
  attempts,
  execution,
  frozen,
  onChanged,
}: {
  projectSlug: string;
  plan: ClipPlan;
  attempts: Attempt[];
  execution: Execution;
  frozen: boolean;
  onChanged: () => void;
}) {
  const [maxUsd, setMaxUsd] = useState("");
  const [note, setNote] = useState("");
  const [confirm, setConfirm] = useState(false);
  const [reviewNote, setReviewNote] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [problems, setProblems] = useState<string[]>([]);

  useEffect(() => {
    setMaxUsd(plan.estimate_usd != null ? (Math.ceil(plan.estimate_usd * 100) / 100).toFixed(2) : "");
    setNote("");
    setConfirm(false);
    setReviewNote("");
    setError(null);
    setProblems([]);
  }, [plan.clip, plan.estimate_usd]);

  const run = async (fn: () => Promise<unknown>) => {
    setBusy(true);
    setError(null);
    setProblems([]);
    try {
      await fn();
      onChanged();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
      if (e instanceof ApiError) setProblems(e.problems);
    } finally {
      setBusy(false);
    }
  };

  const toReview = plan.state === "review" ? attempts.find((a) => a.key === plan.attempt) : undefined;
  const live = execution.mode === "live";

  return (
    <div className="clipplan">
      <div className="mstill__head">
        <span className={`state-chip clipplan__state is-${plan.state}`}>{STATE_TEXT[plan.state]}</span>
        <code>{plan.clip}</code>
        <span className="fineprint">
          clip {plan.n}/{plan.of} of {plan.shot} · {plan.complexity} · {plan.shot_class.replace("_", " ")}
          {plan.proof ? " · PROOF" : ""}
        </span>
      </div>
      {plan.reasons.length > 0 && (
        <ul className="clipplan__reasons">
          {plan.reasons.map((r) => (
            <li key={r}>{r}</li>
          ))}
        </ul>
      )}

      <dl className="review__facts">
        <dt>Anchors</dt>
        <dd>
          <code>{plan.start_still}</code> → <code>{plan.end_still}</code>
        </dd>
        <dt>Task</dt>
        <dd>
          {plan.task} <span className="fineprint">({plan.location}, {plan.duration_seconds} s)</span>
        </dd>
        <dt>Model</dt>
        <dd>
          {plan.route.model ?? "none"} · <b>{plan.route.status.replace(/_/g, " ")}</b>
          <div className="fineprint">{plan.route.evidence}</div>
        </dd>
        <dt>Estimate</dt>
        <dd>{money(plan.estimate_usd, 4)} (audio off)</dd>
        <dt>Project budget</dt>
        <dd>
          {money(plan.budget.spent_usd, 2)} spent · {money(plan.budget.reserved_usd, 2)} in flight · {money(plan.budget.remaining_usd, 2)} left of{" "}
          {money(plan.budget.cap_usd, 2)} · per-clip ceiling {money(plan.budget.per_clip_max_usd, 2)}
        </dd>
        <dt>Spend approval</dt>
        <dd>
          {plan.budget_approval
            ? `${money(plan.budget_approval.max_usd, 2)} - “${plan.budget_approval.note}”${plan.budget_approval.consumed_by ? ` (used by ${plan.budget_approval.consumed_by})` : " (open, one job)"}`
            : "none"}
        </dd>
      </dl>

      {plan.state === "ready" && !frozen && (
        <div className="confirm">
          <div className="confirm__title">Approve spend for ONE job of this clip</div>
          <div className="clipplan__row">
            <label>
              Up to $ <input className="clipplan__usd" value={maxUsd} onChange={(e) => setMaxUsd(e.target.value)} inputMode="decimal" />
            </label>
            <input className="note" placeholder="Why (required)" value={note} onChange={(e) => setNote(e.target.value)} />
            <button
              type="button"
              className="btn btn--primary"
              disabled={busy || !note.trim() || !(Number(maxUsd) > 0)}
              onClick={() => run(() => api.approveClipBudget(projectSlug, plan.clip, Number(maxUsd), note))}
            >
              Approve spend
            </button>
          </div>
          <p className="fineprint">Nothing is spent here. A failed or rejected job needs a new approval - nothing is retried automatically.</p>
        </div>
      )}

      {plan.state === "budget_approved" && !frozen && (
        <div className="confirm">
          <div className="confirm__title">Submit (paid)</div>
          {plan.money_problems.length > 0 && (
            <ul className="clipplan__reasons">
              {plan.money_problems.map((p) => (
                <li key={p}>{p}</li>
              ))}
            </ul>
          )}
          <label className="mstill__replace">
            <input type="checkbox" checked={confirm} onChange={(e) => setConfirm(e.target.checked)} />
            Spend up to {money(plan.budget_approval?.max_usd, 2)} on one {plan.route.model} job ({money(plan.estimate_usd, 4)} estimated).
          </label>
          <button
            type="button"
            className="btn btn--primary"
            disabled={busy || !confirm || !live || plan.money_problems.length > 0}
            title={!live ? `Execution mode is ${execution.mode} - paid submissions need live mode` : undefined}
            onClick={() => run(() => api.submitClip(projectSlug, plan.clip))}
          >
            {busy ? "Submitting…" : "Submit one job"}
          </button>
          {!live && <p className="fineprint">Execution mode is {execution.mode}: paid submissions need STUDIO_EXECUTION_MODE=live.</p>}
          <p className="fineprint">After submit the Render Bay follows the job (queue → generate → download) on its own; it survives restarts.</p>
        </div>
      )}

      {toReview && (
        <div className="confirm">
          <div className="confirm__title">Review {toReview.label}</div>
          <textarea className="note" rows={2} placeholder="What did you see?" value={reviewNote} onChange={(e) => setReviewNote(e.target.value)} />
          <div className="confirm__actions">
            <button type="button" className="btn btn--primary" disabled={busy} onClick={() => run(() => api.reviewAttempt(projectSlug, plan.clip, toReview.key, "accept", reviewNote))}>
              Accept clip
            </button>
            <button type="button" className="btn btn--warn" disabled={busy} onClick={() => run(() => api.reviewAttempt(projectSlug, plan.clip, toReview.key, "reject", reviewNote))}>
              Reject
            </button>
          </div>
        </div>
      )}

      {plan.spec_errors.length > 0 && (
        <details className="clipplan__reasons" open>
          <summary>Project spec errors ({plan.spec_errors.length})</summary>
          <ul>
            {plan.spec_errors.map((p) => (
              <li key={p}>{p}</li>
            ))}
          </ul>
        </details>
      )}
      {error && (
        <div className="confirm__problem">
          ✕ {error}
          {problems.length > 0 && (
            <ul>
              {problems.map((p) => (
                <li key={p}>{p}</li>
              ))}
            </ul>
          )}
        </div>
      )}
      <details className="intent">
        <summary>Generation prompt</summary>
        <p className="intent__prompt">{plan.prompt}</p>
      </details>
    </div>
  );
}
