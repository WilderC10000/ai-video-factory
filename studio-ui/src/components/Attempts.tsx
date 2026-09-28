import { useEffect, useRef, useState } from "react";
import { timeAgo, usd } from "../format";
import type { Attempt } from "../types";

const STATUS_TEXT: Record<Attempt["status"], string> = {
  complete: "Complete",
  in_flight: "Generating at the provider",
  cancelled: "Cancelled (not billed)",
  failed: "Failed (not billed)",
  not_started: "Not started",
};

function verdictChip(a: Attempt) {
  if (a.verdict?.verdict === "failed") {
    const why = a.verdict.failure_class ? a.verdict.failure_class.replace(/_/g, " ") : "failed";
    return <span className="state-chip state-chip--rejected">Proof failed · {why}</span>;
  }
  if (a.verdict?.verdict === "passed") return <span className="state-chip state-chip--approved">Proof passed</span>;
  if (a.status === "complete") return <span className="state-chip state-chip--waiting">Awaiting your review</span>;
  return null;
}

function AttemptCard({ a }: { a: Attempt }) {
  const cost = a.actual_cost_usd ?? a.estimated_cost_usd;
  return (
    <div className={`attempt is-${a.status}`}>
      <div className="attempt__head">
        <b>{a.model_label ?? a.model ?? "Unknown model"}</b>
        {a.provider && <span className="attempt__provider">via {a.provider}</span>}
        <span className="attempt__label">{a.label}</span>
      </div>
      {a.output_url ? (
        <video src={a.output_url} poster={a.start_frame_url ?? undefined} controls playsInline loop preload="metadata" />
      ) : (
        <div className="thumb thumb--empty attempt__empty">
          {a.status === "in_flight" ? "Generating - the clip appears here when it finishes." : STATUS_TEXT[a.status]}
        </div>
      )}
      <div className="attempt__chips">{verdictChip(a)}</div>
      <dl className="attempt__facts">
        <dt>Status</dt>
        <dd className={`attempt__status is-${a.status}`}>{STATUS_TEXT[a.status]}</dd>
        <dt>Job ID</dt>
        <dd>{a.provider_job_id ? <code>{a.provider_job_id}</code> : "—"}</dd>
        <dt>{a.actual_cost_usd != null ? "Cost recorded" : "Estimated cost"}</dt>
        <dd>
          {usd(cost)}
          {a.status === "cancelled" || a.status === "failed" ? " (not billed)" : ""}
        </dd>
        <dt>Settings</dt>
        <dd>
          {[a.resolution, a.duration_seconds != null ? `${a.duration_seconds} s` : null,
            a.audio === false ? "sound off" : a.audio ? "sound on" : null].filter(Boolean).join(" · ") || "—"}
        </dd>
        <dt>{a.completed_at ? "Completed" : "Submitted"}</dt>
        <dd>{a.completed_at ? timeAgo(a.completed_at) : a.submitted_at ? timeAgo(a.submitted_at) : "—"}</dd>
      </dl>
      {a.verdict?.findings && a.verdict.findings.length > 0 && (
        <details className="attempt__findings">
          <summary>Review findings ({a.verdict.findings.length})</summary>
          <ul>
            {a.verdict.findings.map((f) => (
              <li key={f}>{f}</li>
            ))}
          </ul>
          {a.verdict.continuity && <p className="fineprint">Continuity: {a.verdict.continuity}</p>}
        </details>
      )}
    </div>
  );
}

/** Two completed attempts side by side, played in lock-step from the same frame. */
function SideBySide({ left, right }: { left: Attempt; right: Attempt }) {
  const a = useRef<HTMLVideoElement>(null);
  const b = useRef<HTMLVideoElement>(null);
  const both = () => [a.current, b.current].filter((v): v is HTMLVideoElement => !!v);
  const play = () =>
    both().forEach((v) => {
      v.currentTime = 0;
      void v.play();
    });
  const pause = () => both().forEach((v) => v.pause());
  return (
    <div className="attempts__compare">
      <div className="attempts__compare-row">
        {[left, right].map((x, i) => (
          <figure key={x.key}>
            <video ref={i === 0 ? a : b} src={x.output_url ?? undefined} muted playsInline loop preload="metadata" />
            <figcaption>
              {x.model_label} · {x.label}
            </figcaption>
          </figure>
        ))}
      </div>
      <div className="attempts__compare-actions">
        <button type="button" className="btn" onClick={play}>
          ▶ Play both from start
        </button>
        <button type="button" className="btn" onClick={pause}>
          Pause
        </button>
      </div>
    </div>
  );
}

export function Attempts({ attempts }: { attempts: Attempt[] }) {
  const playable = attempts.filter((x) => x.output_url);
  const [pair, setPair] = useState<[string, string] | null>(null);
  useEffect(() => {
    // Default comparison: the primary result against the newest other playable attempt.
    const primary = playable.find((x) => x.is_primary);
    const other = [...playable].reverse().find((x) => !x.is_primary);
    setPair(primary && other ? [primary.key, other.key] : playable.length >= 2 ? [playable[0].key, playable[1].key] : null);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [attempts.map((x) => `${x.key}:${x.status}`).join("|")]);

  if (attempts.length === 0) return null;
  const left = playable.find((x) => x.key === pair?.[0]);
  const right = playable.find((x) => x.key === pair?.[1]);
  return (
    <div className="attempts">
      <div className="compare__head">
        <h4>Provider attempts ({attempts.length})</h4>
        <span className="fineprint">
          Each attempt is kept separately - the stage's own approval and the proof gate belong to the primary result.
        </span>
      </div>
      <div className="attempts__grid">
        {attempts.map((x) => (
          <AttemptCard key={x.key} a={x} />
        ))}
      </div>
      {left && right && (
        <>
          <div className="compare__head">
            <h4>Side-by-side comparison</h4>
            {playable.length > 2 && (
              <span className="fineprint">
                <select value={pair?.[0]} onChange={(e) => setPair([e.target.value, pair?.[1] ?? ""])}>
                  {playable.map((x) => (
                    <option key={x.key} value={x.key}>{`${x.model_label} · ${x.label}`}</option>
                  ))}
                </select>{" "}
                vs{" "}
                <select value={pair?.[1]} onChange={(e) => setPair([pair?.[0] ?? "", e.target.value])}>
                  {playable.map((x) => (
                    <option key={x.key} value={x.key}>{`${x.model_label} · ${x.label}`}</option>
                  ))}
                </select>
              </span>
            )}
          </div>
          <SideBySide left={left} right={right} />
        </>
      )}
    </div>
  );
}
