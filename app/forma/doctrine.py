"""FORMA temporal-realism doctrine, in the form prompts and reviews consume.

Human-readable source: docs/forma/creative/FORMA_CREATIVE_BRAIN.md. The two are
kept in sync by tests/test_forma_doctrine.py.
"""

TEMPORAL_REALISM_RULES: tuple[str, ...] = (
    "SKIP REPETITION, NOT EXPLANATION",
    "Checkpoints define states; clips must visibly perform the work between them",
    "One major construction idea per sequence",
    "Show 70-90% of the task before a jump cut",
    "Causal labor: visible progress must be caused by the builder's visible actions",
    "Construction frontier: COMPLETED | ACTIVE WORK | UNTOUCHED",
    "Stable cameras during tasks",
    "No magical spawning of materials, structure, or furniture",
    "Interior work is shown progressively too",
    "Temporal realism matters more than photorealistic individual frames",
)

# Compact block appended to every video prompt.
VIDEO_DOCTRINE = (
    "SKIP REPETITION, NOT EXPLANATION: the builder visibly performs the work, step after step, "
    "for the whole clip - every piece of progress is caused by his visible hands and tools, never "
    "appearing on its own. Materials come from a visible stack or pile and are carried, placed and "
    "fastened on-screen. The construction frontier stays readable in every frame: completed work | "
    "the active work area | untouched area, and it moves steadily in one direction. No magical "
    "spawning, no sudden completion, no one-action-finishes-everything."
)

# Compact block appended to every checkpoint still prompt.
STILL_DOCTRINE = (
    "SKIP REPETITION, NOT EXPLANATION. This still is one checkpoint in a continuous build: it must look like a real moment mid-way "
    "through the work, with a readable construction frontier (completed | active work | untouched), "
    "the builder physically doing the task, and every new material with a visible source nearby. "
    "Nothing already built may disappear or regress."
)
