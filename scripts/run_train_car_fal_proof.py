#!/usr/bin/env python3
"""FORMA VIDEO #2 (TRAIN CAR) - one clip03 proof on a fal video model (Project #3 routing).

A proof decides whether a candidate model may move up a shot class (app/forma/routing.py). The
setup folder's setup.json names the ONE fal model that can receive the paid request, the shot
class it is being proved for, and the exact request settings. Start/end frames are whatever
cp02_still / cp03_still are APPROVED as in the stills folder right now (sha256-checked; stills are
made manually in ChatGPT, never generated here).

    --prepare                 FREE: upload both approved stills to fal storage (no generation), build the
                              exact payload + estimate, write prepared.json for review
    --check                   LOCAL ONLY (no network): every pre-submit condition
    --submit --approve-usd X  PAID: submit prepared.json's payload VERBATIM, once - refused unless
                              setup.json cost.max_approved_usd is set (the recorded approval), the
                              estimate is <= X and <= that amount, and every --check passes
    --recover                 FREE: check/finish the already-submitted job (never resubmits)

    --setup DIR               default: data/train_car_video_2/provider_tests/fal_kling_v3_standard_clip03

The result goes into the train-car manifest under setup.json's attempt_key (counted against the $15
cap). It never touches `clip03` or the proof gate - passing a model is a separate human review.
"""
import argparse
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

from app.forma import routing
from app.providers.base import VideoGenerationRequest, VideoProviderError
from app.providers.video.fal import FAL_VIDEO_MODELS, FalVideoProvider
from app.studio.attempt_status import check_attempt
from scripts.run_alpine_video_2_common import spent_so_far

DATA = Path(__file__).resolve().parent.parent / "data" / "train_car_video_2"
MANIFEST_PATH = DATA / "manifest.json"
DEFAULT_SETUP_DIR = DATA / "provider_tests" / "fal_kling_v3_standard_clip03"
CLIPS_DIR = DATA / "clips"
FAL_QUEUE_BASE = "https://queue.fal.run"


class ProofError(Exception):
    pass


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def load_setup(setup_dir: Path) -> dict:
    setup = json.loads((setup_dir / "setup.json").read_text())
    endpoint = setup["model"]["endpoint_id"]
    if endpoint not in FAL_VIDEO_MODELS:
        raise ProofError(f"setup.json model {endpoint!r} is not a configured fal video model.")
    return setup


def route_for(setup: dict) -> routing.Route:
    """The routing entry this proof tests - refuses a model that already failed this shot class."""
    try:
        return routing.select_video_model(setup["shot_class"], allow_unproven=True,
                                          model=setup["model"]["endpoint_id"])
    except routing.RoutingError as e:
        raise ProofError(str(e)) from e


def provider_for(setup: dict, **kwargs) -> FalVideoProvider:
    return FalVideoProvider(FAL_VIDEO_MODELS[setup["model"]["endpoint_id"]], **kwargs)


def approved_frames(setup: dict, manifest_path: Path = MANIFEST_PATH) -> dict:
    from scripts import run_train_car_video_2_stage as stage_mod

    try:
        (start, start_sha), (end, end_sha) = (stage_mod.approved_still(setup["stills"]["start"], manifest_path),
                                              stage_mod.approved_still(setup["stills"]["end"], manifest_path))
    except Exception as e:  # missing / placed-not-approved / changed since approval
        raise ProofError(f"Approved stills required: {e}") from e
    return {"start": str(start), "start_sha256": start_sha, "end": str(end), "end_sha256": end_sha}


def build_request(setup: dict, frames: dict) -> VideoGenerationRequest:
    model = setup["model"]
    return VideoGenerationRequest(
        prompt=model.get("prompt") or "", reference_image_path=frames["start"], end_image_path=frames["end"],
        duration_seconds=float(model["duration"]), aspect_ratio=model["aspect_ratio"],
        extra_params=dict(model.get("extra_params") or {}))


def raw_output_path(setup: dict) -> Path:
    slug = setup["model"]["endpoint_id"].replace("/", "_").replace(".", "-")
    return CLIPS_DIR / f"{setup['attempt_key']}_fal_{slug}_raw.mp4"  # one file per attempt (beats share a stage)


def prepare(provider: FalVideoProvider, setup: dict, manifest_path: Path = MANIFEST_PATH) -> dict:
    """FREE: uploads the two approved stills to fal storage and builds the exact payload. No generation."""
    route = route_for(setup)
    manifest = json.loads(manifest_path.read_text())
    frames = approved_frames(setup, manifest_path)
    request = build_request(setup, frames)
    provider.check_request(request)  # refuse before uploading anything
    image_url = provider.upload_image(frames["start"])
    end_image_url = provider.upload_image(frames["end"])
    payload = provider.build_payload(request, image_url, end_image_url)
    return {"prepared_at": _now(), "attempt_key": setup["attempt_key"], "shot_class": setup["shot_class"],
            "route_status": route.status, "model": provider.model_config.submit_path,
            "endpoint": f"POST {FAL_QUEUE_BASE}/{provider.model_config.submit_path}",
            "payload": payload, "estimate_usd": provider.estimate_cost(request),
            "estimate_basis": setup["cost"].get("basis"),
            "max_approved_usd": setup["cost"].get("max_approved_usd"),
            "budget_spent_usd": spent_so_far(manifest), "budget_cap_usd": manifest["budget_cap_usd"],
            "start_frame": frames["start"], "start_frame_sha256": frames["start_sha256"],
            "end_frame": frames["end"], "end_frame_sha256": frames["end_sha256"]}


def existing_jobs(manifest: dict, setup: dict, setup_dir: Path) -> list[str]:
    found = []
    if (manifest.get(setup["attempt_key"]) or {}).get("provider_job_id"):
        found.append(f"manifest {setup['attempt_key']}: job {manifest[setup['attempt_key']]['provider_job_id']}")
    if (setup_dir / "job.json").exists():
        found.append("job.json exists")
    return found


def shot_length_check(setup: dict, provider: FalVideoProvider) -> tuple[bool, str]:
    """Every multi_prompt shot within the model's per-shot limit (Kling v3: 512 characters - a run-time
    limit fal's schema doesn't show; clip03__attempt4 failed on it)."""
    shots = (setup["model"].get("extra_params") or {}).get("multi_prompt")
    if not shots:
        return True, "single prompt (no multi_prompt shots)"
    limit = provider.model_config.max_shot_prompt_chars
    lengths = [len(shot["prompt"]) for shot in shots]
    ok = limit is None or all(n <= limit for n in lengths)
    return ok, f"{' / '.join(map(str, lengths))} chars (limit {limit or 'none'})"


def final_check(setup: dict, setup_dir: Path, manifest_path: Path = MANIFEST_PATH,
                provider: FalVideoProvider | None = None) -> dict:
    """LOCAL ONLY - no network. Everything that must hold right before the paid submit."""
    provider = provider or provider_for(setup)
    manifest = json.loads(manifest_path.read_text())
    checks: dict[str, tuple[bool, str]] = {}
    try:
        route = route_for(setup)
        checks["route"] = (True, f"{setup['shot_class']}: {route.model} ({route.status})")
    except ProofError as e:
        checks["route"] = (False, str(e))
    checks["shot prompts"] = shot_length_check(setup, provider)
    prepared_path = setup_dir / "prepared.json"
    if not prepared_path.exists():
        checks["prepared"] = (False, "no prepared.json - run --prepare (free)")
        return checks
    prepared = json.loads(prepared_path.read_text())
    payload = prepared["payload"]
    try:
        frames = approved_frames(setup, manifest_path)
        same = (frames["start_sha256"], frames["end_sha256"]) == (prepared["start_frame_sha256"],
                                                                  prepared["end_frame_sha256"])
        checks["stills"] = (same, f"approved {setup['stills']['start']} {frames['start_sha256'][:12]} / "
                                  f"{setup['stills']['end']} {frames['end_sha256'][:12]} "
                                  f"{'= prepared' if same else '!= prepared - run --prepare again'}")
        cfg = provider.model_config
        rebuilt = provider.build_payload(build_request(setup, frames), payload[cfg.image_param_name],
                                         payload.get(cfg.end_image_param_name))
        checks["payload"] = (rebuilt == payload, "prepared payload = what setup.json builds today"
                             if rebuilt == payload else "setup.json changed since --prepare - run it again")
        estimate = provider.estimate_cost(build_request(setup, frames))
    except (ProofError, VideoProviderError) as e:
        checks["stills"] = (False, str(e))
        estimate = prepared["estimate_usd"]
    checks["audio off"] = (payload.get("generate_audio") is False, f"generate_audio={payload.get('generate_audio')}")
    cap = setup["cost"].get("max_approved_usd")
    checks["approved amount"] = (cap is not None and estimate <= cap,
                                 f"estimate ${estimate:.4f}; approved {'none yet' if cap is None else f'${cap:.2f}'}")
    jobs = existing_jobs(manifest, setup, setup_dir)
    checks["no earlier job"] = (not jobs, "; ".join(jobs) or "none recorded")
    spent = spent_so_far(manifest)
    checks["budget"] = (spent + estimate <= manifest["budget_cap_usd"],
                        f"${spent:.2f} spent + ${estimate:.4f} of ${manifest['budget_cap_usd']:.2f}")
    checks["credentials"] = (bool(provider.api_key), "FAL key present (value not shown)")
    return checks


def submit(provider: FalVideoProvider, approve_usd: float, *, setup: dict, setup_dir: Path,
           manifest_path: Path = MANIFEST_PATH, log=print, wait_seconds: float = 2700.0,
           poll_seconds: float = 15.0, wait: bool = True) -> dict:
    """PAID: exactly one job, the reviewed prepared.json payload verbatim. Job id recorded first.
    wait=False returns right after recording it; the studio then follows the job (free status checks)."""
    from scripts import run_train_car_video_2_plan as plan

    if plan.FROZEN:
        raise ProofError(plan.FROZEN)
    checks = final_check(setup, setup_dir, manifest_path, provider)
    failed = [f"{name}: {detail}" for name, (ok, detail) in checks.items() if not ok]
    if failed:
        raise ProofError("Not submitted - " + "; ".join(failed))
    prepared = json.loads((setup_dir / "prepared.json").read_text())
    usd = prepared["estimate_usd"]
    if usd > approve_usd:
        raise ProofError(f"Estimate ${usd:.4f} is above the approved ${approve_usd:.2f} - not submitted.")
    try:
        submitted = provider.submit_payload(prepared["payload"], usd)
    except VideoProviderError as e:
        # Rejected at submission (e.g. a 4xx validation error): no job exists, nothing is charged.
        # Kept as a finding - e.g. "multi_prompt + end_image_url is not accepted".
        (setup_dir / "submit_rejected.json").write_text(json.dumps({"at": _now(), "error": str(e)}, indent=2))
        raise ProofError(f"fal rejected the request (no job, not charged): {e}") from e
    manifest = json.loads(manifest_path.read_text())
    manifest[setup["attempt_key"]] = {
        "provider": "fal", "video_model": provider.model_config.submit_path, "shot_class": setup["shot_class"],
        "route_status_at_submit": prepared["route_status"], "payload": prepared["payload"],
        "estimated_cost_usd": usd, "approved_usd": approve_usd, "estimate_basis": prepared["estimate_basis"],
        "provider_job_id": submitted.provider_job_id, "meta": submitted.meta,
        "start_frame_path": prepared["start_frame"], "start_frame_sha256": prepared["start_frame_sha256"],
        "end_frame_path": prepared["end_frame"], "end_frame_sha256": prepared["end_frame_sha256"],
        "submitted_at": _now(), "provider_status": None, "status_checked_at": None,
        "planned_output_path": str(raw_output_path(setup)), "raw_video_path": None, "actual_cost_usd": None,
        "completed_at": None, "note": setup.get("purpose"),
        **({"beat": setup["beat"]} if setup.get("beat") else {})}
    manifest_path.write_text(json.dumps(manifest, indent=2))
    (setup_dir / "job.json").write_text(json.dumps({"provider_job_id": submitted.provider_job_id,
                                                    "meta": submitted.meta}, indent=2))
    log(f"Submitted. fal request id: {submitted.provider_job_id}")
    if not wait:  # the studio (or a later --recover) follows the job from the manifest record
        return manifest[setup["attempt_key"]]
    return recover(provider, setup=setup, manifest_path=manifest_path, log=log, wait_seconds=wait_seconds,
                   poll_seconds=poll_seconds)


def recover(provider: FalVideoProvider, *, setup: dict, manifest_path: Path = MANIFEST_PATH, log=print,
            wait_seconds: float = 2700.0, poll_seconds: float = 15.0) -> dict:
    """FREE: poll the recorded job until it finishes; each check is persisted in the manifest (the studio
    shows it live) via app.studio.attempt_status.check_attempt. Never resubmits."""
    key = setup["attempt_key"]
    entry = json.loads(manifest_path.read_text()).get(key) or {}
    if not entry.get("provider_job_id"):
        raise ProofError(f"No {key} job recorded - nothing to recover.")
    deadline = time.monotonic() + wait_seconds
    while True:
        entry = check_attempt(manifest_path, key, provider=provider, force=True)
        if entry.get("completed_at"):
            log(f"Done: {entry['raw_video_path']}")
            return entry
        if entry.get("status") in ("failed", "cancelled"):
            raise ProofError(f"fal job {entry['provider_job_id']} ended without a video: {entry.get('error')}")
        if time.monotonic() > deadline:
            raise ProofError(f"Still not finished after {wait_seconds:.0f}s - job {entry['provider_job_id']} is "
                             "recorded; run --recover later (free).")
        log(f"  {entry.get('provider_status') or 'checking'}"
            f"{' (check failed: ' + entry['last_check_error'][:120] + ')' if entry.get('last_check_error') else ''}...")
        time.sleep(poll_seconds)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--prepare", action="store_true")
    group.add_argument("--check", action="store_true")
    group.add_argument("--submit", action="store_true")
    group.add_argument("--recover", action="store_true")
    parser.add_argument("--approve-usd", type=float, help="with --submit: the most you approved spending")
    parser.add_argument("--setup", type=Path, default=DEFAULT_SETUP_DIR)
    parser.add_argument("--no-wait", action="store_true",
                        help="with --submit: record the job and exit; the studio follows it from there")
    args = parser.parse_args()
    try:
        setup = load_setup(args.setup)
        provider = provider_for(setup)
        if args.check:
            checks = final_check(setup, args.setup, provider=provider)
            for name, (ok, detail) in checks.items():
                print(f"  {'OK  ' if ok else 'FAIL'} {name}: {detail}")
            sys.exit(0 if all(ok for ok, _ in checks.values()) else 1)
        if args.prepare:
            prepared = prepare(provider, setup)
            (args.setup / "prepared.json").write_text(json.dumps(prepared, indent=2))
            print(json.dumps(prepared, indent=2))
        elif args.submit:
            if args.approve_usd is None:
                raise ProofError("--submit needs --approve-usd <amount you approved>.")
            entry = submit(provider, args.approve_usd, setup=setup, setup_dir=args.setup, wait=not args.no_wait)
            print(json.dumps({k: entry.get(k) for k in ("provider_job_id", "provider_status", "estimated_cost_usd",
                                                         "submitted_at", "completed_at", "raw_video_path")}, indent=2))
        else:
            print(recover(provider, setup=setup))
    except (ProofError, VideoProviderError) as e:
        print(f"STOPPED: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
