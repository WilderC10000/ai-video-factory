import { useEffect, useState } from "react";
import { usd } from "../format";
import type { Job, JobStatus } from "../types";

// Only real, reported states - no percentage bars (the provider exposes none).
const VIDEO_STEPS: { status: JobStatus[]; label: string }[] = [
  { status: ["queued", "submitting"], label: "Submitting" },
  { status: ["provider_queued"], label: "Queued" },
  { status: ["generating"], label: "Generating" },
  { status: ["downloading"], label: "Downloading" },
  { status: ["syncing"], label: "Syncing" },
  { status: ["succeeded"], label: "Complete" },
];
const LOCAL_STEPS: { status: JobStatus[]; label: string }[] = [
  { status: ["queued", "submitting"], label: "Starting" },
  { status: ["generating", "provider_queued", "downloading"], label: "Generating" },
  { status: ["syncing"], label: "Syncing" },
  { status: ["succeeded"], label: "Complete" },
];

function useNow(active: boolean): number {
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    if (!active) return;
    const id = window.setInterval(() => setNow(Date.now()), 1000);
    return () => window.clearInterval(id);
  }, [active]);
  return now;
}

const fmtElapsed = (ms: number) => {
  const s = Math.max(0, Math.floor(ms / 1000));
  return s < 60 ? `${s}s` : `${Math.floor(s / 60)}m ${String(s % 60).padStart(2, "0")}s`;
};

export function JobProgress({ job, compact = false }: { job: Job; compact?: boolean }) {
  const now = useNow(job.active);
  const steps = job.action === "video" ? VIDEO_STEPS : LOCAL_STEPS;
  const current = steps.findIndex((s) => s.status.includes(job.status));
  const failedAt = job.status === "failed";
  const start = job.started_at ? new Date(job.started_at).getTime() : null;
  const end = job.completed_at ? new Date(job.completed_at).getTime() : now;

  return (
    <div className={`job ${failedAt ? "job--failed" : job.active ? "job--active" : "job--done"}`}>
      <div className="job__head">
        <b>{job.mode === "retry" ? "Retry" : "Generation"} · {job.phase_label}</b>
        <span className={`mode-badge mode-badge--${job.execution_mode}`}>{job.execution_mode.toUpperCase()}</span>
        {start && <span className="job__time">{fmtElapsed(end - start)}</span>}
      </div>
      {!failedAt && (
        <ol className="job__steps">
          {steps.map((s, i) => (
            <li key={s.label} className={i < current ? "is-done" : i === current ? "is-current" : ""}>
              {s.label}
            </li>
          ))}
        </ol>
      )}
      {failedAt && job.error && <pre className="job__error">{job.error}</pre>}
      {!compact && (
        <div className="job__meta">
          {job.is_paid ? `Expected up to ${usd(job.expected_cost_usd)}` : "No spend"}
          {job.actual_cost_usd != null && ` · actual ${usd(job.actual_cost_usd)}`}
          {job.provider_job_id && (
            <>
              {" · provider job "}
              <code>{job.provider_job_id}</code>
            </>
          )}
        </div>
      )}
      {!compact && job.log_tail.length > 0 && (
        <details className="job__log" open={failedAt}>
          <summary>Pipeline output</summary>
          <pre>{job.log_tail.join("\n")}</pre>
        </details>
      )}
    </div>
  );
}
