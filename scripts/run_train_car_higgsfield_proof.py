#!/usr/bin/env python3
"""FORMA VIDEO #2 (TRAIN CAR) - clip03 proof on a Higgsfield first/last-frame video model.

RETIRED 2026-09-28 - R&D history, recovery only. Higgsfield is off the production path (Project #3
uses fal: scripts/run_train_car_fal_proof.py). --prepare and --submit refuse; --check (local) and
--recover (free: status/download of the recorded job) still work. The Seedance 2.5 result stays in
the manifest as clip03__attempt3.

The same CP02 -> CP03 proof that Wan 3.0 failed on mechanism, re-run on another provider with
everything else held constant. setup.json (data/train_car_video_2/provider_tests/higgsfield_clip03/)
names the ONE model that receives the paid request (`model.endpoint_id`, one of
app.providers.video.higgsfield.MODELS) and its settings: the exact clip03 prompt, 6 s, 9:16, sound
off, plus that model's own fields (`model.overrides`). Start/end frames are whatever
cp02_still / cp03_still are APPROVED as in the stills folder right now (sha256-checked; stills are made
manually in ChatGPT) - prepared.json records whether they are still the Wan baseline's stills.

    --prepare                 FREE: upload both stills, call /estimate (+ comparison tiers), write prepared.json
    --check                   LOCAL ONLY (no network): final pre-submit checks
    --submit --approve-usd X  PAID: re-prepare, refuse unless estimate <= X and <= setup.json
                              cost.max_approved_usd, submit ONE job, wait, download
    --recover                 FREE: check/finish the already-submitted job (never resubmits)

The result is recorded in the train-car manifest as `clip03__attempt3` so its cost counts against the
$15 cap; it never touches `clip03` or the proof gate - passing the gate stays a separate human decision.
"""
import argparse
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

from app.providers.base import ProviderJobState, VideoGenerationRequest, VideoProviderError
from app.providers.video.higgsfield import MODELS, RETIRED_NOTE, HiggsfieldVideoProvider
from scripts.run_alpine_video_2_common import spent_so_far

DATA = Path(__file__).resolve().parent.parent / "data" / "train_car_video_2"
MANIFEST_PATH = DATA / "manifest.json"
TEST_DIR = DATA / "provider_tests" / "higgsfield_clip03"
SETUP_PATH = TEST_DIR / "setup.json"
PREPARED_PATH = TEST_DIR / "prepared.json"
JOB_PATH = TEST_DIR / "job.json"
CLIPS_DIR = DATA / "clips"
ENTRY_KEY = "clip03__attempt3"


def max_approved_usd(setup: dict) -> float:
    """The most the user approved for this proof (setup.json cost.max_approved_usd) - a hard stop."""
    value = (setup.get("cost") or {}).get("max_approved_usd")
    if not isinstance(value, (int, float)) or value <= 0:
        raise ProofError("setup.json has no cost.max_approved_usd - nothing is approved for this proof.")
    return float(value)


def existing_jobs(manifest: dict) -> list[str]:
    """Every sign of an earlier Higgsfield proof job - any one of them blocks a new submission."""
    found = [f"manifest {k}: job {v.get('provider_job_id')}" for k, v in manifest.items()
             if isinstance(v, dict) and v.get("provider") == "higgsfield" and v.get("provider_job_id")]
    if (manifest.get(ENTRY_KEY) or {}).get("provider_job_id") and not found:
        found.append(f"manifest {ENTRY_KEY}: job {manifest[ENTRY_KEY]['provider_job_id']}")
    if JOB_PATH.exists():
        found.append(f"{JOB_PATH.name} exists")
    return found


class ProofError(Exception):
    pass


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def approved_frames(manifest_path: Path = MANIFEST_PATH) -> dict:
    """The stills folder is the source of truth: clip03's start/end are whatever cp02_still and
    cp03_still are approved as right now (sha256-checked), never a stale path."""
    from scripts import run_train_car_video_2_stage as stage_mod

    clip = stage_mod.STAGES["clip03"]
    try:
        (start, start_sha), (end, end_sha) = (stage_mod.approved_still(clip.source, manifest_path),
                                              stage_mod.approved_still(clip.end_frame, manifest_path))
    except Exception as e:  # PipelineStepError: missing / placed-not-approved / changed since approval
        raise ProofError(f"Approved stills required: {e}") from e
    return {"start": str(start), "start_sha256": start_sha, "end": str(end), "end_sha256": end_sha}


def model_provider(setup: dict, **kwargs) -> HiggsfieldVideoProvider:
    """The provider for the model setup.json names - the only model that can receive the paid request."""
    endpoint = setup["model"]["endpoint_id"]
    if endpoint not in MODELS:
        raise ProofError(f"setup.json model {endpoint!r} is not a configured Higgsfield model ({sorted(MODELS)}).")
    return HiggsfieldVideoProvider(MODELS[endpoint], **kwargs)


def raw_output_path(setup: dict) -> Path:
    slug = setup["model"]["endpoint_id"].replace("/", "_").replace(".", "-")
    return CLIPS_DIR / f"clip03_higgsfield_{slug}_raw.mp4"


def build_request(manifest: dict, setup: dict, frames: dict) -> VideoGenerationRequest:
    """The request: approved stills + the prompt pinned in setup.json - any prompt drift refuses."""
    clip, held, model = manifest["clip03"], setup["held_constant"], setup["model"]
    if clip["video_prompt"] != held["prompt"]:
        raise ProofError("clip03 prompt differs from the prompt pinned in setup.json.")
    return VideoGenerationRequest(
        prompt=clip["video_prompt"], reference_image_path=frames["start"], end_image_path=frames["end"],
        duration_seconds=float(model["duration"]), aspect_ratio=model["aspect_ratio"],
        extra_params=dict(model.get("overrides") or {}))


def prepare(provider: HiggsfieldVideoProvider, manifest: dict, setup: dict,
            manifest_path: Path = MANIFEST_PATH) -> dict:
    """FREE: uploads + estimates. Returns what prepared.json holds (no secrets)."""
    if provider.model_config.endpoint_id != setup["model"]["endpoint_id"]:
        raise ProofError(f"Provider is {provider.model_config.endpoint_id} but setup.json names "
                         f"{setup['model']['endpoint_id']}.")
    frames = approved_frames(manifest_path)
    request = build_request(manifest, setup, frames)
    payload = provider.build_payload(request)
    estimate = provider.estimate_payload(payload)
    # Free price checks of other tiers of the same model (e.g. 720p) - never what gets submitted.
    compare = {label: provider.estimate_payload(payload | delta)
               for label, delta in (setup["model"].get("compare_estimates") or {}).items()}
    return {"prepared_at": _now(), "model": provider.model_config.endpoint_id,
            "endpoint": f"POST https://api.higgsfield.ai/{provider.model_config.endpoint_id}",
            "payload": payload, "estimate_usd": estimate["usd"], "estimate_credits": estimate["credits"],
            "estimate_basis": estimate.get("basis"), "max_approved_usd": max_approved_usd(setup),
            "compare_estimates_usd": {label: e["usd"] for label, e in compare.items()},
            "estimate_raw": {"submitted_payload": estimate["raw"], **{k: v["raw"] for k, v in compare.items()}},
            "budget_spent_usd": spent_so_far(manifest), "budget_cap_usd": manifest["budget_cap_usd"],
            "start_frame": frames["start"], "start_frame_sha256": frames["start_sha256"],
            "end_frame": frames["end"], "end_frame_sha256": frames["end_sha256"],
            "same_stills_as_wan_baseline": (
                frames["start_sha256"] == setup["held_constant"]["start_frame"]["sha256"]
                and frames["end_sha256"] == setup["held_constant"]["end_frame"]["sha256"])}


def submit(provider: HiggsfieldVideoProvider, approve_usd: float, *, manifest_path: Path = MANIFEST_PATH,
           setup: dict, log=print, wait_seconds: float = 2700.0, poll_seconds: float = 15.0) -> dict:
    """PAID: exactly one job. The job id is written to the manifest before anything else happens."""
    if not provider.allow_retired_submit:
        raise ProofError(RETIRED_NOTE)
    manifest = json.loads(manifest_path.read_text())
    jobs = existing_jobs(manifest)
    if jobs:
        raise ProofError(f"A Higgsfield proof job already exists ({'; '.join(jobs)}) - use --recover; "
                         "a second submission would pay twice.")
    cap = max_approved_usd(setup)
    prepared = prepare(provider, manifest, setup, manifest_path)
    usd = prepared["estimate_usd"]
    if usd > approve_usd:
        raise ProofError(f"Estimate ${usd:.4f} is above the approved ${approve_usd:.2f} - not submitted.")
    if usd > cap:
        raise ProofError(f"Estimate ${usd:.4f} is above the ${cap:.2f} approved for this proof - not submitted.")
    if spent_so_far(manifest) + usd > manifest["budget_cap_usd"]:
        raise ProofError("Budget cap would be exceeded - not submitted.")

    frames = {"start": prepared["start_frame"], "start_sha256": prepared["start_frame_sha256"],
              "end": prepared["end_frame"], "end_sha256": prepared["end_frame_sha256"]}
    submitted = provider.submit_video_job(build_request(manifest, setup, frames))
    manifest[ENTRY_KEY] = {"provider": "higgsfield", "video_model": provider.model_config.endpoint_id,
                           "payload": prepared["payload"], "estimated_cost_usd": usd, "approved_usd": approve_usd,
                           "estimate_basis": prepared["estimate_basis"],
                           "provider_job_id": submitted.provider_job_id, "meta": submitted.meta,
                           "start_frame_path": frames["start"], "start_frame_sha256": frames["start_sha256"],
                           "end_frame_path": frames["end"], "end_frame_sha256": frames["end_sha256"],
                           "submitted_at": _now(), "raw_video_path": None, "actual_cost_usd": None,
                           "completed_at": None,
                           "note": f"clip03 proof comparison - Higgsfield {provider.model_config.endpoint_id}"}
    manifest_path.write_text(json.dumps(manifest, indent=2))
    JOB_PATH.write_text(json.dumps({"provider_job_id": submitted.provider_job_id, "meta": submitted.meta}, indent=2))
    log(f"Submitted. Higgsfield request id: {submitted.provider_job_id}")
    return recover(provider, manifest_path=manifest_path, log=log, wait_seconds=wait_seconds,
                   poll_seconds=poll_seconds, output=raw_output_path(setup))


def recover(provider: HiggsfieldVideoProvider, *, manifest_path: Path = MANIFEST_PATH, log=print,
            wait_seconds: float = 2700.0, poll_seconds: float = 15.0, output: Path | None = None) -> dict:
    """FREE: poll the recorded job; on completion download and record cost. Never resubmits."""
    manifest = json.loads(manifest_path.read_text())
    entry = manifest.get(ENTRY_KEY) or {}
    job_id = entry.get("provider_job_id")
    if not job_id:
        raise ProofError(f"No {ENTRY_KEY} job recorded - nothing to recover.")
    output = output or raw_output_path({"model": {"endpoint_id": entry["video_model"]}})
    if entry.get("completed_at"):
        return entry
    deadline = time.monotonic() + wait_seconds
    while True:
        try:
            result = provider.get_job_status(job_id, entry.get("meta"))
        except VideoProviderError as e:
            log(f"  status check failed ({e}); retrying")
            result = None
        if result and result.status == ProviderJobState.COMPLETED:
            provider.download_result(job_id, result.output_url, str(output))
            manifest = json.loads(manifest_path.read_text())
            manifest[ENTRY_KEY].update(raw_video_path=str(output), completed_at=_now(),
                                       actual_cost_usd=manifest[ENTRY_KEY]["estimated_cost_usd"])
            manifest_path.write_text(json.dumps(manifest, indent=2))
            log(f"Done: {output}")
            return manifest[ENTRY_KEY]
        if result and result.status == ProviderJobState.FAILED:
            manifest = json.loads(manifest_path.read_text())
            manifest[ENTRY_KEY].update(status="failed", error=result.error_message, failed_at=_now())
            manifest_path.write_text(json.dumps(manifest, indent=2))
            raise ProofError(f"Higgsfield job {job_id} ended without a video (not charged): {result.error_message}")
        if time.monotonic() > deadline:
            raise ProofError(f"Still not finished after {wait_seconds:.0f}s - job {job_id} is recorded; "
                             "run --recover later (free).")
        log(f"  {(result.meta or {}).get('provider_status', 'checking') if result else 'retrying'}...")
        time.sleep(poll_seconds)


def final_check(setup: dict, manifest_path: Path = MANIFEST_PATH, *, expected_spend_usd: float = 0.90) -> dict:
    """LOCAL ONLY - no network. Everything that must hold right before the paid submit."""
    from scripts import run_train_car_video_2_stage as stage_mod

    manifest = json.loads(manifest_path.read_text())
    model, held = setup["model"], setup["held_constant"]
    checks: dict[str, tuple[bool, str]] = {}
    checks["model"] = (model["endpoint_id"] in MODELS, model["endpoint_id"])
    over = model.get("overrides") or {}
    checks["settings"] = (model["duration"] == 6 and model["aspect_ratio"] == "9:16"
                          and over.get("resolution") == "480p" and over.get("generate_audio") is False,
                          f"{model['duration']} s, {model['aspect_ratio']}, {over.get('resolution')}, "
                          f"generate_audio={over.get('generate_audio')}")
    prompt = manifest["clip03"]["video_prompt"]
    checks["prompt"] = (prompt == held["prompt"], f"{len(prompt)} chars, identical to the clip03 / Wan prompt")
    try:
        frames = approved_frames(manifest_path)
        for side, key, label in (("start", "cp02_still", "start_frame"), ("end", "cp03_still", "end_frame")):
            approved = manifest[key]["approved_sha256"]
            current = frames[side + "_sha256"]
            baseline = "same" if approved == held[label]["sha256"] else "DIFFERENT"
            checks[side + " still"] = (current == approved, f"{frames[side]} sha256 {current[:16]} = approved "
                                                            f"{approved[:16]}; Wan baseline: {baseline}")
    except ProofError as e:
        checks["stills"] = (False, str(e))
    jobs = existing_jobs(manifest)
    checks["no other Higgsfield job"] = (not jobs, "; ".join(jobs) or "none recorded")
    spent = spent_so_far(manifest)
    checks["spend"] = (abs(spent - expected_spend_usd) < 1e-9, f"${spent:.2f} of ${manifest['budget_cap_usd']:.2f}")
    gate = manifest.get("proof_gate") or {}
    checks["proof gate closed"] = (not gate.get("passed"),
                                   f"passed={bool(gate.get('passed'))}, last verdict: {gate.get('last_verdict')}")
    checks["Wan blocked"] = (stage_mod.VIDEO_MODEL in stage_mod._failed_video_models(manifest), stage_mod.VIDEO_MODEL)
    try:
        checks["approved amount"] = (True, f"${max_approved_usd(setup):.2f}")
    except ProofError as e:
        checks["approved amount"] = (False, str(e))
    probe = HiggsfieldVideoProvider(MODELS.get(model["endpoint_id"]) or next(iter(MODELS.values())))
    checks["credentials"] = (bool(probe.api_key_id and probe.api_key_secret), "HF_KEY parsed (value not shown)")
    return checks


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--prepare", action="store_true")
    group.add_argument("--check", action="store_true")
    group.add_argument("--submit", action="store_true")
    group.add_argument("--recover", action="store_true")
    parser.add_argument("--approve-usd", type=float, help="with --submit: the most you approved spending")
    args = parser.parse_args()
    setup = json.loads(SETUP_PATH.read_text())
    try:
        if args.check:
            checks = final_check(setup)
            for name, (ok, detail) in checks.items():
                print(f"  {'OK  ' if ok else 'FAIL'} {name}: {detail}")
            sys.exit(0 if all(ok for ok, _ in checks.values()) else 1)
        if args.prepare or args.submit:
            raise ProofError(RETIRED_NOTE)
        provider = model_provider(setup)
        if args.prepare:
            prepared = prepare(provider, json.loads(MANIFEST_PATH.read_text()), setup, MANIFEST_PATH)
            PREPARED_PATH.write_text(json.dumps(prepared, indent=2))
            print(json.dumps(prepared, indent=2))
        elif args.submit:
            if args.approve_usd is None:
                raise ProofError("--submit needs --approve-usd <amount you approved>.")
            print(submit(provider, args.approve_usd, setup=setup))
        else:
            print(recover(provider))
    except (ProofError, VideoProviderError) as e:
        print(f"STOPPED: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
