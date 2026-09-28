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
    "Distribute repetitive work with hard jump cuts: "
    "LOCAL ACTION → HARD JUMP CUT → REPOSITIONED LOCAL ACTION → HARD JUMP CUT → ADVANCED PHASE",
)

# Planning/routing lessons from Projects #1 and #2 - binding from Project #3 on.
PRODUCTION_LESSONS: tuple[str, ...] = (
    "One physical task per continuous shot",
    "Repetitive work uses hard editorial jump cuts: ACTION → CUT → REPOSITION → ACTION → CUT → PHASE ADVANCED",
    "Never ask a model to simulate an entire repetitive construction phase continuously",
    "Every visible change inside a continuous shot must be caused by visible labor",
    "Tools and materials have a plausible source and destination",
    "No unexplained object spawning or disappearing during a continuous shot",
    "Camera movement and construction complexity do not happen in the same shot",
    "Approved checkpoint pixels are authoritative",
    "Use a phase-completion image edit when a jump in elapsed time is more believable than video generation",
    "Add checkpoints whenever they reduce the physical change one clip must produce",
    "Select the video model by task difficulty, never one model for the whole video",
)

# Production lesson 11: shot difficulty class -> what kind of generation it gets.
SHOT_CLASSES: dict[str, str] = {
    "environmental": "simple environmental motion / reveal -> economical video model",
    "repetitive_labor": "broad repetitive labor -> stronger motion model with internal jump cuts",
    "precision": "precision tool / material interaction -> premium video model",
    "time_jump": "static completion / time jump -> image edit instead of video",
}

# Appended to the prompt of every repetitive physical-work clip (rule 11), after its shot list.
BEATS_DOCTRINE = (
    "Within each shot: one continuous take; every bit of progress is caused by the builder's visible hands and "
    "tools, showing the full work cycle; nothing vanishes, appears or morphs - no debris or material disappearing "
    "on its own. Across each hard cut only elapsed time changes: the builder is repositioned further along the "
    "work area, which is visibly further advanced, and tool, wheelbarrow and material positions may differ; the "
    "railcar, location, light, builder and clothing never change. No camera glide, pan or zoom between work "
    "locations - hard editorial cuts only. No dissolves, no on-screen text."
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
