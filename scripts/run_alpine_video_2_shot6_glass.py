#!/usr/bin/env python3
"""FORMA VIDEO #2 - SHOT 6: GLASS FACADE.

Only runnable after Edit 4 (roof/cladding complete) is generated AND
approved. Multiple glass panels progress across ~80% of the lake-facing
facade - this was Video #1's single biggest weakness (one panel then
magic-finished facade), so this must clearly show several panels going
in.
"""
from scripts.run_alpine_video_2_common import OUTPUT_DIR, run_gated_video_shot
from scripts.run_alpine_video_2_edit4_roof_complete import EDIT4_OUTPUT_PATH

MAX_SPEND_USD = 0.55
DURATION_SECONDS = 11.0

SHOT6_RAW_PATH = OUTPUT_DIR / "shot6_glass_raw.mp4"
JOB_STATE_PATH = OUTPUT_DIR / "shot6_last_job.json"

CAMERA_CLAUSE = "Camera view: the fixed viewpoint established by the previous edit, facing the lake-facing wall directly, held completely steady. No camera movement, no further angle change."

PROMPT = (
    "Vertical 9:16, realistic construction footage, documentary/observational style. "
    f"{CAMERA_CLAUSE} Continuing directly from the current state shown in the starting image.\n\n"
    "The cabin's shell is complete with dark cladding, and the lake-facing wall shows large empty "
    "framed openings for glass - no panels installed yet. The builder guides one large glass "
    "panel from a staged stack into the first opening, aligns it, seats it into the frame, and "
    "secures its edges, then moves to the next adjacent opening and repeats - installing panel "
    "after panel across the facade in one continuous direction. By the end of the clip, "
    "approximately 75 to 90 percent of the lake-facing facade is glazed, with only one or two "
    "openings still empty. No siding changes, no additional windows appear elsewhere, no second "
    "story, no furniture. The turquoise lake and mountains are visible through the installed "
    "glass, reinforcing the view it will offer. No posing, no presenter behavior."
)


def main() -> None:
    run_gated_video_shot(
        shot_key="shot6",
        title="SHOT 6 (GLASS FACADE)",
        upstream_path=EDIT4_OUTPUT_PATH,
        upstream_label="Edit 4 (Roof/Cladding Complete)",
        needs_frame_extraction=False,
        start_frame_path=EDIT4_OUTPUT_PATH,
        prompt=PROMPT,
        duration_seconds=DURATION_SECONDS,
        max_spend_usd=MAX_SPEND_USD,
        raw_output_path=SHOT6_RAW_PATH,
        job_state_path=JOB_STATE_PATH,
        review_checklist=[
            "HIGH PRIORITY: multiple distinct glass panels visibly installed in sequence",
            "~75-90% of the facade glazed by the end - not one panel then a jump",
            "lake/mountains visible through the installed glass",
        ],
        next_step_note=(
            "Do NOT run Edit 5 (Glass Complete + Interior Move) until you have reviewed and "
            "approved this clip. That is scripts/run_alpine_video_2_edit5_glass_complete.py."
        ),
    )


if __name__ == "__main__":
    main()
