#!/usr/bin/env python3
"""FORMA VIDEO #2 - SHOT 5: ROOF + EXTERIOR CLADDING.

Only runnable after Edit 3 (framing complete) is generated AND approved.
Roof sheathing completes fully partway through the clip, then dark
exterior cladding gets its own visible source (a separate staged stack)
and installation action (carried, positioned, fastened) and sweeps to
~75-85% coverage by the end - per the FORMA continuity rule, a jump cut
may only skip a task's final repetitive 10-30%, never the majority, and
every major finish needs a visible source and installation before it
reads as complete.
"""
from scripts.run_alpine_video_2_common import OUTPUT_DIR, VideoShotSpec, run_gated_video_shot
from scripts.run_alpine_video_2_edit3_framing_complete import EDIT3_OUTPUT_PATH

MAX_SPEND_USD = 0.60
DURATION_SECONDS = 12.0

SHOT5_RAW_PATH = OUTPUT_DIR / "shot5_roof_cladding_raw.mp4"
JOB_STATE_PATH = OUTPUT_DIR / "shot5_last_job.json"

CAMERA_CLAUSE = "Camera view: the fixed viewpoint established by the previous edit, held completely steady. No camera movement, no further angle change."

PROMPT = (
    "Vertical 9:16, realistic construction footage, documentary/observational style. "
    f"{CAMERA_CLAUSE} Continuing directly from the current state shown in the starting image.\n\n"
    "The A-frame rib structure stands complete along the cabin's full length - no roof surface, "
    "no siding, no glass yet. The builder installs roof sheathing panels one after another, each "
    "carried from a staged stack and fastened onto the sloped rib faces, sweeping steadily from "
    "one end of the roof toward the other. By roughly the midpoint of the clip, the roof sheathing "
    "is fully complete across the entire roof. The builder then moves to a separate staged stack "
    "of dark charcoal cladding panels, carries one panel at a time to the exterior wall, positions "
    "it against the sheathing, and fastens it in place, sweeping steadily across the exterior in "
    "one continuous direction. By the end of the clip, approximately 75 to 85 percent of the "
    "exterior cladding is installed, with only a small final section of bare sheathing remaining. "
    "No glass or door appears in the framed openings yet. The lake, mountains, and shoreline "
    "remain clearly visible around the structure. No posing, no presenter behavior."
)


SPEC = VideoShotSpec(
    shot_key="shot5",
    title="SHOT 5 (ROOF + EXTERIOR CLADDING)",
    upstream_path=EDIT3_OUTPUT_PATH,
    upstream_label="Edit 3 (Framing Complete)",
    needs_frame_extraction=False,
    start_frame_path=EDIT3_OUTPUT_PATH,
    prompt=PROMPT,
    duration_seconds=DURATION_SECONDS,
    max_spend_usd=MAX_SPEND_USD,
    raw_output_path=SHOT5_RAW_PATH,
    job_state_path=JOB_STATE_PATH,
    review_checklist=[
        "roof sheathing reaches full 100% coverage partway through the clip, one clear direction",
        "cladding panels are each visibly carried from their own staged stack and fastened on - "
        "not simply appearing",
        "~75-85% of the exterior cladding installed by the end - majority shown, not skipped",
        "no glass or door in the framed openings yet; lake/mountains remain visible",
    ],
    next_step_note=(
        "Do NOT run Edit 4 (Roof/Cladding Complete) until you have reviewed and approved this "
        "clip. That is scripts/run_alpine_video_2_edit4_roof_complete.py."
    ),
)


def main() -> None:
    run_gated_video_shot(SPEC)


if __name__ == "__main__":
    main()
