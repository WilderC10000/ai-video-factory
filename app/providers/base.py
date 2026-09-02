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


class VideoProvider(ABC):
    """AI video generation provider (Veo, Kling, Runway, ...). Implemented in Milestone 2."""

    name: str

    @abstractmethod
    def generate_video(self, shot_prompt: str, **kwargs) -> "VideoResult":
        ...


@dataclass
class VideoResult:
    provider_name: str
    file_path: str
    cost_usd: float = 0.0
    meta: dict = field(default_factory=dict)


class ImageProvider(ABC):
    """AI keyframe/reference image provider. Implemented when needed by Milestone 2+."""

    name: str

    @abstractmethod
    def generate_image(self, prompt: str, **kwargs) -> "ImageResult":
        ...


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
