#!/usr/bin/env python3
"""FORMA VIDEO #2 (TRAIN CAR) - RUN ONE STAGE (incremental, gated).

Runs exactly ONE stage of the 20-checkpoint plan (scripts/run_train_car_video_2_plan.py)
through the shared pipeline functions (execute_generate / execute_edit /
execute_video_shot). The same SPECS drive the FORMA Virtual Studio, which is the
intended way to run this project: GENERATE STILL -> REVIEW -> APPROVE -> GENERATE
CLIP -> REVIEW -> APPROVE -> NEXT CHECKPOINT.

Gates, enforced here and in the studio:
  - stages run strictly in plan.execution_order(); each needs its predecessor done;
  - the hard budget cap in data/train_car_video_2/manifest.json ($15.00);
  - PROOF GATE: nothing ordered after clip03 (the first CP02 -> CP03 end-frame test)
    may run until `--pass-proof "<why>"` is recorded after reviewing it.

Usage (from the repo root):
    python -m scripts.run_train_car_video_2_stage --status
    python -m scripts.run_train_car_video_2_stage cp01_still          # asks before spending
    python -m scripts.run_train_car_video_2_stage --pass-proof "end frame held, railcar stable"
"""
import argparse
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
    return STILLS_DIR / f"{key}.jpg"


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
    start = still_path(stage.source)
    return VideoShotSpec(
        shot_key=stage.key, title=stage.label, upstream_path=start, upstream_label=STAGES[stage.source].label,
        needs_frame_extraction=False, start_frame_path=start, prompt=prompt,
        duration_seconds=float(stage.raw_seconds), max_spend_usd=stage.estimated_cost_usd,
        raw_output_path=CLIPS_DIR / f"{stage.key}_raw.mp4", job_state_path=CLIPS_DIR / f"{stage.key}_last_job.json",
        review_checklist=plan.CLIP_REVIEW_CHECKLIST, next_step_note=_note(stage.key),
        end_frame_path=still_path(stage.end_frame) if stage.end_frame else None,
        disable_prompt_expansion=True,
    )


# Read by the Virtual Studio (app/studio/actions.py): one spec per stage key.
SPECS = {key: _build_spec(stage) for key, stage in STAGES.items()}


def _manifest(manifest_path: Path) -> dict:
    return json.loads(manifest_path.read_text()) if manifest_path.exists() else {}


def _completed(entry) -> bool:
    return isinstance(entry, dict) and bool(entry.get("completed_at"))


def launch_blockers(stage_key: str, manifest_path: Path = MANIFEST_PATH) -> list[str]:
    """Why this stage may not run yet (empty = allowed). Used by the CLI and the studio."""
    if stage_key not in STAGES:
        return [f"Unknown train-car stage {stage_key!r}."]
    manifest = _manifest(manifest_path)
    problems = []
    if manifest.get("budget_cap_usd") is None:
        problems.append("No budget cap in the train-car manifest - run `python -m scripts.run_train_car_video_2_plan --write`.")
    i = ORDER.index(stage_key)
    if i > 0 and not _completed(manifest.get(ORDER[i - 1])):
        problems.append(f"Runs in order: {ORDER[i - 1]} must be generated (and reviewed) first.")
    stage = STAGES[stage_key]
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
    print()
    next_shown = False
    for key in ORDER:
        entry = manifest.get(key)
        state = "done" if _completed(entry) else ("STARTED" if isinstance(entry, dict) else "pending")
        marker = ""
        if state == "pending" and not next_shown:
            blockers = launch_blockers(key)
            marker = "  <- next" + (f" (blocked: {blockers[0]})" if blockers else "")
            next_shown = True
        print(f"  {state:<8} {key:<14} ${STAGES[key].estimated_cost_usd:.2f}  {STAGES[key].label}{marker}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("stage", nargs="?", help="stage key to run, e.g. cp01_still")
    parser.add_argument("--status", action="store_true")
    parser.add_argument("--pass-proof", metavar="NOTE")
    parser.add_argument("--recover", metavar="CLIP", help="check/finish an already-submitted clip (never resubmits)")
    parser.add_argument("--wait", action="store_true", help="with --recover: keep polling until it completes")
    parser.add_argument("--yes", action="store_true", help="skip the spend confirmation (not the review question)")
    args = parser.parse_args()

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
