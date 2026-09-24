import { splitLabel, usd } from "../format";
import type { Approval, AudioReport, Budget, ProjectInfo, Room, Stage } from "../types";
import { StageThumb } from "./StageThumb";

interface Props {
  room: Room;
  project: ProjectInfo;
  stages: Stage[];
  budget: Budget | null;
  approvals: Approval[];
  audio?: AudioReport;
}

export const FINAL_AUDIO_TEXT: Record<AudioReport["final_status"], string> = {
  not_assembled: "Final cut not assembled yet",
  preserved: "Source audio — preserved in final cut",
  discarded: "Final cut: source audio discarded (older assembly)",
  no_source_audio: "Final cut: silent (no source audio)",
  unknown: "Final cut audio unknown",
};

export const clipAudioClass = (hasAudio: boolean | null) =>
  hasAudio === true ? "has" : hasAudio === false ? "none" : "unknown";

const tick = (s: Stage) => (s.status === "complete" ? "✓" : s.status === "started" ? "…" : "○");

function NoData({ label }: { label: string }) {
  return (
    <div className="screen screen--nodata">
      <span className="screen__nodata-icon">◌</span>
      <span>No data source yet</span>
      <small>{label}</small>
    </div>
  );
}

/** The room's wall screen. Every number and image here comes from the snapshot. */
export function RoomScreen({ room, project, stages, budget, approvals, audio }: Props) {
  const mine = stages.filter((s) => s.room_id === room.id);
  const pending = approvals.filter((a) => a.status === "pending");

  switch (room.id) {
    case "command_deck":
      return (
        <div className="screen screen--command">
          <div className="command__stats">
            <div><b>{project.stages_complete}/{project.stages_total}</b><span>stages done</span></div>
            <div className={pending.length ? "is-attention" : ""}><b>{pending.length}</b><span>awaiting you</span></div>
            <div><b>{usd(budget?.spent_usd)}</b><span>spent</span></div>
            <div><b>{usd(budget?.remaining_usd)}</b><span>remaining</span></div>
          </div>
          <div className="command__stage">{project.production_stage}</div>
        </div>
      );

    case "story_lab": {
      const shots = stages.filter((s) => s.kind === "video");
      return (
        <div className="screen screen--list">
          {shots.slice(0, 8).map((s) => (
            <div key={s.key} className={`screen__row is-${s.status}`}>
              <span>{tick(s)}</span>
              <span className="screen__row-label">{splitLabel(s.label).tag}</span>
              <span className="screen__row-meta">{splitLabel(s.label).title}</span>
            </div>
          ))}
        </div>
      );
    }

    case "continuity_office": {
      const ref = mine[0];
      return (
        <div className="screen screen--media">
          {ref ? <StageThumb stage={ref} /> : <div className="thumb thumb--empty">No reference</div>}
          <div className="screen__caption">{ref ? "Location reference" : "—"}</div>
        </div>
      );
    }

    case "build_logic_workshop":
      return (
        <div className="screen screen--grid">
          {mine.map((s) => (
            <div key={s.key} className={`grid-cell is-${s.status}`} title={s.label}>
              <StageThumb stage={s} />
            </div>
          ))}
        </div>
      );

    case "finance_room": {
      if (!budget || budget.cap_usd == null) return <NoData label="No budget cap recorded" />;
      const pct = (n: number) => `${Math.min(100, (n / budget.cap_usd!) * 100)}%`;
      return (
        <div className="screen screen--finance">
          <div className="finance__row"><span>Spent</span><b>{usd(budget.spent_usd)}</b></div>
          <div className="finance__row"><span>Cap</span><b>{usd(budget.cap_usd)}</b></div>
          <div className="finance__bar">
            <span className="finance__spent" style={{ width: pct(budget.spent_usd) }} />
            <span className="finance__planned" style={{ width: pct(budget.planned_remaining_spend_usd) }} />
          </div>
          <div className="finance__row finance__row--small">
            <span>Planned next</span><b>{usd(budget.planned_remaining_spend_usd)}</b>
          </div>
        </div>
      );
    }

    case "render_bay":
      return (
        <div className="screen screen--list">
          {mine.map((s) => (
            <div key={s.key} className={`screen__row is-${s.status}`}>
              <span>{tick(s)}</span>
              <span className="screen__row-label">{splitLabel(s.label).tag}</span>
              <span className="screen__row-meta">
                {s.actual_cost_usd != null ? usd(s.actual_cost_usd) : s.planned_cost_usd != null ? `(${usd(s.planned_cost_usd)})` : ""}
              </span>
            </div>
          ))}
        </div>
      );

    case "edit_suite": {
      const clips = stages.filter((s) => s.kind === "video");
      const total = clips.reduce((n, s) => n + (s.duration_seconds ?? 5), 0) || 1;
      const assembly = mine[mine.length - 1];
      return (
        <div className="screen screen--timeline">
          <div className="timeline">
            {clips.map((s) => (
              <span
                key={s.key}
                className={`timeline__clip is-${s.status}`}
                style={{ flexGrow: (s.duration_seconds ?? 5) / total }}
                title={s.label}
              />
            ))}
          </div>
          <div className="screen__caption">
            {clips.filter((s) => s.status === "complete").length}/{clips.length} clips ·{" "}
            {assembly ? (assembly.status === "complete" ? "assembled" : "assembly pending") : "no assembly"}
          </div>
        </div>
      );
    }

    case "screening_room": {
      const a = pending[0];
      const stage = a && stages.find((s) => s.key === a.stage_key);
      if (!stage) {
        return (
          <div className="screen screen--nodata">
            <span className="screen__nodata-icon">✓</span>
            <span>Nothing awaiting review</span>
          </div>
        );
      }
      return (
        <div className="screen screen--media">
          <StageThumb stage={stage} />
          <div className="screen__caption is-attention">Awaiting your review</div>
        </div>
      );
    }

    case "library_archive": {
      const outputs = stages.filter((s) => s.latest_output_path);
      const videos = outputs.filter((s) => s.latest_output_name?.endsWith(".mp4")).length;
      const missing = stages.filter((s) => s.latest_output_exists === false || s.previous_frame_exists === false).length;
      return (
        <div className="screen screen--library">
          <div><b>{outputs.length - videos}</b><span>stills</span></div>
          <div><b>{videos}</b><span>clips</span></div>
          <div className={missing ? "is-attention" : ""}><b>{missing}</b><span>missing</span></div>
        </div>
      );
    }

    case "sound_booth": {
      if (!audio || !audio.ffprobe_available) return <NoData label="ffprobe not found - can't inspect audio" />;
      const found =
        audio.clips_total === 0
          ? "no clips yet"
          : audio.clips_with_audio === 0
            ? "none"
            : `${audio.clips_with_audio}/${audio.clips_total} clips`;
      return (
        <div className="screen screen--audio">
          <div className="audio__row">
            <span className="audio__label">Source audio</span>
            <b>{found}</b>
          </div>
          <div className="audio__clips">
            {audio.clips.map((c) => (
              <span key={c.stage_key} className={`audio__clip ${clipAudioClass(c.has_audio)}`} title={c.label} />
            ))}
          </div>
          <div className={`audio__final is-${audio.final_status}`}>{FINAL_AUDIO_TEXT[audio.final_status]}</div>
          <div className="audio__row audio__row--muted">
            <span className="audio__label">Additional sound design</span>
            <span>not implemented yet</span>
          </div>
        </div>
      );
    }

    default:
      return <NoData label="Nothing published yet" />;
  }
}
