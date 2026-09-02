"""Business logic for generating one shot's reference/keyframe image through an
ImageProvider. Mirrors project_service.py / video_job_service.py's shape.

Unlike video, image generation is synchronous (real image providers like
fal.ai's FLUX return a finished image in seconds) - so there's no submit/poll
job table here, just one function that either returns the updated shot or
raises. The resulting image is stored on the shot and reused by
video_job_service when submitting an image-to-video job, and reused again on
every regeneration - we only pay for the image once per shot.
"""
from sqlalchemy.orm import Session

from app.config import settings
from app.models.project import CostRecord, OperationType, Shot
from app.providers.base import ImageGenerationRequest, ImageProvider, ImageProviderError
from app.services.errors import FactoryPausedError, SpendLimitExceededError

__all__ = [
    "FactoryPausedError",
    "SpendLimitExceededError",
    "generate_shot_reference_image",
]


def _check_not_paused() -> None:
    if settings.factory_paused:
        raise FactoryPausedError("The factory is globally paused (FACTORY_PAUSED=true). No generation will run.")


def _image_path_for_shot(shot: Shot) -> str:
    path = settings.project_data_path / shot.project_id / "images" / f"{shot.id}.jpg"
    return str(path)


def _record_cost(db: Session, shot: Shot, provider_name: str, cost_usd: float) -> CostRecord:
    record = CostRecord(
        project_id=shot.project_id,
        shot_id=shot.id,
        operation_type=OperationType.IMAGE,
        provider_name=provider_name,
        description="generate_reference_image",
        cost_usd=cost_usd,
    )
    db.add(record)
    return record


def generate_shot_reference_image(
    db: Session, shot: Shot, image_provider: ImageProvider, extra_params: dict | None = None
) -> Shot:
    """Generate (or regenerate) a shot's reference image. Enforces the pause
    flag and per-project spend limit BEFORE calling the provider, same as
    video job submission. Overwrites any existing reference image for this
    shot - call this only when you actually want to pay for a new one."""
    _check_not_paused()

    request = ImageGenerationRequest(prompt=shot.prompt or shot.description, extra_params=extra_params or {})
    estimated_cost = image_provider.estimate_cost(request)

    projected_total = shot.project.total_cost_usd + estimated_cost
    if projected_total > settings.max_spend_per_project_usd:
        raise SpendLimitExceededError(
            f"Generating this reference image would bring project {shot.project_id}'s total cost to "
            f"${projected_total:.2f}, exceeding its ${settings.max_spend_per_project_usd:.2f} limit."
        )

    result = image_provider.generate_image(request, _image_path_for_shot(shot))

    shot.reference_image_path = result.file_path
    _record_cost(db, shot, result.provider_name, result.cost_usd)

    db.commit()
    db.refresh(shot)
    return shot
