#!/usr/bin/env python3
"""FORMA VIDEO #2 - SHOT 3: FLOORBOARDS.

Only runnable after Edit 1 (base/floor complete) is generated AND
approved. Starting image is edit1_base_floor_complete.jpg directly - no
frame extraction needed.

Highly satisfying decking sweep: boards laid in rapid succession across
~85-90% of the floor, one clear frontier (INSTALLED FLOOR | BUILDER |
EXPOSED JOISTS). This is the first real test of the 90% Process Rule.
"""
from scripts.run_alpine_video_2_common import OUTPUT_DIR, run_gated_video_shot
from scripts.run_alpine_video_2_edit1_base_floor_complete import EDIT1_OUTPUT_PATH

MAX_SPEND_USD = 0.65
DURATION_SECONDS = 13.0

SHOT3_RAW_PATH = OUTPUT_DIR / "shot3_floorboards_raw.mp4"
JOB_STATE_PATH = OUTPUT_DIR / "shot3_last_job.json"

CAMERA_CLAUSE = "Camera view: the fixed viewpoint established by the previous edit, held completely steady. No camera movement, no further angle change."

PROMPT = (
    "Vertical 9:16, realistic construction footage, documentary/observational style. "
    f"{CAMERA_CLAUSE} Continuing directly from the current state shown in the starting image.\n\n"
    "The base and floor joist structure is complete - no decking yet. The builder lays floorboard "
    "after floorboard in rapid succession, each one visibly picked up from a staged board stack, "
    "positioned onto the joists, and secured, before moving immediately to the next adjacent "
    "position - sweeping steadily across the floor in one continuous direction. The frontier "
    "reads clearly: installed floor on one side, the builder actively working at the current "
    "position, exposed joists still ahead until reached. By the end of the clip, approximately "
    "85 to 90 percent of the floor is decked, with only a small section of exposed joists "
    "remaining. No walls, no roof, no glass appear. The lake, mountains, and shoreline remain "
    "clearly visible and important. No posing, no presenter behavior."
)


def main() -> None:
    run_gated_video_shot(
        shot_key="shot3",
        title="SHOT 3 (FLOORBOARDS)",
        upstream_path=EDIT1_OUTPUT_PATH,
        upstream_label="Edit 1 (Base/Floor Complete)",
        needs_frame_extraction=False,
        start_frame_path=EDIT1_OUTPUT_PATH,
        prompt=PROMPT,
        duration_seconds=DURATION_SECONDS,
        max_spend_usd=MAX_SPEND_USD,
        raw_output_path=SHOT3_RAW_PATH,
        job_state_path=JOB_STATE_PATH,
        review_checklist=[
            "floorboards sweep across ~85-90% of the floor - not just one or two boards",
            "INSTALLED FLOOR | BUILDER | EXPOSED JOISTS frontier reads clearly, one direction",
            "no walls, roof, or glass appear; lake/mountains remain visually important",
        ],
        next_step_note=(
            "Do NOT run Edit 2 (Floor Complete) until you have reviewed and approved this clip. "
            "That is scripts/run_alpine_video_2_edit2_floor_complete.py."
        ),
    )


if __name__ == "__main__":
    main()
