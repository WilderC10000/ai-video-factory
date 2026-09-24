"""The Creative Brain document and the prompt doctrine must stay in sync."""
import re
from pathlib import Path

from app.forma.doctrine import STILL_DOCTRINE, TEMPORAL_REALISM_RULES, VIDEO_DOCTRINE

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
