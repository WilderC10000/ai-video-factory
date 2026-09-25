#!/usr/bin/env python3
"""FORMA VIDEO #2 (TRAIN CAR) - clip03 proof on Higgsfield Kling O3 first/last-frame.

The same CP02 -> CP03 proof that Wan 3.0 failed on mechanism, re-run on another provider with
everything else held constant (setup: data/train_car_video_2/provider_tests/higgsfield_clip03/setup.json):
the exact clip03 prompt, 9:16, 6 s, sound off, single shot, mode pro. Start/end frames are whatever
cp02_still / cp03_still are APPROVED as in the stills folder right now (sha256-checked; stills are made
manually in ChatGPT) - prepared.json records whether they are still the Wan baseline's stills.

    --prepare                 FREE: upload both stills, call /estimate (pro and std), write prepared.json
    --submit --approve-usd X  PAID: re-prepare, refuse unless estimate <= X, submit ONE job, wait, download
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
from app.providers.video.higgsfield import KLING_O3_FIRST_LAST_FRAME, HiggsfieldVideoProvider
from scripts.run_alpine_video_2_common import spent_so_far

DATA = Path(__file__).resolve().parent.parent / "data" / "train_car_video_2"
MANIFEST_PATH = DATA / "manifest.json"
TEST_DIR = DATA / "provider_tests" / "higgsfield_clip03"
SETUP_PATH = TEST_DIR / "setup.json"
PREPARED_PATH = TEST_DIR / "prepared.json"
JOB_PATH = TEST_DIR / "job.json"
RAW_OUTPUT = DATA / "clips" / "clip03_higgsfield_kling_o3_raw.mp4"
ENTRY_KEY = "clip03__attempt3"
HARD_CAP_USD = 1.00  # per setup.json: stop if the estimate is above this, whatever is approved


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


def build_request(manifest: dict, setup: dict, frames: dict) -> VideoGenerationRequest:
    """The request: approved stills + the prompt pinned in setup.json - any prompt drift refuses."""
    clip, held = manifest["clip03"], setup["held_constant"]
    if clip["video_prompt"] != held["prompt"]:
        raise ProofError("clip03 prompt differs from the prompt pinned in setup.json.")
    payload = setup["model"]["payload"]
    if setup["model"]["endpoint_id"] != KLING_O3_FIRST_LAST_FRAME.endpoint_id:
        raise ProofError("setup.json endpoint is not the Kling O3 first/last-frame config.")
    return VideoGenerationRequest(
        prompt=clip["video_prompt"], reference_image_path=frames["start"],
        end_image_path=frames["end"], duration_seconds=float(payload["duration"]),
        aspect_ratio=payload["aspect_ratio"], extra_params={"mode": payload["mode"], "sound": payload["sound"]})


def prepare(provider: HiggsfieldVideoProvider, manifest: dict, setup: dict,
            manifest_path: Path = MANIFEST_PATH) -> dict:
    """FREE: uploads + estimates. Returns what prepared.json holds (no secrets)."""
    frames = approved_frames(manifest_path)
    request = build_request(manifest, setup, frames)
    payload = provider.build_payload(request)
    estimates = {"pro": provider.estimate_payload(payload)}
    estimates["std"] = provider.estimate_payload(payload | {"mode": "std"})
    return {"prepared_at": _now(), "endpoint": f"POST https://api.higgsfield.ai/{provider.model_config.endpoint_id}",
            "payload": payload, "estimate_usd": estimates["pro"]["usd"], "estimate_credits": estimates["pro"]["credits"],
            "estimate_std_usd": estimates["std"]["usd"], "estimate_raw": {k: v["raw"] for k, v in estimates.items()},
            "budget_spent_usd": spent_so_far(manifest), "budget_cap_usd": manifest["budget_cap_usd"],
            "start_frame": frames["start"], "start_frame_sha256": frames["start_sha256"],
            "end_frame": frames["end"], "end_frame_sha256": frames["end_sha256"],
            "same_stills_as_wan_baseline": (
                frames["start_sha256"] == setup["held_constant"]["start_frame"]["sha256"]
                and frames["end_sha256"] == setup["held_constant"]["end_frame"]["sha256"])}


def submit(provider: HiggsfieldVideoProvider, approve_usd: float, *, manifest_path: Path = MANIFEST_PATH,
           setup: dict, log=print, wait_seconds: float = 2700.0, poll_seconds: float = 15.0) -> dict:
    """PAID: exactly one job. The job id is written to the manifest before anything else happens."""
    manifest = json.loads(manifest_path.read_text())
    if (manifest.get(ENTRY_KEY) or {}).get("provider_job_id"):
        raise ProofError(f"{ENTRY_KEY} already has provider job {manifest[ENTRY_KEY]['provider_job_id']} - "
                         "use --recover; a second submission would pay twice.")
    prepared = prepare(provider, manifest, setup, manifest_path)
    usd = prepared["estimate_usd"]
    if usd > approve_usd:
        raise ProofError(f"Estimate ${usd:.4f} is above the approved ${approve_usd:.2f} - not submitted.")
    if usd > HARD_CAP_USD:
        raise ProofError(f"Estimate ${usd:.4f} is above the ${HARD_CAP_USD:.2f} hard cap - not submitted.")
    if spent_so_far(manifest) + usd > manifest["budget_cap_usd"]:
        raise ProofError("Budget cap would be exceeded - not submitted.")

    frames = {"start": prepared["start_frame"], "start_sha256": prepared["start_frame_sha256"],
              "end": prepared["end_frame"], "end_sha256": prepared["end_frame_sha256"]}
    submitted = provider.submit_video_job(build_request(manifest, setup, frames))
    manifest[ENTRY_KEY] = {"provider": "higgsfield", "video_model": provider.model_config.endpoint_id,
                           "payload": prepared["payload"], "estimated_cost_usd": usd, "approved_usd": approve_usd,
                           "provider_job_id": submitted.provider_job_id, "meta": submitted.meta,
                           "start_frame_path": frames["start"], "start_frame_sha256": frames["start_sha256"],
                           "end_frame_path": frames["end"], "end_frame_sha256": frames["end_sha256"],
                           "submitted_at": _now(), "raw_video_path": None, "actual_cost_usd": None,
                           "completed_at": None, "note": "clip03 proof comparison - Higgsfield Kling O3 FLF"}
    manifest_path.write_text(json.dumps(manifest, indent=2))
    JOB_PATH.write_text(json.dumps({"provider_job_id": submitted.provider_job_id, "meta": submitted.meta}, indent=2))
    log(f"Submitted. Higgsfield request id: {submitted.provider_job_id}")
    return recover(provider, manifest_path=manifest_path, log=log, wait_seconds=wait_seconds, poll_seconds=poll_seconds)


def recover(provider: HiggsfieldVideoProvider, *, manifest_path: Path = MANIFEST_PATH, log=print,
            wait_seconds: float = 2700.0, poll_seconds: float = 15.0) -> dict:
    """FREE: poll the recorded job; on completion download and record cost. Never resubmits."""
    manifest = json.loads(manifest_path.read_text())
    entry = manifest.get(ENTRY_KEY) or {}
    job_id = entry.get("provider_job_id")
    if not job_id:
        raise ProofError(f"No {ENTRY_KEY} job recorded - nothing to recover.")
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
            provider.download_result(job_id, result.output_url, str(RAW_OUTPUT))
            manifest = json.loads(manifest_path.read_text())
            manifest[ENTRY_KEY].update(raw_video_path=str(RAW_OUTPUT), completed_at=_now(),
                                       actual_cost_usd=manifest[ENTRY_KEY]["estimated_cost_usd"])
            manifest_path.write_text(json.dumps(manifest, indent=2))
            log(f"Done: {RAW_OUTPUT}")
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


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--prepare", action="store_true")
    group.add_argument("--submit", action="store_true")
    group.add_argument("--recover", action="store_true")
    parser.add_argument("--approve-usd", type=float, help="with --submit: the most you approved spending")
    args = parser.parse_args()
    setup = json.loads(SETUP_PATH.read_text())
    provider = HiggsfieldVideoProvider()
    try:
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
