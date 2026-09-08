"""Provider abstraction layer.

The rest of the application only ever talks to these interfaces (e.g.
`llm_provider.generate_script(...)`), never to a specific vendor SDK. Swapping
OpenAI for Anthropic, or Veo for Kling, means writing one new file under
`providers/<kind>/` and changing which one is instantiated - nothing else in
the app changes.

Every provider call returns a result object that carries its own cost, so the
service layer can write a CostRecord without needing to know how each
provider's pricing works.
"""
import enum
from abc import ABC, abstractmethod
from dataclasses import dataclass, field


@dataclass
class ConceptResult:
    provider_name: str
    title: str
    concept: str
    continuity_bible: dict
    cost_usd: float = 0.0
    meta: dict = field(default_factory=dict)


@dataclass
class ScriptResult:
    provider_name: str
    script: dict  # {"hook": str, "beats": [{"narration": str, "shot_description": str}, ...]}
    cost_usd: float = 0.0
    meta: dict = field(default_factory=dict)


@dataclass
class ShotPlan:
    shot_number: int
    description: str
    target_duration_seconds: float = 5.0


@dataclass
class StoryboardResult:
    provider_name: str
    shots: list[ShotPlan]
    cost_usd: float = 0.0
    meta: dict = field(default_factory=dict)


class LLMProvider(ABC):
    """Text-generation provider: concepts, scripts, storyboards, prompts, QA critique."""

    name: str

    @abstractmethod
    def generate_concept(self, idea_text: str) -> ConceptResult:
        """Turn a raw idea into a refined concept + an initial continuity bible."""

    @abstractmethod
    def generate_script(self, concept: str, continuity_bible: dict) -> ScriptResult:
        """Turn a concept into a hook + narration beats."""

    @abstractmethod
    def generate_storyboard(
        self, concept: str, script: dict, continuity_bible: dict
    ) -> StoryboardResult:
        """Break the script into individual shot descriptions (10-20 beats)."""


class VideoProviderError(Exception):
    """Raised by a VideoProvider implementation for any provider-side failure:
    network error, auth failure, rate limit, invalid request, provider outage,
    etc. The service layer treats these as potentially transient and applies
    its own retry policy rather than each provider implementing its own."""


class ProviderJobState(str, enum.Enum):
    """The provider's own view of a job's progress. Deliberately smaller than
    our DB-level VideoJobStatus (app/models/video_job.py): providers only ever
    tell us "still working", "done", or "failed" - concepts like PENDING
    (not yet submitted) or TIMED_OUT (we gave up waiting) are things our own
    service layer decides, not something a provider reports."""

    PROCESSING = "PROCESSING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"


@dataclass
class VideoGenerationRequest:
    """Everything a provider needs to start generating one shot's clip.

    Setting `reference_image_path` turns this into an image-to-video request;
    leaving it unset is a plain text-to-video request. Using one request type
    for both keeps the interface small - most real providers accept the same
    "prompt + optional reference image" shape for either mode.
    """

    prompt: str
    reference_image_path: str | None = None
    duration_seconds: float = 5.0
    aspect_ratio: str = "9:16"
    # Provider-specific knobs (e.g. motion strength, seed, model variant) that
    # don't belong in the generic interface. Providers should document what
    # keys they read from here.
    extra_params: dict = field(default_factory=dict)


@dataclass
class SubmittedVideoJob:
    """Returned immediately after submitting a job - the provider has accepted
    the request and started work asynchronously, but the clip isn't ready yet."""

    provider_name: str
    provider_job_id: str
    estimated_cost_usd: float = 0.0
    meta: dict = field(default_factory=dict)


@dataclass
class VideoJobStatusResult:
    """Returned by a single poll of a previously submitted job."""

    status: ProviderJobState
    output_url: str | None = None  # set once status == COMPLETED
    actual_cost_usd: float | None = None  # set once status == COMPLETED (or known on FAILED)
    error_message: str | None = None  # set when status == FAILED
    meta: dict = field(default_factory=dict)


class VideoProvider(ABC):
    """AI video generation provider (Veo, Kling, Runway, ...).

    Modeled as submit-then-poll because that's how every real async video
    generation API works: you kick off a job and it renders in the background
    for anywhere from seconds to minutes. The service layer (video_job_service)
    owns retry/timeout/spend-limit policy; a provider implementation should
    just talk to its vendor's API and translate the response into these types.
    """

    name: str

    @abstractmethod
    def estimate_cost(self, request: VideoGenerationRequest) -> float:
        """Estimate the cost in USD for this request BEFORE submitting it, so
        the caller can enforce spending limits before any money is committed."""

    @abstractmethod
    def submit_video_job(self, request: VideoGenerationRequest) -> SubmittedVideoJob:
        """Submit a generation job. Must return quickly (does not block until
        the video is ready) and raise VideoProviderError on failure to submit."""

    @abstractmethod
    def get_job_status(self, provider_job_id: str, meta: dict | None = None) -> VideoJobStatusResult:
        """Check on a previously submitted job. `meta` is whatever
        SubmittedVideoJob.meta held at submission time (e.g. status/result
        URLs the provider handed back) - a provider that needs it to avoid
        reconstructing URLs itself (see providers/video/fal.py) should
        prefer it; a provider that doesn't need it can ignore the argument.
        `meta` may be None (e.g. when recovering a job whose original
        submission response wasn't saved) - implementations must handle
        that by falling back to whatever they'd otherwise do.
        Raise VideoProviderError for a transient failure to check (e.g.
        network error) - the caller retries."""

    @abstractmethod
    def download_result(self, provider_job_id: str, output_url: str, destination_path: str) -> str:
        """Download the completed clip to local disk at destination_path (the
        caller ensures the parent directory exists). Returns the path actually
        written, and should raise VideoProviderError on failure."""


class ImageProviderError(Exception):
    """Raised by an ImageProvider implementation for any provider-side failure."""


@dataclass
class ImageGenerationRequest:
    """Everything a provider needs to generate one reference/keyframe image.

    Unlike video, image generation from providers like fal.ai's FLUX is fast
    (seconds) and synchronous - no submit/poll dance needed. `width`/`height`
    default to a small 9:16 size that stays under 1 megapixel, since image
    providers commonly bill per-megapixel rounded up - keeping the default
    small keeps the default cheap.
    """

    prompt: str
    width: int = 576
    height: int = 1024
    extra_params: dict = field(default_factory=dict)


@dataclass
class ImageEditRequest:
    """A prompt-guided edit of one or more EXISTING images (e.g. correcting a
    hand/tool pose in an already-generated reference image) - as opposed to
    ImageGenerationRequest, which generates from a text prompt alone with no
    input image. Not part of the ImageProvider ABC below: editing is a
    fal.ai-specific capability (Nano Banana Pro Edit) with no mock/other
    provider implementation yet, so it lives as a concrete-only method on
    FalImageProvider - same pattern as FalVideoProvider's reference-image
    upload helper, which also isn't part of the VideoProvider ABC.
    """

    prompt: str
    reference_image_paths: list[str]
    extra_params: dict = field(default_factory=dict)


class ImageProvider(ABC):
    """AI keyframe/reference image provider (used to give a video provider a
    consistent starting frame for image-to-video generation)."""

    name: str

    @abstractmethod
    def estimate_cost(self, request: ImageGenerationRequest) -> float:
        """Estimate the cost in USD for this request BEFORE generating it, so
        the caller can enforce spending limits before any money is committed."""

    @abstractmethod
    def generate_image(self, request: ImageGenerationRequest, destination_path: str) -> "ImageResult":
        """Generate the image and save it to destination_path (the caller
        ensures the parent directory exists). Raise ImageProviderError on
        failure. Synchronous - returns once the image is ready."""


@dataclass
class ImageResult:
    provider_name: str
    file_path: str
    cost_usd: float = 0.0
    meta: dict = field(default_factory=dict)


class VoiceProvider(ABC):
    """AI voiceover provider. Implemented in Milestone 4."""

    name: str

    @abstractmethod
    def generate_voice(self, script_text: str, **kwargs) -> "VoiceResult":
        ...


@dataclass
class VoiceResult:
    provider_name: str
    file_path: str
    cost_usd: float = 0.0
    meta: dict = field(default_factory=dict)
