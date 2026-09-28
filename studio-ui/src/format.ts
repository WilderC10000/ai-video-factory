import type { AgentStatus, Severity, Stage } from "./types";

export const usd = (n: number | null | undefined) => (n == null ? "—" : `$${n.toFixed(2)}`);

export function timeAgo(iso: string | null): string {
  if (!iso) return "—";
  // Naive timestamps from SQLite are UTC.
  const t = new Date(/[zZ]|[+-]\d\d:?\d\d$/.test(iso) ? iso : `${iso}Z`).getTime();
  const s = Math.max(0, (Date.now() - t) / 1000);
  if (s < 60) return "just now";
  if (s < 3600) return `${Math.floor(s / 60)}m ago`;
  if (s < 86400) return `${Math.floor(s / 3600)}h ago`;
  return `${Math.floor(s / 86400)}d ago`;
}

export const parseIso = (iso: string) => new Date(/[zZ]|[+-]\d\d:?\d\d$/.test(iso) ? iso : `${iso}Z`).getTime();

/** "42s", "3m 07s", "1h 04m" */
export function fmtDuration(ms: number): string {
  const s = Math.max(0, Math.floor(ms / 1000));
  if (s < 60) return `${s}s`;
  if (s < 3600) return `${Math.floor(s / 60)}m ${String(s % 60).padStart(2, "0")}s`;
  return `${Math.floor(s / 3600)}h ${String(Math.floor((s % 3600) / 60)).padStart(2, "0")}m`;
}

export const STATUS_LABEL: Record<AgentStatus, string> = {
  idle: "Idle",
  working: "Working",
  waiting_for_approval: "Waiting for approval",
  blocked: "Blocked",
  failed: "Failed",
  complete: "Complete",
};

export const SEVERITY_LABEL: Record<Severity, string> = {
  info: "Info",
  low: "Low",
  medium: "Medium",
  high: "High",
  critical: "Critical",
};

/** "Shot 4 - A-Frame Ribs [HERO]" -> { tag: "Shot 4", title: "A-Frame Ribs [HERO]" } */
export function splitLabel(label: string): { tag: string; title: string } {
  const i = label.indexOf(" - ");
  return i === -1 ? { tag: label, title: "" } : { tag: label.slice(0, i), title: label.slice(i + 3) };
}

export const isVideo = (s: Stage) => !!s.latest_output_name?.toLowerCase().endsWith(".mp4");
