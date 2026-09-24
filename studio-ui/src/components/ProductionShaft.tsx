import { splitLabel, usd } from "../format";
import type { Stage } from "../types";

interface Props {
  stages: Stage[];
  currentKey: string | null;
  workingKey?: string | null;
  selectedStage?: string;
  onSelect: (stage: Stage) => void;
}

const KIND_ICON: Record<Stage["kind"], string> = {
  image_generate: "◎",
  video: "▶",
  image_edit: "◆",
  assembly: "✂",
};

/** The building's central shaft: the project's real stage chain, top to bottom. */
export function ProductionShaft({ stages, currentKey, workingKey, selectedStage, onSelect }: Props) {
  const done = stages.filter((s) => s.status === "complete").length;
  const fill = stages.length ? (done / stages.length) * 100 : 0;

  return (
    <div className="shaft" aria-label="Production flow">
      <div className="shaft__title">Production flow</div>
      <div className="shaft__track">
        <span className="shaft__rail" />
        <span className="shaft__rail-fill" style={{ height: `${fill}%` }} />
        {stages.map((s) => {
          const { tag, title } = splitLabel(s.label);
          const current = s.key === currentKey;
          return (
            <button
              key={s.key}
              type="button"
              className={`node is-${s.status} ${current ? "is-current" : ""} ${workingKey === s.key ? "is-working" : ""} ${selectedStage === s.key ? "is-selected" : ""} ${
                s.requires_human_review ? "is-needs-you" : ""
              }`}
              onClick={() => onSelect(s)}
              title={`${s.label} - ${s.status}`}
            >
              <span className="node__icon">{s.status === "complete" ? "✓" : KIND_ICON[s.kind]}</span>
              <span className="node__text">
                <span className="node__tag">{tag}</span>
                {title && <span className="node__title">{title}</span>}
              </span>
              <span className="node__cost">
                {s.actual_cost_usd != null ? usd(s.actual_cost_usd) : s.planned_cost_usd ? usd(s.planned_cost_usd) : ""}
              </span>
            </button>
          );
        })}
      </div>
      <div className="shaft__footer">
        {done}/{stages.length} complete
      </div>
    </div>
  );
}
