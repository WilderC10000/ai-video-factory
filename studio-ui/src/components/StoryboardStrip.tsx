import { splitLabel, usd } from "../format";
import type { Stage } from "../types";
import { StageThumb } from "./StageThumb";

interface Props {
  stages: Stage[];
  currentKey: string | null;
  workingKey?: string | null;
  selectedStage?: string;
  onSelect: (stage: Stage) => void;
}

/** Every stage's real output in story order; stages not yet run show their planned cost. */
export function StoryboardStrip({ stages, currentKey, workingKey, selectedStage, onSelect }: Props) {
  return (
    <section className="storyboard" aria-label="Storyboard">
      <div className="storyboard__head">
        <h2>Storyboard</h2>
        <span className="fineprint">Real outputs per stage · checkpoints (◆) are the build-state stills between shots</span>
      </div>
      <div className="storyboard__track">
        {stages.map((s, i) => {
          const { tag, title } = splitLabel(s.label);
          return (
            <button
              key={s.key}
              type="button"
              className={`frame is-${s.status} ${s.key === currentKey ? "is-current" : ""} ${workingKey === s.key ? "is-working" : ""} ${
                selectedStage === s.key ? "is-selected" : ""
              } ${s.requires_human_review ? "is-needs-you" : ""} kind--${s.kind}`}
              onClick={() => onSelect(s)}
            >
              <span className="frame__num">{String(i + 1).padStart(2, "0")}</span>
              <StageThumb stage={s} />
              <span className="frame__label">
                <b>{tag}</b>
                <span>{title || " "}</span>
              </span>
              <span className="frame__meta">
                {s.status === "complete" ? usd(s.actual_cost_usd ?? 0) : s.planned_cost_usd ? `planned ${usd(s.planned_cost_usd)}` : s.status}
              </span>
              {workingKey === s.key && <span className="frame__flag frame__flag--working">Working</span>}
              {workingKey !== s.key && s.requires_human_review && (
                <span className={`frame__flag ${s.approval_state === "rejected" ? "frame__flag--rejected" : ""}`}>
                  {s.approval_state === "rejected" ? "Rejected" : "Review"}
                </span>
              )}
            </button>
          );
        })}
      </div>
    </section>
  );
}
