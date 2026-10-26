import { useEffect, useRef, useState } from "react";
import { ApiError, api } from "../api";
import { timeAgo } from "../format";
import type { Execution, ManualStill, StillGeneration } from "../types";

const ACCEPT = ".jpg,.jpeg,.png,.webp";
const OK_EXT = /\.(jpe?g|png|webp)$/i;

const STATE_TEXT: Record<ManualStill["state"], string> = {
  missing: "Missing - upload it",
  placed: "Placed - review and approve",
  approved: "Approved",
  changed: "Changed since approval - review and approve",
  ambiguous: "Several files for one still - keep one",
};
const GEN_STATE_TEXT: Partial<Record<ManualStill["state"], string>> = {
  missing: "Not generated yet",
  placed: "Generated - review it",
};

const kb = (n: number | null) => (n == null ? "—" : n > 1_000_000 ? `${(n / 1_000_000).toFixed(1)} MB` : `${Math.round(n / 1000)} KB`);
const money = (n: number | null | undefined, digits = 4) => (n == null ? "—" : `$${n.toFixed(digits)}`);

interface Picked {
  file: File;
  url: string;
  width: number | null;
  height: number | null;
}

/** Generate (one confirmed fal call) or upload one still, then review and approve it. A person approves every still;
 * nothing is generated, approved or continued automatically. */
export function ManualStillPanel({
  projectSlug,
  still,
  execution,
  frozen = false,
  onChanged,
  onApprovedContinue,
}: {
  projectSlug: string;
  still: ManualStill;
  execution?: Execution;
  frozen?: boolean;
  onChanged: () => void;
  /** Approve & Continue: open the next still / clip (it does not generate or submit anything). */
  onApprovedContinue?: () => void;
}) {
  const [picked, setPicked] = useState<Picked | null>(null);
  const [confirmReplace, setConfirmReplace] = useState(false);
  const [note, setNote] = useState("");
  const [dragging, setDragging] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [problems, setProblems] = useState<string[]>([]);
  const input = useRef<HTMLInputElement>(null);

  const gen = still.generation;
  const generated = !!gen && gen.source_mode === "generate";

  useEffect(() => {
    setPicked(null);
    setConfirmReplace(false);
    setNote("");
    setError(null);
    setProblems([]);
  }, [still.key]);
  useEffect(
    () => () => {
      if (picked) URL.revokeObjectURL(picked.url);
    },
    [picked],
  );

  const exists = still.state !== "missing";
  const pick = (file: File | undefined) => {
    setError(null);
    if (!file) return;
    if (!OK_EXT.test(file.name)) {
      setError("Accepted formats: .jpg, .jpeg, .png, .webp");
      return;
    }
    const url = URL.createObjectURL(file);
    const img = new Image();
    img.onload = () => setPicked({ file, url, width: img.naturalWidth, height: img.naturalHeight });
    img.onerror = () => setPicked({ file, url, width: null, height: null });
    img.src = url; // state is set once, on load, so the preview URL is never revoked while shown
    setConfirmReplace(false);
  };

  const run = async (fn: () => Promise<unknown>, after?: () => void) => {
    setBusy(true);
    setError(null);
    setProblems([]);
    try {
      await fn();
      onChanged();
      after?.();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
      if (e instanceof ApiError) setProblems(e.problems);
    } finally {
      setBusy(false);
    }
  };

  const upload = () =>
    picked &&
    run(async () => {
      await api.uploadStill(projectSlug, still.key, picked.file, exists);
      setPicked(null);
      setConfirmReplace(false);
    });
  const approve = (andContinue: boolean) =>
    run(
      async () => {
        await api.approveStill(projectSlug, still.key, note);
        setNote("");
      },
      andContinue ? onApprovedContinue : undefined,
    );

  const uploadBox = (
    <>
      <div
        className={`mstill__drop ${dragging ? "is-dragging" : ""}`}
        onDragOver={(e) => {
          e.preventDefault();
          setDragging(true);
        }}
        onDragLeave={() => setDragging(false)}
        onDrop={(e) => {
          e.preventDefault();
          setDragging(false);
          pick(e.dataTransfer.files[0]);
        }}
      >
        <span>Drop an image here (e.g. made in ChatGPT), or</span>
        <button type="button" className="btn" onClick={() => input.current?.click()} disabled={busy}>
          Choose file…
        </button>
        <input ref={input} type="file" accept={ACCEPT} hidden onChange={(e) => pick(e.target.files?.[0] ?? undefined)} />
        <small>
          Saved as <code>{still.key}.jpg / .png / .webp</code> in <code>{still.expected_dir}</code>
        </small>
      </div>
      {picked && (
        <div className="mstill__confirm">
          <figure className="mstill__picked">
            <img src={picked.url} alt="selected file" />
            <figcaption>
              Selected: {picked.file.name} · {picked.width && picked.height ? `${picked.width}×${picked.height}` : "…"} · {kb(picked.file.size)}
            </figcaption>
          </figure>
          {exists && (
            <label className="mstill__replace">
              <input type="checkbox" checked={confirmReplace} onChange={(e) => setConfirmReplace(e.target.checked)} />
              Replace the current {still.state} file for {still.key}
              {still.state === "approved" ? " - it becomes “changed” and every clip that uses it is blocked until you approve the new image" : ""}.
              The old file is kept in stills/_replaced/.
            </label>
          )}
          <button type="button" className="btn btn--primary" disabled={busy || (exists && !confirmReplace)} onClick={upload}>
            {busy ? "Uploading…" : "Upload still"}
          </button>
          <button type="button" className="btn btn--ghost-inline" disabled={busy} onClick={() => setPicked(null)}>
            Cancel
          </button>
          <p className="fineprint">Uploading only places the file. It is not approved until you review it and approve it.</p>
        </div>
      )}
    </>
  );

  const stateText = (generated && GEN_STATE_TEXT[still.state]) || STATE_TEXT[still.state];

  return (
    <div className="mstill">
      <div className="mstill__head">
        <span className={`state-chip mstill__state is-${still.state}`}>{stateText}</span>
        <code className="mstill__key">{still.key}</code>
        {still.origin && <span className="fineprint">{still.origin}</span>}
      </div>

      <div className="mstill__media">
        {gen?.source && (
          <figure>
            {gen.source.url ? (
              <a href={gen.source.url} target="_blank" rel="noreferrer" title="Open full size">
                <img src={gen.source.url} alt={gen.source.key} />
              </a>
            ) : (
              <div className="thumb thumb--empty">{gen.source.key}: {gen.source.state}</div>
            )}
            <figcaption>
              Edits: {gen.source.key} ({gen.source.state})
            </figcaption>
          </figure>
        )}
        <figure>
          {still.url ? (
            <a href={still.url} target="_blank" rel="noreferrer" title="Open full size">
              <img src={still.url} alt={still.key} />
            </a>
          ) : (
            <div className="thumb thumb--empty">No file yet</div>
          )}
          <figcaption>This still</figcaption>
        </figure>
      </div>

      {generated && gen && !picked && (
        <GeneratePanel
          projectSlug={projectSlug}
          still={still}
          gen={gen}
          execution={execution}
          frozen={frozen}
          busy={busy}
          run={run}
        />
      )}

      {(still.state === "placed" || still.state === "changed") && !picked && (
        <div className="mstill__approve">
          <textarea
            className="note"
            rows={2}
            placeholder="What did you check? (required - e.g. same camera, pipe and builder; branch cut, leaf litter untouched)"
            value={note}
            onChange={(e) => setNote(e.target.value)}
          />
          <div className="mstill__row">
            {onApprovedContinue && (
              <button type="button" className="btn btn--primary" disabled={busy || !note.trim()} onClick={() => approve(true)}>
                Approve &amp; Continue
              </button>
            )}
            <button type="button" className={`btn ${onApprovedContinue ? "" : "btn--primary"}`} disabled={busy || !note.trim()} onClick={() => approve(false)}>
              Approve only
            </button>
          </div>
          <p className="fineprint">Continue only opens the next still or clip - it never generates or submits anything by itself.</p>
        </div>
      )}
      {error && <p className="confirm__problem">✕ {error}</p>}
      {problems.length > 0 && (
        <ul className="attn">
          {problems.map((p) => (
            <li key={p}>{p}</li>
          ))}
        </ul>
      )}

      {generated ? (
        <details className="intent" open={!!picked}>
          <summary>Optional override: upload your own still instead</summary>
          {uploadBox}
        </details>
      ) : (
        uploadBox
      )}

      <dl className="review__facts">
        <dt>Expected file</dt>
        <dd>
          <code>{still.expected_filename}</code>
        </dd>
        <dt>Dimensions</dt>
        <dd>{still.width && still.height ? `${still.width} × ${still.height}` : "—"}</dd>
        <dt>Type · size</dt>
        <dd>
          {still.file_type ?? "—"} · {kb(still.size_bytes)}
        </dd>
        <dt>SHA-256</dt>
        <dd>
          {still.sha256 ? <code title={still.sha256}>{still.sha256.slice(0, 16)}…</code> : "—"}
          {still.approved_sha256 && still.sha256 !== still.approved_sha256 ? (
            <span className="fineprint"> (approved: {still.approved_sha256.slice(0, 12)}…)</span>
          ) : null}
        </dd>
        <dt>Approved</dt>
        <dd>{still.approved_at ? `${timeAgo(still.approved_at)}${still.approval_note ? ` - “${still.approval_note}”` : ""}` : "no"}</dd>
        <dt>Uploaded</dt>
        <dd>{still.upload ? `${still.upload.original_filename}, ${timeAgo(still.upload.uploaded_at)}` : "—"}</dd>
        {gen && gen.attempts.length > 0 && (
          <>
            <dt>Generations</dt>
            <dd>
              {gen.attempts.map((a) => (
                <span key={a.key} className="mstill__use" title={a.error ?? ""}>
                  {a.key.split("__")[1]} {a.status} {money(a.cost_usd)}
                </span>
              ))}
            </dd>
          </>
        )}
        <dt>Used by</dt>
        <dd>
          {still.used_by.length === 0
            ? "no clips"
            : still.used_by.map((u) => (
                <span key={u.clip} className={`mstill__use ${u.stale ? "is-stale" : ""}`}>
                  {u.clip}
                  {u.stale ? " (stale - made from an older version)" : u.generated ? " (generated)" : ""}
                </span>
              ))}
        </dd>
      </dl>

      {still.brief && (
        <details className="intent">
          <summary>{generated ? "Prompt sent to fal (also usable as a ChatGPT brief)" : "ChatGPT brief for this still"}</summary>
          <p className="intent__prompt">{still.brief}</p>
        </details>
      )}
    </div>
  );
}

/** One confirmed image call: the first still from text, every later one an edit of the previous approved still. */
function GeneratePanel({
  projectSlug,
  still,
  gen,
  execution,
  frozen,
  busy,
  run,
}: {
  projectSlug: string;
  still: ManualStill;
  gen: StillGeneration;
  execution?: Execution;
  frozen: boolean;
  busy: boolean;
  run: (fn: () => Promise<unknown>) => Promise<void>;
}) {
  const [maxUsd, setMaxUsd] = useState("");
  const [confirm, setConfirm] = useState(false);

  useEffect(() => {
    setMaxUsd(gen.estimate_usd != null ? (Math.ceil(gen.estimate_usd * 100) / 100).toFixed(2) : "");
    setConfirm(false);
  }, [gen.key, gen.estimate_usd, still.sha256]);

  const mode = execution?.mode ?? "disabled";
  const paid = mode === "live";
  const blockers = [
    ...(frozen ? ["This project is frozen."] : []),
    ...(execution && !execution.launch_enabled ? execution.problems : []),
    ...gen.problems,
  ];
  const max = Number(maxUsd);
  const canGo = !busy && blockers.length === 0 && confirm && max > 0;
  const generate = () =>
    run(async () => {
      await api.generateStill(projectSlug, still.key, max, gen.exists);
      setConfirm(false);
    });

  return (
    <div className="mstill__gen">
      <p>
        {gen.mode === "generate" ? (
          <>
            <strong>Text-to-image</strong> (the first still) on <code>{gen.model}</code>
            {gen.references.length > 0 ? ` with ${gen.references.length} reference image(s)` : ""}.
          </>
        ) : (
          <>
            <strong>Image edit of {gen.source?.key}</strong> - its exact approved pixels - on <code>{gen.model}</code>. Camera,
            structure, environment, builder and lighting are kept; only this step's progress changes.
          </>
        )}
      </p>
      <p className="fineprint">
        Estimate {money(gen.estimate_usd)} {paid ? "(paid, live)" : mode === "mock" ? "- mock mode: $0, placeholder image" : ""} · model{" "}
        {gen.model_status.replace("_", " ")} · budget {money(gen.budget.spent_usd, 2)} spent of {money(gen.budget.cap_usd, 2)}
      </p>
      {gen.stale_source && (
        <p className="confirm__problem">! This still was generated from an older version of {gen.source?.key}. Regenerate it from the approved one.</p>
      )}
      {blockers.length > 0 && (
        <ul className="attn">
          {blockers.map((p) => (
            <li key={p}>{p}</li>
          ))}
        </ul>
      )}
      <div className="mstill__row">
        <label>
          Spend up to $
          <input
            className="mstill__usd"
            type="number"
            min="0.01"
            step="0.01"
            max={gen.per_still_max_usd}
            value={maxUsd}
            onChange={(e) => setMaxUsd(e.target.value)}
          />
        </label>
        <label className="mstill__replace">
          <input type="checkbox" checked={confirm} onChange={(e) => setConfirm(e.target.checked)} />
          {gen.exists
            ? `Replace the current ${still.state} file with a new generation (one call; the old file goes to stills/_replaced/)`
            : `Make one ${paid ? "paid " : ""}call for ${still.key}`}
        </label>
      </div>
      <button type="button" className="btn btn--primary" disabled={!canGo} onClick={generate}>
        {busy ? "Generating…" : gen.exists ? "Regenerate still" : "Generate still"}
      </button>
      <p className="fineprint">One click = one call. The result waits here for your review; nothing is approved or continued automatically.</p>
    </div>
  );
}
