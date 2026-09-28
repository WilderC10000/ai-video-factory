"""Still and clip state machines - derived only from files on disk and the manifest (restart-proof).

STILL   missing --upload--> placed --approve--> approved --upload(replace)--> changed --approve--> approved

CLIP    blocked         a start/end still is not approved, or the spec has errors
          | stills approved
        ready           can be priced; needs a person's spend approval
          | approve budget (one approval = one job)
        budget_approved
          | submit (the only paid step; live execution only)
        submitted -> queued -> generating -> downloading     (fal status, persisted by free checks)
          |
        review          a video exists; a person watches it
          | accept                     | reject -> ready (new approval needed; never auto-retried)
        accepted
        a failed / cancelled job -> ready (no video; new approval needed)

A clip whose accepted attempt was generated from a still that has since changed is `stale`.
"""
from pathlib import Path

from app.forma.production import budget, stills
from app.forma.production.spec import Clip, ProjectSpec
from app.studio.attempt_status import attempt_phase

# A rejected / failed / cancelled attempt returns the clip to ready (or blocked) with the reason attached.
CLIP_STATES = ("blocked", "ready", "budget_approved", "submitted", "queued", "generating", "downloading",
               "review", "accepted", "stale")


def attempts(manifest: dict, clip_key: str) -> list[tuple[str, dict]]:
    found = [(k, v) for k, v in manifest.items() if isinstance(v, dict) and k.startswith(f"{clip_key}__attempt")]
    return sorted(found, key=lambda kv: int(kv[0].rpartition("attempt")[2] or 0))


def _output_exists(entry: dict) -> bool:
    return bool(entry.get("raw_video_path")) and Path(entry["raw_video_path"]).is_file()


def clip_state(spec: ProjectSpec, manifest_path: Path, manifest: dict, clip: Clip,
               spec_errors: bool = False) -> dict:
    still_states = {k: stills.state(manifest_path, k, manifest)["state"] for k in (clip.start_still, clip.end_still)}
    primary = manifest.get(clip.key) if isinstance(manifest.get(clip.key), dict) else None
    tries = attempts(manifest, clip.key)
    latest_key, latest = tries[-1] if tries else (None, None)
    reasons = []
    if primary and primary.get("accepted_at"):
        used = {primary.get("start_frame_sha256"), primary.get("end_frame_sha256")}
        current = {stills.state(manifest_path, k, manifest).get("sha256") for k in (clip.start_still, clip.end_still)}
        if not current <= used or any(s != "approved" for s in still_states.values()):
            return {"state": "stale", "attempt": primary.get("accepted_attempt"),
                    "reasons": ["An anchor still changed after this clip was accepted - regenerate it."]}
        return {"state": "accepted", "attempt": primary.get("accepted_attempt"), "reasons": []}
    if latest is not None:
        phase = attempt_phase(latest, _output_exists(latest))
        review = (latest.get("review") or {}).get("verdict")
        if phase in ("submitted", "queued", "generating", "downloading"):
            return {"state": phase, "attempt": latest_key, "reasons": []}
        if phase == "complete" and review is None:
            return {"state": "review", "attempt": latest_key, "reasons": []}
        if phase in ("failed", "cancelled") or review == "rejected":
            reasons.append(f"Last attempt {latest_key} {'was rejected' if review == 'rejected' else phase} - "
                           "a new spend approval is needed (no automatic retries).")
    if spec_errors:
        return {"state": "blocked", "attempt": latest_key, "reasons": ["The project spec has doctrine errors."]}
    unapproved = [f"{k} is {s}" for k, s in still_states.items() if s != "approved"]
    if unapproved:
        return {"state": "blocked", "attempt": latest_key, "reasons": unapproved + reasons}
    if budget.open_approval(manifest, clip.key):
        return {"state": "budget_approved", "attempt": latest_key, "reasons": reasons}
    return {"state": "ready", "attempt": latest_key, "reasons": reasons}
