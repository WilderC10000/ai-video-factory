"""The eleven studio rooms and the agent that occupies each one.

Static registry: rooms are a fixed part of the studio's layout, not data.
`floor` / `col` place the room in the cutaway building: floor 0 is the roof (Command
Deck), col 0/2 are the left/right wings either side of the central production shaft.
`data_source` says what real state drives the room in v0.1; None means the
room has no real data behind it yet and must show as idle, not pretend.
"""
from dataclasses import dataclass


@dataclass(frozen=True)
class Room:
    id: str
    name: str
    agent_name: str
    agent_role: str
    floor: int
    col: int
    data_source: str | None


ROOMS: list[Room] = [
    Room("command_deck", "Command Deck", "Director", "Owns the production plan, stage gates and approvals",
         0, 1, "project stage + pending approvals"),
    Room("story_lab", "Story Lab", "Story Editor", "Shot list, beats and generation prompts",
         1, 0, "stage prompts in the manifest"),
    Room("continuity_office", "Continuity Office", "Continuity Supervisor",
         "Location bible, reference imagery, cross-shot consistency", 2, 0, "site reference stage"),
    Room("build_logic_workshop", "Build Logic Workshop", "Build Logic Engineer",
         "Construction-order checkpoints between shots", 3, 0, "checkpoint edit stages"),
    Room("finance_room", "Finance Room", "Producer", "Budget cap, spend and planned spend",
         2, 2, "manifest actual/estimated costs"),
    Room("render_bay", "Render Bay", "Render Wrangler", "Video generation jobs",
         3, 2, "video shot stages"),
    Room("edit_suite", "Edit Suite", "Editor", "Acceleration, trims and final assembly",
         4, 0, "final assembly stage"),
    Room("sound_booth", "Sound Booth", "Sound Designer", "Music, SFX and voice", 4, 2, None),
    Room("screening_room", "Screening Room / QA", "QA Reviewer", "Output review against each shot's checklist",
         5, 0, "outputs awaiting human review"),
    Room("analytics_observatory", "Analytics Observatory", "Analyst", "Post-publish performance",
         1, 2, None),
    Room("library_archive", "Library / Archive", "Archivist", "Every generated file on disk",
         5, 2, "files referenced by the manifest"),
]

ROOMS_BY_ID: dict[str, Room] = {r.id: r for r in ROOMS}
