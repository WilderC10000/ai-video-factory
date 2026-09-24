import type { Selection, Snapshot, Stage } from "../types";
import { ProductionShaft } from "./ProductionShaft";
import { RoomCard } from "./RoomCard";

interface Props {
  snap: Required<Snapshot>;
  selection: Selection | null;
  onSelectRoom: (roomId: string) => void;
  onSelectStage: (stage: Stage) => void;
}

/** Cutaway building: Command Deck on the roof, two wings of rooms around the production shaft. */
export function Building({ snap, selection, onSelectRoom, onSelectStage }: Props) {
  const { rooms, project, stages, budget, approvals } = snap;
  const floors = Math.max(...rooms.map((r) => r.floor));
  const deck = rooms.find((r) => r.floor === 0);
  const card = (roomId: string) => {
    const room = rooms.find((r) => r.id === roomId)!;
    return (
      <RoomCard
        key={room.id}
        room={room}
        project={project!}
        stages={stages}
        budget={budget}
        approvals={approvals}
        selected={selection?.roomId === room.id}
        onSelect={onSelectRoom}
      />
    );
  };

  return (
    <div className="building">
      <div className="building__sign">
        <span className="building__wordmark">FORMA</span>
        <span className="building__sub">Virtual Studio</span>
      </div>
      <div className="building__roof">{deck && card(deck.id)}</div>
      <div className="building__body" style={{ gridTemplateRows: `repeat(${floors}, minmax(172px, auto))` }}>
        {rooms
          .filter((r) => r.floor > 0)
          .map((r) => (
            <div
              key={r.id}
              className="building__slot"
              style={{ gridRow: r.floor, gridColumn: r.col === 0 ? 1 : 3 }}
            >
              {card(r.id)}
            </div>
          ))}
        <div className="building__shaft" style={{ gridRow: `1 / span ${floors}`, gridColumn: 2 }}>
          <ProductionShaft
            stages={stages}
            currentKey={project!.current_stage_key}
            workingKey={snap.active_job?.stage_key ?? null}
            selectedStage={selection?.stageKey}
            onSelect={onSelectStage}
          />
        </div>
      </div>
      <div className="building__ground">
        <span className="building__door">FORMA</span>
      </div>
    </div>
  );
}
