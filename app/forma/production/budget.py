"""Budget controls: a project cap, a per-clip ceiling, and a person's approval for every single submission.

    manifest["clip_budget"][<clip>] = {"max_usd", "note", "approved_at", "consumed_by": None | attempt key}

One approval pays for ONE submission. When that job fails, is rejected or is cancelled, nothing is retried:
the clip needs a new approval (there are no automatic retries anywhere in the engine).

Spend is counted the same way everywhere in the repo: the sum of every manifest entry's actual_cost_usd.
In-flight jobs reserve their estimate so two submissions can never overrun the cap together.
"""
import json
import os
from datetime import datetime, timezone
from pathlib import Path

from app.forma.production.spec import ProjectSpec
from app.studio.attempt_status import is_unfinished


class BudgetError(Exception):
    def __init__(self, message: str, status: int = 409):
        super().__init__(message)
        self.status = status


def spend(manifest: dict, spec: ProjectSpec) -> dict:
    spent = round(sum(v.get("actual_cost_usd") or 0.0 for v in manifest.values() if isinstance(v, dict)), 4)
    reserved = round(sum(v.get("estimated_cost_usd") or 0.0 for v in manifest.values()
                         if isinstance(v, dict) and is_unfinished(v)), 4)
    return {"cap_usd": spec.budget_cap_usd, "per_clip_max_usd": spec.per_clip_max_usd, "spent_usd": spent,
            "reserved_usd": reserved, "remaining_usd": round(spec.budget_cap_usd - spent - reserved, 4)}


def open_approval(manifest: dict, clip_key: str) -> dict | None:
    rec = (manifest.get("clip_budget") or {}).get(clip_key)
    return rec if rec and not rec.get("consumed_by") else None


def approve(manifest_path: Path, spec: ProjectSpec, clip_key: str, max_usd: float, note: str) -> dict:
    """A person approves spending up to max_usd on ONE submission of this clip."""
    spec.clip(clip_key)  # must be a clip of this project
    if not note.strip():
        raise BudgetError("Say why this spend is approved (a short note).", 400)
    if not 0 < max_usd <= spec.per_clip_max_usd:
        raise BudgetError(f"Approve between $0.01 and the per-clip ceiling ${spec.per_clip_max_usd:.2f}.", 400)
    manifest = json.loads(Path(manifest_path).read_text())
    rec = {"max_usd": round(float(max_usd), 4), "note": note.strip(),
           "approved_at": datetime.now(timezone.utc).isoformat(), "consumed_by": None}
    manifest.setdefault("clip_budget", {})[clip_key] = rec
    tmp = Path(manifest_path).with_suffix(".json.tmp")
    tmp.write_text(json.dumps(manifest, indent=2))
    os.replace(tmp, manifest_path)
    return rec


def submit_problems(manifest: dict, spec: ProjectSpec, clip_key: str, estimate_usd: float) -> list[str]:
    """Why this clip may NOT be submitted right now (empty = the money side is fine)."""
    problems = []
    rec = open_approval(manifest, clip_key)
    if rec is None:
        problems.append("No open spend approval for this clip - approve an amount first (one approval = one job).")
    elif estimate_usd > rec["max_usd"] + 1e-9:
        problems.append(f"Estimate ${estimate_usd:.4f} is above the approved ${rec['max_usd']:.2f}.")
    if estimate_usd > spec.per_clip_max_usd + 1e-9:
        problems.append(f"Estimate ${estimate_usd:.4f} is above the per-clip ceiling ${spec.per_clip_max_usd:.2f}.")
    s = spend(manifest, spec)
    if estimate_usd > s["remaining_usd"] + 1e-9:
        problems.append(f"Project cap: ${s['spent_usd']:.2f} spent + ${s['reserved_usd']:.2f} in flight + "
                        f"${estimate_usd:.4f} would exceed ${s['cap_usd']:.2f}.")
    return problems
