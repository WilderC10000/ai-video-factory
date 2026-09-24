#!/usr/bin/env python3
"""FORMA VIRTUAL STUDIO - MOCK SANDBOX (no paid calls, real data untouched).

Copies the real Alpine #2 and Cliffside #1 project folders into
data/studio_sandbox/ (manifest paths rewritten to the copies), then starts the
studio backend in MOCK execution mode against that copy with its own SQLite
database. Every "generation" runs the real pipeline code path with mock
providers at $0.00. Nothing under data/alpine_video_2 or data/cliffside_video_1
is ever written, and no provider is ever called.

Usage (from the repo root; the frontend is still `cd studio-ui && npm run dev`):
    python -m scripts.studio_sandbox            # create the sandbox if missing, then serve on :8000
    python -m scripts.studio_sandbox --reset    # throw the sandbox away, re-copy, then serve
    python -m scripts.studio_sandbox --no-serve # just (re)create the sandbox
"""
import argparse
import json
import os
import shutil
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
REAL_DATA = REPO_ROOT / "data"
SANDBOX = REAL_DATA / "studio_sandbox"
PROJECTS = ["alpine_video_2", "cliffside_video_1", "train_car_video_2"]


def _rewrite_paths(value, real_prefix: str, sandbox_prefix: str):
    if isinstance(value, str) and value.startswith(real_prefix):
        return sandbox_prefix + value[len(real_prefix):]
    if isinstance(value, dict):
        return {k: _rewrite_paths(v, real_prefix, sandbox_prefix) for k, v in value.items()}
    if isinstance(value, list):
        return [_rewrite_paths(v, real_prefix, sandbox_prefix) for v in value]
    return value


def create_sandbox(reset: bool) -> None:
    if reset and SANDBOX.exists():
        shutil.rmtree(SANDBOX)
    SANDBOX.mkdir(parents=True, exist_ok=True)
    for slug in PROJECTS:
        src, dst = REAL_DATA / slug, SANDBOX / slug
        if dst.exists():
            print(f"  kept existing sandbox copy of {slug}")
            continue
        if not src.exists():
            print(f"  {slug}: no real data folder - skipped")
            continue
        shutil.copytree(src, dst)  # reads the real folder, writes only the copy
        manifest_path = dst / "manifest.json"
        if manifest_path.exists():
            manifest = json.loads(manifest_path.read_text())
            manifest = _rewrite_paths(manifest, str(REAL_DATA), str(SANDBOX))
            manifest_path.write_text(json.dumps(manifest, indent=2))
        print(f"  copied {slug} -> {dst}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--reset", action="store_true", help="Delete and re-copy the sandbox first.")
    parser.add_argument("--no-serve", action="store_true", help="Only create the sandbox.")
    parser.add_argument("--port", type=int, default=8000)
    args = parser.parse_args()

    print(f"Sandbox: {SANDBOX}")
    create_sandbox(args.reset)

    # Must be set before app.config is imported; these override anything in .env.
    os.environ["STUDIO_EXECUTION_MODE"] = "mock"
    os.environ["STUDIO_DATA_DIR"] = "./data/studio_sandbox"
    os.environ["DATABASE_URL"] = "sqlite:///./data/studio_sandbox/studio.db"
    os.environ["FAL_API_KEY"] = ""  # belt and braces: no real key is even visible to this process

    from app.db import SessionLocal, init_db
    from app.studio.importers.manifest_importer import import_all

    init_db()
    with SessionLocal() as db:
        for r in import_all(db):
            print(f"  imported {r.slug}: {r.stages_complete}/{r.stages_total} stages" if r.found else f"  {r.slug}: {r.error}")

    if args.no_serve:
        return
    import uvicorn

    print("\nMOCK SANDBOX backend on http://127.0.0.1:%d - mock providers, $0.00, real data untouched." % args.port)
    uvicorn.run("app.main:app", host="127.0.0.1", port=args.port)


if __name__ == "__main__":
    main()
