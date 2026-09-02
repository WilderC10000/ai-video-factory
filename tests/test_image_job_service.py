from pathlib import Path

import pytest

from app.config import settings
from app.providers.base import ImageProviderError
from app.providers.image.mock import MockImageProvider
from app.providers.video.mock import MockVideoProvider
from app.services import image_job_service, video_job_service
from app.services.errors import FactoryPausedError, SpendLimitExceededError


@pytest.fixture()
def image():
    # Mirrors fal.ai FLUX.1 [schnell] pricing ($0.003/MP) by default; kept
    # explicit here so the test doesn't silently change if that default moves.
    return MockImageProvider(cost_per_megapixel=0.003)


def test_successful_generation(db_session, ready_shot, image):
    shot = image_job_service.generate_shot_reference_image(db_session, ready_shot, image)

    assert shot.reference_image_path is not None
    clip = Path(shot.reference_image_path)
    assert clip.exists()
    assert clip.stat().st_size > 0

    project = shot.project
    db_session.refresh(project)
    assert project.total_cost_usd == pytest.approx(0.003)
    image_costs = [c for c in project.cost_records if c.shot_id == shot.id]
    assert len(image_costs) == 1
    assert image_costs[0].cost_usd == pytest.approx(0.003)
    assert image_costs[0].provider_name == "mock-image"


def _image_cost_records(project):
    return [c for c in project.cost_records if c.provider_name == "mock-image"]


def test_failed_generation_leaves_shot_untouched(db_session, ready_shot, image):
    with pytest.raises(ImageProviderError):
        image_job_service.generate_shot_reference_image(
            db_session, ready_shot, image, extra_params={"mock_behavior": "fail"}
        )

    assert ready_shot.reference_image_path is None
    assert _image_cost_records(ready_shot.project) == []


def test_paused_factory_blocks_generation(db_session, ready_shot, image, monkeypatch):
    monkeypatch.setattr(settings, "factory_paused", True)

    with pytest.raises(FactoryPausedError):
        image_job_service.generate_shot_reference_image(db_session, ready_shot, image)

    assert ready_shot.reference_image_path is None


def test_spend_limit_blocks_generation(db_session, ready_shot, image, monkeypatch):
    monkeypatch.setattr(settings, "max_spend_per_project_usd", 0.001)

    with pytest.raises(SpendLimitExceededError):
        image_job_service.generate_shot_reference_image(db_session, ready_shot, image)

    assert ready_shot.reference_image_path is None
    assert _image_cost_records(ready_shot.project) == []


def test_regeneration_overwrites_the_previous_image(db_session, ready_shot, image):
    shot = image_job_service.generate_shot_reference_image(db_session, ready_shot, image)
    first_path = shot.reference_image_path

    shot = image_job_service.generate_shot_reference_image(db_session, shot, image)
    second_path = shot.reference_image_path

    # Same destination path (keyed by shot id) - regenerating overwrites in place.
    assert first_path == second_path
    project = shot.project
    db_session.refresh(project)
    # Two separate CostRecords though - we paid for the image twice.
    assert len(_image_cost_records(project)) == 2


# ---------------------------------------------------------------------------
# Wiring into video generation: a shot with a reference image should submit
# as image-to-video automatically, and regenerating the video should reuse
# the same image rather than paying for a new one.
# ---------------------------------------------------------------------------


def test_video_job_uses_shots_reference_image_automatically(db_session, ready_shot, image):
    shot = image_job_service.generate_shot_reference_image(db_session, ready_shot, image)
    reference_path = shot.reference_image_path

    video = MockVideoProvider()
    job = video_job_service.submit_shot_video_job(db_session, shot, video)

    assert job.reference_image_path == reference_path


def test_regenerating_video_reuses_existing_reference_image(db_session, ready_shot, image):
    shot = image_job_service.generate_shot_reference_image(db_session, ready_shot, image)
    reference_path = shot.reference_image_path

    video = MockVideoProvider()
    job = video_job_service.submit_shot_video_job(
        db_session, shot, video, extra_params={"mock_behavior": "fail"}
    )
    video_job_service.poll_shot_video_job(db_session, job, video)  # -> shot FAILED

    new_job = video_job_service.regenerate_shot_video(db_session, shot, video)

    assert new_job.reference_image_path == reference_path
    # No new image cost was recorded - only the one image + two video jobs.
    project = shot.project
    db_session.refresh(project)
    image_cost_count = len([c for c in project.cost_records if c.provider_name == "mock-image"])
    assert image_cost_count == 1
