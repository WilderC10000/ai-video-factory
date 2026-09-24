import { useCallback, useEffect, useRef, useState } from "react";
import { api } from "./api";
import { Building } from "./components/Building";
import { Inspector } from "./components/Inspector";
import { ActivityPanel, AttentionPanel, BudgetPanel, ProjectPanel } from "./components/Panels";
import { StoryboardStrip } from "./components/StoryboardStrip";
import type { Selection, Snapshot, Stage } from "./types";

const POLL_MS = 5000;
const POLL_ACTIVE_MS = 1500; // while a job runs, so phase changes show up promptly

// The open room/stage lives in the URL hash (#room=render_bay&stage=shot4) so it can be linked and survives reloads.
function readHash(): Selection | null {
  const params = new URLSearchParams(window.location.hash.slice(1));
  const roomId = params.get("room");
  return roomId ? { roomId, stageKey: params.get("stage") ?? undefined } : null;
}

function writeHash(sel: Selection | null) {
  const hash = sel ? `#room=${sel.roomId}${sel.stageKey ? `&stage=${sel.stageKey}` : ""}` : "";
  window.history.replaceState(null, "", `${window.location.pathname}${window.location.search}${hash}`);
}

function ExecutionBadge({ mode, problems }: { mode: string; problems: string[] }) {
  const label =
    mode === "live" ? "LIVE · paid calls enabled" : mode === "mock" ? "MOCK SANDBOX · no paid calls" : "EXECUTION OFF · review only";
  return (
    <span className={`mode-badge mode-badge--lg mode-badge--${mode}`} title={problems.join(" ") || label}>
      {label}
    </span>
  );
}

export function App() {
  const [snap, setSnap] = useState<Snapshot | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [selection, setSelectionState] = useState<Selection | null>(readHash);
  const [syncing, setSyncing] = useState(false);
  const slugRef = useRef<string | undefined>(undefined);

  const setSelection = useCallback((sel: Selection | null) => {
    setSelectionState(sel);
    writeHash(sel);
  }, []);

  const load = useCallback(async () => {
    try {
      const next = await api.snapshot(slugRef.current);
      setSnap(next);
      setError(null);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    }
  }, []);

  const jobRunning = !!snap?.active_job;
  useEffect(() => {
    load();
    const id = window.setInterval(load, jobRunning ? POLL_ACTIVE_MS : POLL_MS);
    return () => window.clearInterval(id);
  }, [load, jobRunning]);

  const switchProject = async (slug: string) => {
    slugRef.current = slug;
    setSelection(null);
    await api.activate(slug).catch(() => undefined);
    await load();
  };

  const resync = async () => {
    setSyncing(true);
    try {
      await api.reimport();
      await load();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setSyncing(false);
    }
  };

  const openRoom = (roomId: string, stageKey?: string) => setSelection({ roomId, stageKey });
  const openStage = (s: Stage) => setSelection({ roomId: s.room_id, stageKey: s.key });
  const close = useCallback(() => setSelection(null), [setSelection]);

  if (!snap) {
    return (
      <div className="splash">
        {error ? (
          <>
            <b>Can't reach the studio backend.</b>
            <span>{error}</span>
            <code>python -m uvicorn app.main:app --reload --port 8000</code>
          </>
        ) : (
          "Loading studio…"
        )}
      </div>
    );
  }

  if (!snap.project || !snap.rooms) {
    return (
      <div className="splash">
        <b>No productions imported yet.</b>
        <span>Import the real FORMA manifests (read-only), then refresh:</span>
        <code>python -m scripts.studio_import</code>
        <button type="button" className="btn" onClick={resync} disabled={syncing}>
          {syncing ? "Importing…" : "Import now"}
        </button>
      </div>
    );
  }

  const full = snap as Required<Snapshot>;
  const roomNames = Object.fromEntries(full.rooms.map((r) => [r.id, r.name]));

  return (
    <div className={`app ${selection ? "has-inspector" : ""}`}>
      <header className="topbar">
        <div className="topbar__brand">
          <span className="topbar__logo">FORMA</span>
          <span className="topbar__title">Virtual Studio</span>
          <span className="topbar__version">v0.2 · control room</span>
        </div>
        <div className="topbar__project">
          <span className="topbar__label">Now producing</span>
          <b>{full.project!.name}</b>
        </div>
        <ExecutionBadge mode={full.execution.mode} problems={full.execution.problems} />
        {error && <span className="topbar__error">Connection issue: {error}</span>}
      </header>

      <main className="layout">
        <div className="layout__world">
          <Building snap={full} selection={selection} onSelectRoom={(id) => openRoom(id)} onSelectStage={openStage} />
        </div>
        <div className="layout__side">
          <ProjectPanel
            project={full.project!}
            projects={full.projects}
            stages={full.stages}
            syncing={syncing}
            onSwitch={switchProject}
            onResync={resync}
            onSelectStage={openStage}
          />
          <BudgetPanel budget={full.budget} />
          <AttentionPanel approvals={full.approvals} events={full.events} onOpen={openRoom} />
          <ActivityPanel events={full.events} roomNames={roomNames} onOpen={openRoom} />
        </div>
        <div className="layout__strip">
          <StoryboardStrip
            stages={full.stages}
            currentKey={full.project!.current_stage_key}
            workingKey={full.active_job?.stage_key ?? null}
            selectedStage={selection?.stageKey}
            onSelect={openStage}
          />
        </div>
      </main>

      {selection && (
        <Inspector
          selection={selection}
          projectSlug={full.project!.slug}
          rooms={full.rooms}
          stages={full.stages}
          approvals={full.approvals}
          events={full.events}
          budget={full.budget}
          execution={full.execution}
          activeJob={full.active_job ?? null}
          audio={full.audio}
          onSelectStage={openStage}
          onChanged={load}
          onClose={close}
        />
      )}
    </div>
  );
}
