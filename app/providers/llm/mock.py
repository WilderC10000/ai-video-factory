"""A free, deterministic LLM provider used until real OpenAI/Anthropic providers
are wired in (Milestone 8). It does no network calls and always costs $0.00.

Its job right now isn't to write good copy - it's to exercise the full
concept -> script -> storyboard -> continuity pipeline so we can prove the
architecture (state machine, continuity inheritance, cost tracking) works
before spending money on real generation.
"""
import re
import textwrap

from app.providers.base import ConceptResult, LLMProvider, ScriptResult, ShotPlan, StoryboardResult

# Generic 12-beat "buried object -> luxury reveal" shot template. A real LLM
# (Milestone 8) will generate bespoke beats per project; this fixed template
# is enough to validate that continuity + shot state machinery works end to end.
_SHOT_BEAT_TEMPLATE = [
    "Establishing shot of the ordinary backyard before any work begins - sets the hook.",
    "{subject} arrives on site / is revealed for the first time.",
    "Excavation begins: heavy machinery starts digging the pit.",
    "The pit deepens; crew inspects progress from the edge.",
    "{subject} is carefully lowered or positioned into the excavation.",
    "Structural reinforcement and waterproofing work begins around the {subject}.",
    "Interior framing: walls and rooms start taking shape inside the {subject}.",
    "Utilities pass: electrical wiring and plumbing being installed.",
    "Interior finishing: luxury materials, fixtures, and furniture going in.",
    "Exterior backfilling and landscaping restores the yard's surface.",
    "Final exterior shot: yard looks normal again, entrance/hatch visible.",
    "Dramatic reveal: camera moves through the entrance into the finished {end_use}.",
]

# Matches phrasing like "buried a pink submarine in his backyard and turned it
# into an underground luxury bunker" or "converted an enormous concrete pipe
# into a hidden luxury home" - pulls out the object being transformed and what
# it becomes. Falls back to the raw idea text if nothing matches; this is a
# best-effort heuristic, not real language understanding (that's Milestone 8).
_TRANSFORM_PATTERNS = [
    re.compile(
        r"buried\s+(?:an?|the)?\s*(?P<subject>.+?)\s+(?:in|beneath|under)\s+.+?"
        r"(?:turned|converted|transformed)\s+(?:it\s+)?into\s+(?:an?|the)?\s*(?P<end_use>.+?)[.!]?$",
        re.IGNORECASE,
    ),
    re.compile(
        r"converted\s+(?:an?|the)?\s*(?P<subject>.+?)\s+into\s+(?:an?|the)?\s*(?P<end_use>.+?)[.!]?$",
        re.IGNORECASE,
    ),
]


def _extract_subject_and_end_use(idea_text: str) -> tuple[str, str]:
    for pattern in _TRANSFORM_PATTERNS:
        match = pattern.search(idea_text)
        if match:
            return match.group("subject").strip(), match.group("end_use").strip()
    return idea_text.strip(), "luxury underground space"


class MockLLMProvider(LLMProvider):
    name = "mock-llm"

    def generate_concept(self, idea_text: str) -> ConceptResult:
        idea_text = idea_text.strip()
        title = textwrap.shorten(idea_text, width=60, placeholder="...")
        subject, end_use = _extract_subject_and_end_use(idea_text)

        concept = (
            f"A realistic, documentary-style transformation video: {idea_text} "
            "The video follows the project through excavation, construction, and "
            "finishing stages, ending on a dramatic reveal of the completed space. "
            "Presented as AI-generated entertainment content, not as real footage."
        )

        continuity_bible = {
            "original_idea": idea_text,
            "main_subject": subject,
            "end_use": end_use,
            "location": "a residential backyard",
            "characters": "a small unnamed construction crew; occasional narrator/owner voice",
            "materials_and_colors": "to be refined once a concrete subject/finish is chosen",
            "time_of_day": "daytime work shots, golden hour for the final reveal",
            "weather": "clear and consistent across all shots",
            "camera_style": "handheld documentary-style ground shots mixed with drone establishing shots",
            "architecture_style": "modern luxury interior finish, industrial/utilitarian exterior shell",
            "current_construction_state": "not started",
            "content_disclosure": "AI-generated entertainment content, not real documented footage",
        }

        return ConceptResult(
            provider_name=self.name,
            title=title,
            concept=concept,
            continuity_bible=continuity_bible,
            cost_usd=0.0,
            meta={"mock": True},
        )

    def generate_script(self, concept: str, continuity_bible: dict) -> ScriptResult:
        subject = continuity_bible.get("main_subject", "this project")
        end_use = continuity_bible.get("end_use", "something incredible")
        hook = f"They transformed {subject} into {end_use}... and the reveal will surprise you."

        beats = [
            {"narration": hook, "shot_description": "hook"},
            {
                "narration": "It all starts in an ordinary backyard, with an extraordinary idea.",
                "shot_description": "establishing",
            },
            {
                "narration": "Day by day, the excavation grows deeper.",
                "shot_description": "excavation",
            },
            {
                "narration": "Every detail is planned to turn this into something incredible.",
                "shot_description": "construction",
            },
            {
                "narration": "And after weeks of work, it's finally ready to reveal.",
                "shot_description": "reveal",
            },
        ]

        return ScriptResult(
            provider_name=self.name,
            script={"hook": hook, "beats": beats},
            cost_usd=0.0,
            meta={"mock": True},
        )

    def generate_storyboard(
        self, concept: str, script: dict, continuity_bible: dict
    ) -> StoryboardResult:
        subject = continuity_bible.get("main_subject", "the main structure")
        end_use = continuity_bible.get("end_use", "luxury underground space")

        shots = []
        for i, beat_template in enumerate(_SHOT_BEAT_TEMPLATE, start=1):
            description = beat_template.format(subject=subject, end_use=end_use)
            shots.append(ShotPlan(shot_number=i, description=description, target_duration_seconds=5.0))

        return StoryboardResult(
            provider_name=self.name,
            shots=shots,
            cost_usd=0.0,
            meta={"mock": True, "shot_count": len(shots)},
        )
