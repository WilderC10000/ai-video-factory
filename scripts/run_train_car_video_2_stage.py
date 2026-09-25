#!/usr/bin/env python3
"""FORMA VIDEO #2 (TRAIN CAR) - RUN ONE STAGE (incremental, gated).

Runs exactly ONE stage of the 20-checkpoint plan (scripts/run_train_car_video_2_plan.py)
through the shared pipeline functions (execute_generate / execute_edit /
execute_video_shot). The same SPECS drive the FORMA Virtual Studio, which is the
intended way to run this project: GENERATE STILL -> REVIEW -> APPROVE -> GENERATE
CLIP -> REVIEW -> APPROVE -> NEXT CHECKPOINT.

MANUAL STILLS (plan.STILLS_SOURCE == "manual", the current setting): stills are made and
approved in ChatGPT, never generated here. The stills folder is the source of truth:
  1. `--still-brief cp04_still` prints what the still must show (paste into ChatGPT);
  2. save the result as stills/cp04_still.jpg (or .png / .webp) - exactly one file per key;
  3. `--approve-still cp04_still "<what you checked>"` records its sha256 (free, no API call);
  4. a clip may only run when its start/end stills are approved AND unchanged since approval -
     replacing a file after approval blocks the clip until it is approved again.
Iterating on a still never spends money; only clips do.

Gates, enforced here and in the studio:
  - stages run strictly in plan.execution_order(); each needs its predecessor done
    (manual stills: each clip needs the previous clip done and its own stills approved);
  - the hard budget cap in data/train_car_video_2/manifest.json ($15.00);
  - PROOF GATE: nothing ordered after clip03 (the first CP02 -> CP03 end-frame test)
    may run until `--pass-proof "<why>"` is recorded after reviewing it.

Usage (from the repo root):
    python -m scripts.run_train_car_video_2_stage --status
    python -m scripts.run_train_car_video_2_stage cp01_still          # asks before spending
    python -m scripts.run_train_car_video_2_stage --pass-proof "end frame held, railcar stable"
    python -m scripts.run_train_car_video_2_stage --stills                 # every still: path + state
    python -m scripts.run_train_car_video_2_stage --still-brief cp04_still
    python -m scripts.run_train_car_video_2_stage --approve-still cp04_still "railcar matches, deck absent"
"""
import argparse
import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

from app.config import settings
from scripts import run_train_car_video_2_plan as plan
from scripts.run_alpine_video_2_common import (
    EditSpec,
    ImageGenerateSpec,
    PipelineStepError,
    VideoShotSpec,
    execute_edit,
    execute_generate,
    execute_video_shot,
    recover_video_shot,
    spent_so_far,
)

OUTPUT_DIR = plan.OUTPUT_DIR
MANIFEST_PATH = OUTPUT_DIR / "manifest.json"
STILLS_DIR = OUTPUT_DIR / "stills"
CLIPS_DIR = OUTPUT_DIR / "clips"

STAGES = {s.key: s for s in plan.build_stage_plan()}
ORDER = plan.execution_order(list(STAGES.values()))


def still_path(key: str) -> Path:
    """Where a generated (API) still is written, and the default name for a manual one."""
    return STILLS_DIR / f"{key}.jpg"


STILL_EXTENSIONS = (".jpg", ".jpeg", ".png", ".webp")


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def still_state(key: str, manifest: dict, stills_dir: Path = STILLS_DIR) -> dict:
    """What is in the stills folder for this key versus what was approved.

    state: missing | ambiguous (several files for one key) | placed (not approved yet) |
           approved | changed (the file is not the one that was approved - approve it again)."""
    files = [stills_dir / f"{key}{ext}" for ext in STILL_EXTENSIONS if (stills_dir / f"{key}{ext}").is_file()]
    entry = manifest.get(key) if isinstance(manifest.get(key), dict) else {}
    if len(files) > 1:
        return {"state": "ambiguous", "paths": [str(f) for f in files]}
    if not files:
        return {"state": "missing", "expected": str(stills_dir / f"{key}.jpg")}
    path, digest = files[0], _sha256(files[0])
    approved = entry.get("approved_sha256")
    if approved is None:
        state = "placed"
    elif approved == digest and Path(entry.get("output_path", "")) == path:
        state = "approved"
    else:
        state = "changed"
    return {"state": state, "path": str(path), "sha256": digest}


def approved_still(key: str, manifest_path: Path = MANIFEST_PATH) -> tuple[Path, str]:
    """The exact approved file (and its sha256) for a still - what a clip must use as a frame."""
    st = still_state(key, _manifest(manifest_path), _stills_dir(manifest_path))
    if st["state"] != "approved":
        raise PipelineStepError(f"{key}: {_describe_still(key, st)}")
    return Path(st["path"]), st["sha256"]


def _stills_dir(manifest_path: Path) -> Path:
    """The stills folder that belongs to this manifest (the real one, or a studio sandbox copy)."""
    return Path(manifest_path).parent / "stills"


def _describe_still(key: str, st: dict) -> str:
    name = Path(st.get("path", "")).name
    return {
        "missing": f"no still yet - save it as {st.get('expected')} (or .png/.webp)",
        "ambiguous": f"several files for one still ({', '.join(Path(p).name for p in st.get('paths', []))}) - keep one",
        "placed": f'{name} is placed but not approved - run --approve-still {key} "<note>"',
        "changed": f'{name} is not the file that was approved - review it and run --approve-still {key} "<note>" again',
        "approved": "approved",
    }[st["state"]]


def _next_attempt_key(manifest: dict, key: str) -> str:
    n = 1
    while f"{key}__attempt{n}" in manifest:
        n += 1
    return f"{key}__attempt{n}"


def approve_still(key: str, note: str, *, manifest_path: Path = MANIFEST_PATH, source: str = "manual") -> dict:
    """Record the still currently in the stills folder as approved (free - no API call).

    A previously recorded still that is a different file is archived as <key>__attemptN (its cost,
    if it was generated, stays counted). Returns the entry plus any completed clips now stale."""
    stage = STAGES.get(key)
    if stage is None or stage.kind == "video":
        raise PipelineStepError(f"{key!r} is not a still stage of the train-car plan.")
    if not note.strip():
        raise PipelineStepError("Say what you checked (a short note) when approving a still.")
    manifest = _manifest(manifest_path)
    st = still_state(key, manifest, _stills_dir(manifest_path))
    if st["state"] in ("missing", "ambiguous"):
        raise PipelineStepError(f"{key}: {_describe_still(key, st)}")
    now = datetime.now(timezone.utc).isoformat()
    entry = manifest.get(key) if isinstance(manifest.get(key), dict) else None
    same_file = (entry is not None and Path(entry.get("output_path", "")) == Path(st["path"])
                 and entry.get("approved_sha256") in (None, st["sha256"]))
    if entry is not None and not same_file:
        manifest[_next_attempt_key(manifest, key)] = entry | {"archived_at": now,
                                                               "archive_reason": "replaced by a newer still"}
        entry = None
    if entry is None:
        entry = {"source": source, "output_path": st["path"], "actual_cost_usd": 0.0, "completed_at": now}
    entry.update(approved_sha256=st["sha256"], approved_at=now, approved_via="manual", approval_note=note.strip())
    manifest[key] = entry
    manifest_path.write_text(json.dumps(manifest, indent=2))
    stale = [k for k, s in STAGES.items() if s.kind == "video" and key in (s.source, s.end_frame)
             and _completed(manifest.get(k))
             and manifest[k].get("start_frame_sha256" if s.source == key else "end_frame_sha256") not in (None, st["sha256"])]
    return {"key": key, **entry, "stale_clips": stale}


def _note(key: str) -> str:
    i = ORDER.index(key)
    nxt = ORDER[i + 1] if i + 1 < len(ORDER) else None
    if key == plan.PROOF_STAGE:
        return ("PROOF GATE: review this clip against the checklist. Nothing further runs until you record "
                "`--pass-proof` (or stop here and report).")
    return f"Review it before running the next stage ({nxt})." if nxt else "Last stage of the plan."


def _build_spec(stage: plan.Stage):
    prompt = plan.stage_prompt(stage)
    if stage.kind == "image_generate":
        return ImageGenerateSpec(
            key=stage.key, title=stage.label, prompt=prompt, output_image_path=still_path(stage.key),
            max_spend_usd=plan.PRICE_IMAGE_GENERATE_USD, review_checklist=plan.STILL_REVIEW_CHECKLIST,
            next_step_note=_note(stage.key),
        )
    if stage.kind == "image_edit":
        source = still_path(stage.source)
        return EditSpec(
            edit_key=stage.key, title=stage.label, upstream_path=source, upstream_label=STAGES[stage.source].label,
            needs_frame_extraction=False, start_frame_path=source, edit_prompt=prompt,
            output_image_path=still_path(stage.key), max_spend_usd=plan.PRICE_IMAGE_EDIT_USD,
            review_checklist=plan.STILL_REVIEW_CHECKLIST, next_step_note=_note(stage.key),
        )
    start = _frame_file(stage.source)
    return VideoShotSpec(
        shot_key=stage.key, title=stage.label, upstream_path=start, upstream_label=STAGES[stage.source].label,
        needs_frame_extraction=False, start_frame_path=start, prompt=prompt,
        duration_seconds=float(stage.raw_seconds), max_spend_usd=stage.estimated_cost_usd,
        raw_output_path=CLIPS_DIR / f"{stage.key}_raw.mp4", job_state_path=CLIPS_DIR / f"{stage.key}_last_job.json",
        review_checklist=plan.CLIP_REVIEW_CHECKLIST, next_step_note=_note(stage.key),
        end_frame_path=_frame_file(stage.end_frame) if stage.end_frame else None,
        disable_prompt_expansion=True,
    )


def _frame_file(key: str) -> Path:
    """A clip's start/end frame: the approved file in the stills folder (manual stills), else the
    generated still's path. launch_blockers refuses the clip if the still isn't approved."""
    if plan.STILLS_SOURCE == "manual":
        st = still_state(key, _manifest(MANIFEST_PATH), _stills_dir(MANIFEST_PATH))
        if st["state"] == "approved":
            return Path(st["path"])
    return still_path(key)


class _LiveSpecs(dict):
    """Specs rebuilt on every lookup, so a clip always points at the stills approved right now
    (a manual still may be a .png, or replaced and re-approved, after this module was imported)."""

    def __getitem__(self, key):
        return _build_spec(STAGES[key])

    def get(self, key, default=None):
        return self[key] if key in STAGES else default

    def values(self):
        return [self[k] for k in STAGES]

    def items(self):
        return [(k, self[k]) for k in STAGES]


# Read by the Virtual Studio (app/studio/actions.py): one spec per stage key.
SPECS = _LiveSpecs(dict.fromkeys(STAGES))


def _manifest(manifest_path: Path) -> dict:
    return json.loads(manifest_path.read_text()) if manifest_path.exists() else {}


def _completed(entry) -> bool:
    return isinstance(entry, dict) and bool(entry.get("completed_at"))


def launch_blockers(stage_key: str, manifest_path: Path = MANIFEST_PATH) -> list[str]:
    """Why this stage may not run yet (empty = allowed). Used by the CLI and the studio."""
    if stage_key not in STAGES:
        return [f"Unknown train-car stage {stage_key!r}."]
    manifest = _manifest(manifest_path)
    stage = STAGES[stage_key]
    stills_dir = _stills_dir(manifest_path)
    if plan.STILLS_SOURCE == "manual" and stage.kind != "video":
        st = still_state(stage_key, manifest, stills_dir)
        return [f"Stills for this project are made manually in ChatGPT and never generated here. {stage_key}: "
                f"{_describe_still(stage_key, st)}."]
    problems = []
    if manifest.get("budget_cap_usd") is None:
        problems.append("No budget cap in the train-car manifest - run `python -m scripts.run_train_car_video_2_plan --write`.")
    i = ORDER.index(stage_key)
    if plan.STILLS_SOURCE == "manual":
        earlier_clips = [k for k in ORDER[:i] if STAGES[k].kind == "video"]
        if earlier_clips and not _completed(manifest.get(earlier_clips[-1])):
            problems.append(f"Runs in order: {earlier_clips[-1]} must be generated (and reviewed) first.")
        for needed in (stage.source, stage.end_frame):
            if needed and (st := still_state(needed, manifest, stills_dir))["state"] != "approved":
                problems.append(f"Needs an approved {needed}: {_describe_still(needed, st)}.")
    else:
        if i > 0 and not _completed(manifest.get(ORDER[i - 1])):
            problems.append(f"Runs in order: {ORDER[i - 1]} must be generated (and reviewed) first.")
        for needed in (stage.source, stage.end_frame):
            if needed and not _completed(manifest.get(needed)):
                problems.append(f"Needs {needed} first.")
    if i > ORDER.index(plan.PROOF_STAGE) and not (manifest.get("proof_gate") or {}).get("passed"):
        problems.append(
            f"PROOF GATE: {plan.PROOF_STAGE} (first end-frame test, CP02 -> CP03) has not been marked passed. Review "
            "it, then run `python -m scripts.run_train_car_video_2_stage --pass-proof \"<what you saw>\"` - or stop."
        )
    # Every clip in this runner is generated with the pipeline's video model; once that model has
    # failed the proof, no clip (including a retry of the proof clip) may be generated with it.
    failed = _failed_video_models(manifest)
    if stage.kind == "video" and VIDEO_MODEL in failed:
        problems.append(f"{VIDEO_MODEL} failed the {plan.PROOF_STAGE} proof ({failed[VIDEO_MODEL]}) - "
                        "train-car clips may not be generated with it.")
    return problems


# The model execute_video_shot uses for every clip (run_alpine_video_2_common.WAN_3_0_STANDARD).
VIDEO_MODEL = "alibaba/wan-3.0/image-to-video"


def _failed_video_models(manifest: dict) -> dict[str, str]:
    return {a["model"]: a.get("failure_class", "failed") for a in manifest.get("proof_attempts", [])
            if a.get("verdict") == "failed" and a.get("model")}


def fail_proof(note: str, *, failure_class: str, findings: list[str], continuity: str,
               manifest_path: Path = MANIFEST_PATH) -> dict:
    """Record that the proof clip was reviewed and failed. Keeps the gate closed and blocks the model."""
    manifest = _manifest(manifest_path)
    entry = manifest.get(plan.PROOF_STAGE)
    if not _completed(entry):
        raise PipelineStepError(f"{plan.PROOF_STAGE} hasn't been generated yet - nothing to fail.")
    if not note.strip():
        raise PipelineStepError("Say what failed (a short note) when failing the proof gate.")
    attempt = {"stage": plan.PROOF_STAGE, "verdict": "failed", "failure_class": failure_class,
               "continuity": continuity, "model": entry.get("video_model"),
               "provider_job_id": entry.get("provider_job_id"), "raw_video_path": entry.get("raw_video_path"),
               "note": note.strip(), "findings": findings, "decided_at": datetime.now(timezone.utc).isoformat()}
    manifest.setdefault("proof_attempts", []).append(attempt)
    manifest["proof_gate"] = {"stage": plan.PROOF_STAGE, "passed": False, "last_verdict": "failed",
                              "note": note.strip(), "decided_at": attempt["decided_at"]}
    manifest_path.write_text(json.dumps(manifest, indent=2))
    return attempt


def pass_proof(note: str, manifest_path: Path = MANIFEST_PATH) -> dict:
    manifest = _manifest(manifest_path)
    if not _completed(manifest.get(plan.PROOF_STAGE)):
        raise PipelineStepError(f"{plan.PROOF_STAGE} hasn't been generated yet - nothing to pass.")
    if not note.strip():
        raise PipelineStepError("Say what you checked (a short note) when passing the proof gate.")
    if any(a.get("verdict") == "failed" and a.get("provider_job_id") == manifest[plan.PROOF_STAGE].get("provider_job_id")
           for a in manifest.get("proof_attempts", [])):
        raise PipelineStepError(f"The current {plan.PROOF_STAGE} clip was already reviewed and failed - "
                                "a new proof clip is needed before the gate can pass.")
    manifest["proof_gate"] = {"stage": plan.PROOF_STAGE, "passed": True, "note": note.strip(),
                              "decided_at": datetime.now(timezone.utc).isoformat()}
    manifest_path.write_text(json.dumps(manifest, indent=2))
    return manifest["proof_gate"]


def run_stage(stage_key: str, *, confirm_spend=None, log=print, on_phase=None, provider=None,
              manifest_path: Path = MANIFEST_PATH) -> dict:
    blockers = launch_blockers(stage_key, manifest_path)
    if blockers:
        raise PipelineStepError(" ".join(blockers))
    spec = SPECS[stage_key]
    common = dict(manifest_path=manifest_path, confirm_spend=confirm_spend, on_phase=on_phase, log=log)
    if isinstance(spec, ImageGenerateSpec):
        return execute_generate(spec, image_provider=provider, **common)
    if isinstance(spec, EditSpec):
        return execute_edit(spec, image_provider=provider, **common)
    return execute_video_shot(spec, video_provider=provider,
                              timeout_seconds=float(settings.studio_live_wait_timeout_seconds), **common)


def recover_stage(stage_key: str, *, wait: bool = False, log=print, provider=None,
                  manifest_path: Path = MANIFEST_PATH) -> dict:
    """Check / finish an already-submitted clip. Never submits a new generation."""
    spec = SPECS.get(stage_key)
    if not isinstance(spec, VideoShotSpec):
        raise PipelineStepError(f"{stage_key} is not a video stage.")
    return recover_video_shot(spec, video_provider=provider, manifest_path=manifest_path, log=log, wait=wait,
                              timeout_seconds=float(settings.studio_live_wait_timeout_seconds))


def _status() -> None:
    manifest = _manifest(MANIFEST_PATH)
    cap = manifest.get("budget_cap_usd")
    spent = spent_so_far(manifest) if manifest else 0.0
    print(f"{plan.PROJECT_NAME}\nBudget: ${spent:.2f} spent of ${cap:.2f}" if cap is not None else "Budget: NOT SET")
    gate = manifest.get("proof_gate") or {}
    print(f"Proof gate ({plan.PROOF_STAGE}): {'PASSED - ' + gate.get('note', '') if gate.get('passed') else 'not passed'}")
    for model, why in _failed_video_models(manifest).items():
        print(f"  Blocked video model: {model} (failed proof: {why})")
    manual = plan.STILLS_SOURCE == "manual"
    if manual:
        print("Stills: MANUAL (ChatGPT) - the stills folder is the source of truth; see --stills")
    print()
    next_shown = False
    for key in ORDER:
        entry = manifest.get(key)
        if manual and STAGES[key].kind != "video":
            print(f"  {'still: ' + still_state(key, manifest)['state']:<16} {key:<14}  free  {STAGES[key].label}")
            continue
        state = "done" if _completed(entry) else ("STARTED" if isinstance(entry, dict) else "pending")
        marker = ""
        if state == "pending" and not next_shown:
            blockers = launch_blockers(key)
            marker = "  <- next" + (f" (blocked: {blockers[0]})" if blockers else "")
            next_shown = True
        print(f"  {state:<16} {key:<14} ${STAGES[key].estimated_cost_usd:.2f}  {STAGES[key].label}{marker}")


def _stills_report() -> None:
    manifest = _manifest(MANIFEST_PATH)
    print(f"Stills folder (source of truth): {STILLS_DIR}\n")
    for key in ORDER:
        if STAGES[key].kind == "video":
            continue
        st = still_state(key, manifest)
        users = ", ".join(k for k, s in STAGES.items() if s.kind == "video" and key in (s.source, s.end_frame))
        print(f"  {st['state']:<9} {key:<12} used by {users or '-':<14} {_describe_still(key, st)}")


def _still_brief(key: str) -> None:
    stage = STAGES.get(key)
    if stage is None or stage.kind == "video":
        raise PipelineStepError(f"{key!r} is not a still stage.")
    print(f"{stage.label}\n"
          f"Save as: {still_path(key)} (or .png / .webp - one file per key)\n"
          f"Storyboard reference: {OUTPUT_DIR / 'storyboard' / f'cp{stage.checkpoint:02d}.jpg'}\n"
          f"Continues from: {stage.source or 'nothing (establishing still)'}\n\n"
          f"{plan.stage_prompt(stage)}\n\nReview checklist:\n"
          + "\n".join(f"  - {c}" for c in plan.STILL_REVIEW_CHECKLIST))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("stage", nargs="?", help="stage key to run, e.g. cp01_still")
    parser.add_argument("--status", action="store_true")
    parser.add_argument("--pass-proof", metavar="NOTE")
    parser.add_argument("--stills", action="store_true", help="every still: expected path and approval state")
    parser.add_argument("--still-brief", metavar="KEY", help="what a still must show (to paste into ChatGPT)")
    parser.add_argument("--approve-still", nargs=2, metavar=("KEY", "NOTE"),
                        help="approve the still currently in the stills folder for KEY (free)")
    parser.add_argument("--recover", metavar="CLIP", help="check/finish an already-submitted clip (never resubmits)")
    parser.add_argument("--wait", action="store_true", help="with --recover: keep polling until it completes")
    parser.add_argument("--yes", action="store_true", help="skip the spend confirmation (not the review question)")
    args = parser.parse_args()

    if args.stills or args.still_brief or args.approve_still:
        try:
            if args.stills:
                _stills_report()
            elif args.still_brief:
                _still_brief(args.still_brief)
            else:
                result = approve_still(*args.approve_still)
                print(f"Approved {result['key']}: {result['output_path']} (sha256 {result['approved_sha256'][:12]}...)")
                if result["stale_clips"]:
                    print(f"NOTE: generated clip(s) {', '.join(result['stale_clips'])} used a different version "
                          "of this still.")
        except PipelineStepError as e:
            print(f"STOPPED: {e}")
            sys.exit(1)
        return
    if args.recover:
        try:
            result = recover_stage(args.recover, wait=args.wait)
        except PipelineStepError as e:
            print(f"STOPPED: {e}")
            sys.exit(1)
        print(f"Recovery: {result}")
        return
    if args.status or not (args.stage or args.pass_proof):
        _status()
        return
    if args.pass_proof is not None:
        print(f"Proof gate recorded: {pass_proof(args.pass_proof)}")
        return

    key = args.stage
    blockers = launch_blockers(key)
    if blockers:
        print("STOPPED: " + " ".join(blockers))
        sys.exit(1)
    i = ORDER.index(key)
    if i > 0:
        answer = input(f"Have you reviewed and approved {ORDER[i - 1]}? Type 'yes': ").strip().lower()
        if answer != "yes":
            print("Stopped. Nothing was generated.")
            return
    spec = SPECS[key]

    def confirm(_provider, _request, cost: float) -> bool:
        print(f"\n{spec.title}\nEstimated cost: ${cost:.4f}\nPrompt:\n  {getattr(spec, 'prompt', None) or spec.edit_prompt}\n")
        if args.yes:
            return True
        return input(f"Type 'yes' to spend up to ${cost:.4f}: ").strip().lower() == "yes"

    try:
        result = run_stage(key, confirm_spend=confirm)
    except PipelineStepError as e:
        print(f"\nSTOPPED: {e}")
        sys.exit(1)
    print(f"\nDONE: {result['output_path']} (${result['actual_cost_usd']:.4f}). STOP HERE and review against:")
    for item in spec.review_checklist:
        print(f"  - {item}")
    print(f"\n{spec.next_step_note}")


if __name__ == "__main__":
    main()
