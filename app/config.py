"""Central place for all configuration. Values come from environment variables
(or a local .env file) so secrets never get hard-coded or committed."""
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

# Project root = two levels up from this file (app/config.py -> app -> root)
ROOT_DIR = Path(__file__).resolve().parent.parent


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=ROOT_DIR / ".env", extra="ignore")

    database_url: str = "sqlite:///./data/videofactory.db"
    project_data_dir: str = "./data/projects"

    # Global kill switch. When True, no provider (mock or real) should run generation.
    factory_paused: bool = False

    # Spending guardrails. Not enforced yet (Milestone 9), but recorded here from day one
    # so the rest of the system can start reading/checking them incrementally.
    max_spend_per_project_usd: float = 5.00
    max_daily_spend_usd: float = 20.00
    max_regenerations_per_shot: int = 3

    # How long (wall-clock seconds since a job started) we'll wait for a video
    # provider before giving up and marking the job TIMED_OUT.
    video_job_timeout_seconds: int = 300
    # How many times a single poll can hit a transient provider error (network
    # blip, etc.) before the job is given up on and marked FAILED. This is
    # separate from Shot.regeneration_count, which tracks whole new attempts.
    max_job_poll_retries: int = 3

    # FORMA Virtual Studio execution. "disabled" (default): the studio records
    # approvals/rejections but can never launch a pipeline stage. "mock": stages run
    # with mock providers against a sandbox copy of the data (studio_data_dir must
    # NOT be ./data - see scripts/studio_sandbox.py). "live": real, paid provider calls
    # on the real ./data manifests, each one still gated by a confirm click in the UI.
    studio_execution_mode: str = "disabled"
    studio_data_dir: str = "./data"
    # How long a live studio job waits on the provider (queue + generation) before
    # giving up locally. Giving up never cancels the provider job; a timed-out job
    # can be finished later with the studio's free Recover action.
    studio_live_wait_timeout_seconds: int = 2700  # 45 min - fal queues have exceeded 15 min

    # Real provider keys - not used by anything active yet. The fal.ai adapters
    # (app/providers/video/fal.py, app/providers/image/fal.py) read this, but
    # they are not wired into the app as the active provider until explicitly
    # approved and switched on.
    fal_api_key: str | None = None
    openai_api_key: str | None = None
    anthropic_api_key: str | None = None

    @property
    def studio_data_path(self) -> Path:
        return (ROOT_DIR / self.studio_data_dir).resolve()

    @property
    def project_data_path(self) -> Path:
        path = (ROOT_DIR / self.project_data_dir).resolve()
        path.mkdir(parents=True, exist_ok=True)
        return path


settings = Settings()
