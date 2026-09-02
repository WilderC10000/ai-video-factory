#!/usr/bin/env python3
"""Run one project all the way from an idea to a rendered first shot - including
generating its reference image first (image-to-video) - using only free mock
providers. This is how we prove the pipeline works end-to-end without needing
a frontend or spending any money.

Usage:
    python -m scripts.seed_demo_project
    python -m scripts.seed_demo_project "He converted a giant concrete pipe into a hidden luxury home."
"""
import sys
import time

from app.db import SessionLocal, init_db
from app.models.video_job import VideoJobStatus
from app.providers.image.mock import MockImageProvider
from app.providers.llm.mock import MockLLMProvider
from app.providers.video.mock import MockVideoProvider
from app.services import image_job_service, project_service, video_job_service

DEFAULT_IDEA = (
    "He buried an abandoned private jet beneath his backyard and turned it into "
    "an underground luxury bunker."
)


def main() -> None:
    idea = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_IDEA
    init_db()

    db = SessionLocal()
    llm = MockLLMProvider()
    image = MockImageProvider()
    video = MockVideoProvider()
    try:
        project = project_service.create_project(db, idea)
        print(f"[1/7] Created project {project.id} - status={project.status.value}")

        project = project_service.advance_to_concept(db, project, llm)
        print(f"[2/7] Concept ready - status={project.status.value}")
        print(f"      Title: {project.title}")
        print(f"      Continuity bible: {project.continuity_bible}")

        project = project_service.advance_to_script(db, project, llm)
        print(f"[3/7] Script ready - status={project.status.value}")
        print(f"      Hook: {project.script['hook']}")

        project = project_service.advance_to_storyboard(db, project, llm)
        print(f"[4/7] Storyboard ready - status={project.status.value}")
        print(f"      {len(project.shots)} shots created:")
        for shot in project.shots:
            print(f"        #{shot.shot_number} [{shot.status.value}] {shot.description}")

        first_shot = project.shots[0]
        print(f"\n[5/7] Generating reference image for shot #{first_shot.shot_number}...")
        first_shot = image_job_service.generate_shot_reference_image(db, first_shot, image)
        print(f"      Reference image saved to: {first_shot.reference_image_path}")

        print(f"\n[6/7] Submitting image-to-video generation job for shot #{first_shot.shot_number}...")
        job = video_job_service.submit_shot_video_job(db, first_shot, video)
        print(f"      Job {job.id} submitted to {job.provider_name} "
              f"(provider job id: {job.provider_job_id}), status={job.status.value}, "
              f"reference image: {job.reference_image_path}, "
              f"estimated cost=${job.estimated_cost_usd:.4f}")
        print(f"      Shot status is now {first_shot.status.value}")

        print("[7/7] Polling job status until it reaches a terminal state...")
        poll_count = 0
        while job.status not in (VideoJobStatus.COMPLETED, VideoJobStatus.FAILED, VideoJobStatus.TIMED_OUT):
            poll_count += 1
            job = video_job_service.poll_shot_video_job(db, job, video)
            print(f"      Poll #{poll_count}: status={job.status.value}")
            if job.status not in (VideoJobStatus.COMPLETED, VideoJobStatus.FAILED, VideoJobStatus.TIMED_OUT):
                time.sleep(0.2)  # just for readable output pacing, not required by the mock

        db.refresh(first_shot)
        print(f"\nFinal shot status: {first_shot.status.value}")
        if job.status == VideoJobStatus.COMPLETED:
            print(f"Clip saved to: {first_shot.video_file_path}")
            print(f"Actual video cost: ${job.actual_cost_usd:.4f}")
        else:
            print(f"Job did not complete: {job.error_message}")

        db.refresh(project)
        print(f"\nTotal project cost so far (image + video for 1 of {len(project.shots)} shots): "
              f"${project.total_cost_usd:.4f}")
        print(f"Project ID for further API calls: {project.id}")
    finally:
        db.close()


if __name__ == "__main__":
    main()
