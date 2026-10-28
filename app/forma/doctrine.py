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

# Still doctrine for generated stills (Project #3 on): each still is an edit of the previous approved one.
STILL_RULES: tuple[str, ...] = (
    "End states are written as explicit final visual conditions, never as implied actions",
    "A removal end state says exactly what is gone, where the removed material ends up, and what must not appear yet",
    "Every 5 chained still edits, compare the current frame against the last major approved anchor and flag "
    "cumulative drift in geometry, camera, builder identity or environment before continuing",
)

# Causal construction for every video clip (from 2026-10-28, all projects). The model demonstrates real work;
# a jump cut advances time. Never a morph from the start frame to the end frame.
CAUSAL_CONSTRUCTION_RULES: tuple[str, ...] = (
    "WAN/KLING/SEEDANCE DEMONSTRATES, EDIT/JUMP CUT ADVANCES TIME",
    "The model never morphs the start frame into the end frame",
    "Every visible change is caused by the builder's physical action with a real tool or machine",
    "Tools and materials come from a visible place and go to a visible place; nothing appears, vanishes, teleports or duplicates",
    "A motion clip shows a believable sample of the work: 1-3 credible actions with real contact between builder, tool, material and structure",
    "Repetitive work keeps a visible COMPLETED | ACTIVE FRONTIER | UNTOUCHED progression; the builder works at the active frontier",
    "Real construction sequencing: earlier work stays intact and later work never appears before its prerequisites",
    "Observational documentary camera: stable geometry, the builder never looks at or presents to the camera, no posing",
    "Approved start and end pixels are authoritative: exact objects, geometry, builder position, materials and state",
    "If a clip needs more physical actions than its duration allows, do not force it: add an intermediate still, another clip, a different duration or a jump cut",
)

# What every motion clip must reason through before it may be submitted (beat["causal"] in project.json).
CLIP_CAUSAL_FIELDS: dict[str, str] = {
    "first_touch": "what the builder touches first",
    "tool": "the tool or machine required",
    "tool_source": "where that tool / material visibly comes from",
    "method": "how it is lifted, carried, cut, fastened, placed, removed, dumped, screwed, nailed, shoveled, rolled or installed",
    "stationary": "what must stay exactly where it is while the action happens",
    "progress": "what progress is realistically possible within the clip duration",
    "frontier_start": "the construction frontier at the start (completed | active | untouched)",
    "frontier_end": "the construction frontier at the end",
}

# Compact block appended to every motion-clip prompt.
CAUSAL_VIDEO_DOCTRINE = (
    "Real-world physics and building logic: the builder physically performs every change with his hands and the "
    "named tool; materials and debris are carried, shoveled, stacked or dumped to a visible place - nothing appears, "
    "vanishes, slides, teleports, duplicates or morphs; objects not being worked on stay exactly where they are. "
    "Show only the work that fits the clip at a real working pace. Observational documentary camera, locked and "
    "stable; the builder never looks at the camera or poses."
)

# Production lesson 11: shot difficulty class -> what kind of generation it gets.
SHOT_CLASSES: dict[str, str] = {
    "environmental": "simple environmental motion / reveal -> economical video model",
    "repetitive_labor": "broad repetitive labor -> stronger motion model with internal jump cuts",
    "precision": "precision tool / material interaction -> premium video model",
    "time_jump": "static completion / time jump -> image edit instead of video",
}

# Production lesson 11, clip count: how many clips a phase gets, by its complexity (0 = still edit only).
PHASE_CLIP_COUNTS: dict[str, int] = {
    "simple phase": 1,
    "medium phase": 2,
    "complex / repetitive phase": 3,  # "up to 3"
    "static elapsed-time completion": 0,
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
