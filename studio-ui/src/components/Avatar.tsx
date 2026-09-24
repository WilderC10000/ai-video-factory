import type { AgentStatus } from "../types";

interface Props {
  status: AgentStatus;
  accent: string;
  needsYou: boolean;
  size?: number;
}

/** A small studio robot. Its pose and badge are driven only by the agent's real status. */
export function Avatar({ status, accent, needsYou, size = 56 }: Props) {
  return (
    <div className={`avatar avatar--${status}`} style={{ width: size, height: size * 1.2 }}>
      {needsYou && <span className="avatar__bubble" title="Waiting on you">YOU</span>}
      {!needsYou && status === "blocked" && <span className="avatar__bubble avatar__bubble--blocked">!</span>}
      {status === "failed" && <span className="avatar__bubble avatar__bubble--failed">×</span>}
      {status === "complete" && <span className="avatar__bubble avatar__bubble--complete">✓</span>}
      <svg viewBox="0 0 60 72" width={size} height={size * 1.2} aria-hidden="true">
        <line x1="30" y1="4" x2="30" y2="12" stroke={accent} strokeWidth="2.5" strokeLinecap="round" />
        <circle className="avatar__antenna" cx="30" cy="4" r="3.5" fill={accent} />
        <rect x="11" y="12" width="38" height="30" rx="12" fill="var(--robot-shell)" stroke={accent} strokeWidth="2" />
        <rect x="16" y="18" width="28" height="17" rx="8" fill="var(--robot-visor)" />
        <g className="avatar__eyes" fill={accent}>
          <ellipse cx="24" cy="26.5" rx="3" ry="3.6" />
          <ellipse cx="36" cy="26.5" rx="3" ry="3.6" />
        </g>
        <rect x="17" y="45" width="26" height="20" rx="8" fill="var(--robot-shell)" stroke={accent} strokeWidth="2" />
        <circle cx="30" cy="55" r="3.2" className="avatar__core" />
        <rect x="8" y="48" width="6" height="12" rx="3" fill="var(--robot-shell)" stroke={accent} strokeWidth="1.5" />
        <rect x="46" y="48" width="6" height="12" rx="3" fill="var(--robot-shell)" stroke={accent} strokeWidth="1.5" />
      </svg>
      <span className="avatar__shadow" />
    </div>
  );
}
