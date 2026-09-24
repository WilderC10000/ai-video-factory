import { useEffect } from "react";
import { SEVERITY_LABEL, STATUS_LABEL, timeAgo } from "../format";
import type { Approval, AudioReport, Budget, Execution, Job, Room, Selection, Stage, StudioEvent } from "../types";
import { Avatar } from "./Avatar";
import { JobProgress } from "./JobProgress";
import { ReviewPanel } from "./ReviewPanel";
import { FINAL_AUDIO_TEXT, clipAudioClass } from "./RoomScreen";
import { ROOM_ACCENT } from "./RoomCard";

interface Props {
  selection: Selection;
  projectSlug: string;
  rooms: Room[];
  stages: Stage[];
  approvals: Approval[];
  events: StudioEvent[];
  budget: Budget | null;
  execution: Execution;
  activeJob: Job | null;
  audio?: AudioReport;
  onSelectStage: (stage: Stage) => void;
  onChanged: () => void;
  onClose: () => void;
}

function Ref({ label, value, empty }: { label: string; value: React.ReactNode; empty: string }) {
  return (
    <div className="ref">
      <span className="ref__label">{label}</span>
      {value ?? <span className="ref__empty">{empty}</span>}
    </div>
  );
}

function FilePath({ path, exists }: { path: string; exists?: boolean | null }) {
  return (
    <li className={`file ${exists === false ? "is-missing" : ""}`}>
      <code>{path}</code>
      {exists === false && <span className="sev-chip sev--medium">missing</span>}
    </li>
  );
}

function probeText(c: AudioReport["clips"][number]): string {
  if (c.has_audio === true) return `${c.codec ?? "audio"} · ${c.channels ?? "?"}ch · ${c.sample_rate ?? "?"} Hz`;
  if (c.has_audio === false) return "no audio stream";
  return `unknown (${c.error})`;
}

function AudioDetails({
  audio,
  stages,
  onSelectStage,
}: {
  audio: AudioReport;
  stages: Stage[];
  onSelectStage: (s: Stage) => void;
}) {
  return (
    <div className="audio-report">
      <h3>Source audio</h3>
      <p className="fineprint">Audio already embedded in the generated clips, read from each file with ffprobe.</p>
      <ul className="audio-list">
        {audio.clips.map((c) => {
          const stage = stages.find((s) => s.key === c.stage_key);
          return (
            <li key={c.stage_key}>
              <button type="button" className="audio-list__item" onClick={() => stage && onSelectStage(stage)}>
                <span className={`audio__clip ${clipAudioClass(c.has_audio)}`} />
                <span className="audio-list__label">{c.label}</span>
                <span className="audio-list__meta">{probeText(c)}</span>
              </button>
            </li>
          );
        })}
        {audio.clips.length === 0 && <li className="ref__empty">No generated clips yet.</li>}
      </ul>

      <h3>Final Assembly</h3>
      <p className={`audio__final is-${audio.final_status}`}>{FINAL_AUDIO_TEXT[audio.final_status]}</p>
      {audio.final && (
        <p className="fineprint">
          <code>{audio.final.file}</code>: {probeText(audio.final)}
        </p>
      )}
      <p className="fineprint">{audio.assembly_code_note}</p>

      <h3>Additional sound design</h3>
      <p className="ref__empty">
        Not implemented yet - deliberate post-production audio (music, SFX, voice) on top of the source audio.
      </p>
    </div>
  );
}

function StageRecord({ stage }: { stage: Stage }) {
  const severity = (sev: string | null, note: string | null) =>
    sev ? (
      <span>
        <span className={`sev-chip sev--${sev}`}>{sev}</span> {note}
      </span>
    ) : null;
  return (
    <div className="refs">
      <Ref label="Pipeline status" value={<b className={`stage-status is-${stage.status}`}>{stage.status}</b>} empty="" />
      <Ref label="Approval" value={stage.approval_state && <b>{stage.approval_state}</b>} empty="No gate yet" />
      <Ref label="Continuity" value={severity(stage.continuity_severity, stage.continuity_note)} empty="Not reviewed yet (no continuity agent)" />
      <Ref label="Build logic" value={severity(stage.build_logic_severity, stage.build_logic_note)} empty="Not reviewed yet (no build-logic agent)" />
      <Ref label="Model" value={stage.model && <code>{stage.model}</code>} empty="—" />
      <Ref label="Completed" value={stage.completed_at && <span>{timeAgo(stage.completed_at)}</span>} empty="—" />
      {stage.provider_job_id && <Ref label="Provider job" value={<code>{stage.provider_job_id}</code>} empty="" />}
      {stage.error_message && <Ref label="Error" value={<span className="is-critical">{stage.error_message}</span>} empty="" />}
    </div>
  );
}

export function Inspector({
  selection,
  projectSlug,
  rooms,
  stages,
  approvals,
  events,
  budget,
  execution,
  activeJob,
  audio,
  onSelectStage,
  onChanged,
  onClose,
}: Props) {
  const room = rooms.find((r) => r.id === selection.roomId);
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);
  if (!room) return null;

  const { agent } = room;
  const roomStages = stages.filter((s) => s.room_id === room.id);
  // Default to what needs you here: a running job, then an output awaiting review, then the next stage.
  const stage =
    stages.find((s) => s.key === selection.stageKey) ??
    roomStages.find((s) => activeJob?.stage_key === s.key) ??
    roomStages.find((s) => s.requires_human_review) ??
    roomStages.find((s) => s.status !== "complete") ??
    roomStages[roomStages.length - 1];
  const warnings = events.filter((e) => e.room_id === room.id && e.severity !== "info");
  const stageKeys = new Set(roomStages.map((s) => s.key));
  const decisions = approvals.filter(
    (a) => a.room_id === room.id || (a.stage_key && stageKeys.has(a.stage_key)) || (room.id === "command_deck" && a.status === "pending"),
  );
  const files = [
    ...new Map(
      roomStages.flatMap((s) => [
        ...(s.latest_output_path ? [[s.latest_output_path, s.latest_output_exists] as const] : []),
        ...(s.previous_frame_path ? [[s.previous_frame_path, s.previous_frame_exists] as const] : []),
      ]),
    ),
  ].map(([path, exists]) => ({ path, exists }));
  const scripts = [...new Set(roomStages.map((s) => s.script_path).filter(Boolean))] as string[];

  return (
    <aside className="inspector" style={{ ["--accent" as string]: ROOM_ACCENT[room.id] }} aria-label={`${room.name} inspector`}>
      <header className="inspector__head">
        <Avatar status={agent.status} accent={ROOM_ACCENT[room.id]} needsYou={agent.requires_human_review} size={48} />
        <div>
          <div className="inspector__room">{room.name}</div>
          <div className="inspector__agent">
            {agent.name} · <span>{agent.role}</span>
          </div>
        </div>
        <button type="button" className="inspector__close" onClick={onClose} aria-label="Close inspector">
          ×
        </button>
      </header>

      <div className="inspector__body">
        <div className="inspector__status">
          <span className={`status-pill status--${agent.status}`}>
            <span className="status-dot" />
            {STATUS_LABEL[agent.status]}
          </span>
          {agent.requires_human_review && <span className="needs-you">Waiting on you</span>}
        </div>
        {agent.status_reason && <p className="inspector__reason">{agent.status_reason}</p>}
        {!room.data_source && <p className="fineprint">This room has no real data source in v0.1, so it stays idle.</p>}
        {activeJob && room.id === "command_deck" && <JobProgress job={activeJob} compact />}
        {room.id === "sound_booth" && audio && <AudioDetails audio={audio} stages={stages} onSelectStage={onSelectStage} />}

        {stage && (
          <>
            {roomStages.length > 1 && (
              <div className="chips chips--top">
                {roomStages.map((s) => (
                  <button
                    key={s.key}
                    type="button"
                    className={`chip is-${s.status} ${s.key === stage.key ? "is-active" : ""} ${s.requires_human_review ? "is-needs-you" : ""}`}
                    onClick={() => onSelectStage(s)}
                  >
                    {s.label.split(" - ")[0]}
                  </button>
                ))}
              </div>
            )}
            <ReviewPanel
              projectSlug={projectSlug}
              stage={stage}
              stages={stages}
              budget={budget}
              execution={execution}
              activeJob={activeJob}
              onChanged={onChanged}
            />
          </>
        )}

        <h3>Current task</h3>
        <p>{agent.current_task ?? <span className="ref__empty">None</span>}</p>
        <h3>Next expected action</h3>
        <p>{agent.next_action ?? <span className="ref__empty">None</span>}</p>

        {stage && (
          <>
            <h3>Stage record</h3>
            <StageRecord stage={stage} />
          </>
        )}

        <h3>Warnings &amp; errors</h3>
        {warnings.length === 0 ? (
          <p className="ref__empty">None</p>
        ) : (
          <ul className="attn">
            {warnings.map((e) => (
              <li key={e.id} className="attn__item attn__item--static">
                <span className={`sev-chip sev--${e.severity}`}>{SEVERITY_LABEL[e.severity]}</span>
                <span className="attn__text">{e.message}</span>
              </li>
            ))}
          </ul>
        )}

        <h3>Recent decisions</h3>
        {decisions.length === 0 ? (
          <p className="ref__empty">None</p>
        ) : (
          <ul className="decisions">
            {decisions.slice(-8).reverse().map((a) => (
              <li key={a.id} className={`is-${a.status}`}>
                <b>{a.status}</b>
                <span>{a.title}</span>
                {a.decided_via === "pipeline" && <small>inferred from the pipeline's review gate</small>}
              </li>
            ))}
          </ul>
        )}

        <h3>Relevant files</h3>
        {files.length === 0 && scripts.length === 0 ? (
          <p className="ref__empty">None</p>
        ) : (
          <ul className="files">
            {scripts.map((p) => (
              <FilePath key={p} path={p} />
            ))}
            {files.map((f) => (
              <FilePath key={f.path + String(f.exists)} path={f.path} exists={f.exists} />
            ))}
          </ul>
        )}
      </div>
    </aside>
  );
}
