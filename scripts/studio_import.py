#!/usr/bin/env python3
"""FORMA VIRTUAL STUDIO - IMPORT REAL PRODUCTION MANIFESTS.

Pure local read. NO API calls, NO FAL_API_KEY needed, NO spend. Mirrors
data/alpine_video_2/manifest.json and data/cliffside_video_1/manifest.json
(plus the files they reference) into the studio_* tables of the app's
SQLite database. The manifests and every pipeline file are only read, never
written. Safe to re-run any time - the import is idempotent.

Usage (from the repo root):
    python -m scripts.studio_import                         # import both, print summary
    python -m scripts.studio_import --project alpine_video_2 --show
"""
import argparse

from sqlalchemy import select

from app.db import SessionLocal, init_db
from app.studio.importers.manifest_importer import import_all
from app.studio.importers.stage_maps import PROJECTS_BY_SLUG
from app.studio.models import StudioApproval, StudioEvent, StudioProject


def _show(db, slug: str) -> None:
    project = db.scalar(select(StudioProject).where(StudioProject.slug == slug))
    if project is None:
        return
    b = project.budget
    print(f"\n{'=' * 78}\n{project.name}  [{project.slug}]{'  (ACTIVE)' if project.is_active else ''}")
    print(f"Stage: {project.production_stage}")
    if b:
        cap = f"${b.cap_usd:.2f}" if b.cap_usd is not None else "none"
        rem = f"${b.remaining_usd:.2f}" if b.remaining_usd is not None else "n/a"
        print(f"Budget: cap {cap} ({b.cap_source}) | spent ${b.spent_usd:.2f} | remaining {rem} | "
              f"planned remaining ${b.planned_remaining_spend_usd:.2f}")
    print("-" * 78)
    for s in project.stages:
        cost = f"${s.actual_cost_usd:.2f}" if s.actual_cost_usd is not None else (
            f"(${s.planned_cost_usd:.2f})" if s.planned_cost_usd else "")
        flags = []
        if s.latest_output_exists is False:
            flags.append("OUTPUT MISSING")
        if s.approval_state:
            flags.append(f"approval={s.approval_state.value}")
        if s.requires_human_review:
            flags.append("NEEDS YOU")
        print(f"  {s.status.value:<9} {s.label:<46} {cost:>8}  {s.room_id:<21} {' '.join(flags)}")
    pending = db.scalars(select(StudioApproval).where(
        StudioApproval.project_id == project.id, StudioApproval.status == "pending")).all()
    for a in pending:
        print(f"\n  PENDING APPROVAL: {a.title}")
    events = db.scalars(select(StudioEvent).where(StudioEvent.project_id == project.id)
                        .where(StudioEvent.severity != "info")).all()
    for e in events:
        print(f"  [{e.severity.value}] {e.message}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--project", choices=sorted(PROJECTS_BY_SLUG), action="append",
                        help="Import only this project (repeatable). Default: all real productions.")
    parser.add_argument("--show", action="store_true", help="Print each project's imported state.")
    args = parser.parse_args()

    init_db()
    with SessionLocal() as db:
        results = import_all(db, slugs=args.project)
        for r in results:
            if not r.found or r.error:
                print(f"{r.slug}: SKIPPED - {r.error}")
                continue
            cap = f"${r.cap_usd:.2f}" if r.cap_usd is not None else "no cap"
            print(f"{r.slug}: {r.stages_complete}/{r.stages_total} stages complete | spent ${r.spent_usd:.2f} of "
                  f"{cap} | new events {r.events_created} | approvals +{r.approvals_created} "
                  f"(updated {r.approvals_updated})")
        if args.show:
            for r in results:
                _show(db, r.slug)


if __name__ == "__main__":
    main()
