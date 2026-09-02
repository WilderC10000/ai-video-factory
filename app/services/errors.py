"""Exceptions shared across the service layer. Kept in one place so both
project_service and video_job_service (and future services) raise/catch the
same types instead of each defining their own near-duplicates.
"""


class FactoryPausedError(Exception):
    """Raised when generation is attempted while the global pause flag is on."""


class InvalidTransitionError(Exception):
    """Raised when a project isn't in the right status for the requested step."""


class InvalidShotStateError(Exception):
    """Raised when a shot isn't in the right status for the requested operation."""


class InvalidJobStateError(Exception):
    """Raised when a video job isn't in the right status for the requested operation
    (e.g. polling a job that has already reached a terminal state)."""


class SpendLimitExceededError(Exception):
    """Raised when submitting a job would push a project's total cost past its
    configured maximum. Raised BEFORE any provider call is made, so no money
    (real or simulated) is ever committed past the limit."""


class MaxRegenerationsExceededError(Exception):
    """Raised when a shot has already been regenerated the maximum allowed
    number of times and a further regeneration is requested."""
