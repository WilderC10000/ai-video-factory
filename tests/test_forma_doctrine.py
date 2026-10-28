"""The Creative Brain document and the prompt doctrine must stay in sync."""
import re
from pathlib import Path

from app.forma.doctrine import (
    PHASE_CLIP_COUNTS,
    PRODUCTION_LESSONS,
    SHOT_CLASSES,
    CAUSAL_CONSTRUCTION_RULES,
    CAUSAL_VIDEO_DOCTRINE,
    CLIP_CAUSAL_FIELDS,
    STILL_DOCTRINE,
    STILL_RULES,
    TEMPORAL_REALISM_RULES,
    VIDEO_DOCTRINE,
)

BRAIN = Path(__file__).resolve().parent.parent / "docs" / "forma" / "creative" / "FORMA_CREATIVE_BRAIN.md"


def _norm(text: str) -> str:
    return re.sub(r"[^a-z0-9|]+", " ", text.lower().replace("–", "-")).strip()


def test_every_rule_appears_in_the_creative_brain():
    brain = _norm(BRAIN.read_text(encoding="utf-8"))
    for rule in TEMPORAL_REALISM_RULES:
        assert _norm(rule) in brain, rule


def test_prompt_blocks_carry_the_core_rules():
    for block in (VIDEO_DOCTRINE, STILL_DOCTRINE):
        assert block.startswith("SKIP REPETITION, NOT EXPLANATION")
    assert "frontier" in VIDEO_DOCTRINE and "No magical" in VIDEO_DOCTRINE
    assert "frontier" in STILL_DOCTRINE and "regress" in STILL_DOCTRINE


def test_every_production_lesson_appears_in_the_creative_brain():
    brain = _norm(BRAIN.read_text(encoding="utf-8"))
    assert len(PRODUCTION_LESSONS) == 11
    for lesson in PRODUCTION_LESSONS:
        assert _norm(lesson) in brain, lesson


def test_every_shot_class_is_routed_in_the_creative_brain():
    brain = _norm(BRAIN.read_text(encoding="utf-8"))
    for route in SHOT_CLASSES.values():
        assert _norm(route.split(" -> ")[0]) in brain, route


def test_adaptive_clip_counts_are_in_the_creative_brain():
    brain = _norm(BRAIN.read_text(encoding="utf-8"))
    assert _norm("Clip count per phase adapts to complexity") in brain
    for phase in PHASE_CLIP_COUNTS:
        assert _norm(phase) in brain, phase
    assert max(PHASE_CLIP_COUNTS.values()) == 3 and PHASE_CLIP_COUNTS["static elapsed-time completion"] == 0


def test_every_still_rule_appears_in_the_creative_brain():
    brain = _norm(BRAIN.read_text(encoding="utf-8"))
    assert len(STILL_RULES) == 3
    for rule in STILL_RULES:
        assert _norm(rule) in brain, rule


def test_every_causal_construction_rule_appears_in_the_creative_brain():
    brain = _norm(BRAIN.read_text(encoding="utf-8"))
    assert len(CAUSAL_CONSTRUCTION_RULES) == 10
    for rule in CAUSAL_CONSTRUCTION_RULES:
        assert _norm(rule) in brain, rule
    assert "morphs" in CAUSAL_VIDEO_DOCTRINE and "never looks at the camera" in CAUSAL_VIDEO_DOCTRINE
    assert set(CLIP_CAUSAL_FIELDS) == {"first_touch", "tool", "tool_source", "method", "stationary", "progress",
                                       "frontier_start", "frontier_end"}
