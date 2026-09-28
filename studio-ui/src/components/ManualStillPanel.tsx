import { useEffect, useRef, useState } from "react";
import { api } from "../api";
import { timeAgo } from "../format";
import type { ManualStill } from "../types";

const ACCEPT = ".jpg,.jpeg,.png,.webp";
const OK_EXT = /\.(jpe?g|png|webp)$/i;

const STATE_TEXT: Record<ManualStill["state"], string> = {
  missing: "Missing - upload it",
  placed: "Placed - review and approve",
  approved: "Approved",
  changed: "Changed since approval - review and approve",
  ambiguous: "Several files for one still - keep one",
};

const kb = (n: number | null) => (n == null ? "—" : n > 1_000_000 ? `${(n / 1_000_000).toFixed(1)} MB` : `${Math.round(n / 1000)} KB`);

interface Picked {
  file: File;
  url: string;
  width: number | null;
  height: number | null;
}

/** Upload / review / approve one manual (ChatGPT) still. Local only: nothing is generated or sent to a provider. */
export function ManualStillPanel({ projectSlug, still, onChanged }: { projectSlug: string; still: ManualStill; onChanged: () => void }) {
  const [picked, setPicked] = useState<Picked | null>(null);
  const [confirmReplace, setConfirmReplace] = useState(false);
  const [note, setNote] = useState("");
  const [dragging, setDragging] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const input = useRef<HTMLInputElement>(null);

  useEffect(() => {
    setPicked(null);
    setConfirmReplace(false);
    setNote("");
    setError(null);
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

  const run = async (fn: () => Promise<unknown>) => {
    setBusy(true);
    setError(null);
    try {
      await fn();
      onChanged();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
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
  const approve = () =>
    run(async () => {
      await api.approveStill(projectSlug, still.key, note);
      setNote("");
    });

  return (
    <div className="mstill">
      <div className="mstill__head">
        <span className={`state-chip mstill__state is-${still.state}`}>{STATE_TEXT[still.state]}</span>
        <code className="mstill__key">{still.key}</code>
      </div>

      <div className="mstill__media">
        <figure>
          {still.url ? (
            <a href={still.url} target="_blank" rel="noreferrer" title="Open full size">
              <img src={still.url} alt={still.key} />
            </a>
          ) : (
            <div className="thumb thumb--empty">No file yet</div>
          )}
          <figcaption>In the stills folder</figcaption>
        </figure>
        {picked && (
          <figure className="mstill__picked">
            <img src={picked.url} alt="selected file" />
            <figcaption>
              Selected: {picked.file.name} · {picked.width && picked.height ? `${picked.width}×${picked.height}` : "…"} · {kb(picked.file.size)}
            </figcaption>
          </figure>
        )}
      </div>

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
        <span>Drop the ChatGPT image here, or</span>
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
          <p className="fineprint">Uploading only places the file. It is not approved until you review it and click Approve still.</p>
        </div>
      )}

      {(still.state === "placed" || still.state === "changed") && !picked && (
        <div className="mstill__approve">
          <textarea
            className="note"
            rows={2}
            placeholder="What did you check? (required - e.g. camera, railcar and builder match; clearing to window 3)"
            value={note}
            onChange={(e) => setNote(e.target.value)}
          />
          <button type="button" className="btn btn--primary" disabled={busy || !note.trim()} onClick={approve}>
            Approve still
          </button>
        </div>
      )}
      {error && <p className="confirm__problem">✕ {error}</p>}

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
          <summary>ChatGPT brief for this still</summary>
          <p className="intent__prompt">{still.brief}</p>
        </details>
      )}
    </div>
  );
}
