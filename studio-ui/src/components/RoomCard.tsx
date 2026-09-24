import { STATUS_LABEL } from "../format";
import type { Approval, Budget, ProjectInfo, Room, Stage } from "../types";
import { Avatar } from "./Avatar";
import { RoomScreen } from "./RoomScreen";

export const ROOM_ACCENT: Record<string, string> = {
  command_deck: "#b9a6ff",
  story_lab: "#f472b6",
  continuity_office: "#fbbf24",
  build_logic_workshop: "#60a5fa",
  finance_room: "#34d399",
  render_bay: "#a78bfa",
  edit_suite: "#fb7185",
  sound_booth: "#fb923c",
  screening_room: "#818cf8",
  analytics_observatory: "#22d3ee",
  library_archive: "#e879f9",
};

interface Props {
  room: Room;
  project: ProjectInfo;
  stages: Stage[];
  budget: Budget | null;
  approvals: Approval[];
  selected: boolean;
  onSelect: (roomId: string) => void;
}

export function RoomCard({ room, project, stages, budget, approvals, selected, onSelect }: Props) {
  const { agent } = room;
  const accent = ROOM_ACCENT[room.id] ?? "#94a3b8";
  const dim = room.data_source === null;

  return (
    <section
      className={`room room--${room.id} room--state-${agent.status} ${agent.requires_human_review ? "is-calling" : ""} ${
        selected ? "is-selected" : ""
      } ${dim ? "is-dim" : ""}`}
      style={{ ["--accent" as string]: accent }}
      role="button"
      tabIndex={0}
      aria-label={`${room.name}: ${agent.name}, ${STATUS_LABEL[agent.status]}`}
      onClick={() => onSelect(room.id)}
      onKeyDown={(e) => (e.key === "Enter" || e.key === " ") && (e.preventDefault(), onSelect(room.id))}
    >
      <header className="room__header">
        <h3 className="room__name">{room.name}</h3>
        {room.warning_count > 0 && (
          <span className={`sev-chip sev--${room.worst_severity}`} title={`${room.warning_count} warning(s)`}>
            ⚠ {room.warning_count}
          </span>
        )}
      </header>

      <div className="room__body">
        <button
          type="button"
          className="room__agent"
          onClick={(e) => (e.stopPropagation(), onSelect(room.id))}
          title={`${agent.name} - ${agent.role}`}
        >
          <Avatar status={agent.status} accent={accent} needsYou={agent.requires_human_review} />
          <span className="room__agent-name">{agent.name}</span>
        </button>
        <div className="room__screen-wrap">
          {agent.status === "working" && <span className="room__activity" aria-hidden="true" />}
          <RoomScreen room={room} project={project} stages={stages} budget={budget} approvals={approvals} />
        </div>
      </div>

      <footer className="room__footer">
        <span className={`status-pill status--${agent.status}`}>
          <span className="status-dot" />
          {STATUS_LABEL[agent.status]}
        </span>
        {agent.job_phase && <span className="phase-chip">{agent.job_phase}</span>}
        {agent.requires_human_review && (
          <span className="needs-you">{agent.status === "waiting_for_approval" ? "Your approval" : "Needs you"}</span>
        )}
        <span className="room__reason">{agent.current_task ?? agent.status_reason}</span>
      </footer>
      <span className="room__floor-light" />
    </section>
  );
}
