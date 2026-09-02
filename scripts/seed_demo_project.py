#!/usr/bin/env python3
"""Run one project all the way from an idea to a full storyboard, using only the
free mock LLM provider. This is how we prove the pipeline works end-to-end
without needing a frontend or spending any money.

Usage:
    python -m scripts.seed_demo_project
    python -m scripts.seed_demo_project "He converted a giant concrete pipe into a hidden luxury home."
"""
import sys

from app.db import SessionLocal, init_db
from app.providers.llm.mock import MockLLMProvider
from app.services import project_service

DEFAULT_IDEA = (
    "He buried an abandoned private jet beneath his backyard and turned it into "
    "an underground luxury bunker."
)


def main() -> None:
    idea = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_IDEA
    init_db()

    db = SessionLocal()
    llm = MockLLMProvider()
    try:
        project = project_service.create_project(db, idea)
        print(f"[1/4] Created project {project.id} - status={project.status.value}")

        project = project_service.advance_to_concept(db, project, llm)
        print(f"[2/4] Concept ready - status={project.status.value}")
        print(f"      Title: {project.title}")
        print(f"      Continuity bible: {project.continuity_bible}")

        project = project_service.advance_to_script(db, project, llm)
        print(f"[3/4] Script ready - status={project.status.value}")
        print(f"      Hook: {project.script['hook']}")

        project = project_service.advance_to_storyboard(db, project, llm)
        print(f"[4/4] Storyboard ready - status={project.status.value}")
        print(f"      {len(project.shots)} shots created:")
        for shot in project.shots:
            print(f"        #{shot.shot_number} [{shot.status.value}] {shot.description}")

        print(f"\nTotal cost so far: ${project.total_cost_usd:.4f}")
        print(f"Project ID for further API calls: {project.id}")
    finally:
        db.close()


if __name__ == "__main__":
    main()
