#!/usr/bin/env python3
"""FORMA VIDEO #2 - SHOT 8: FINAL REVEAL.

Only runnable after Edit 6 (exterior reveal viewpoint) is generated AND
approved. Deliberately the SAFEST possible reveal method, per explicit
instruction: no ambitious in-generation interior-to-exterior camera move.
Edit 6 already established a wide exterior vantage of the finished cabin,
so this shot only needs a simple Wan pull-back/widening from that already-
exterior composition - a clean exterior hero reveal, nothing more ambitious.

This is the terminal shot of the pipeline. No edit follows it.
"""
from scripts.run_alpine_video_2_common import OUTPUT_DIR, run_gated_video_shot
from scripts.run_alpine_video_2_edit6_exterior_reveal_viewpoint import EDIT6_OUTPUT_PATH

MAX_SPEND_USD = 0.25
DURATION_SECONDS = 5.0

SHOT8_RAW_PATH = OUTPUT_DIR / "shot8_reveal_raw.mp4"
JOB_STATE_PATH = OUTPUT_DIR / "shot8_last_job.json"

CAMERA_CLAUSE = (
    "Camera view: starting from the exact exterior vantage established in the starting image, "
    "then slowly and smoothly pulling back / widening to reveal more of the surrounding lake, "
    "mountains, and shoreline around the finished cabin. No cuts, no swooping or orbiting move, "
    "no push toward the structure - a simple, steady pull-back only."
)

PROMPT = (
    "Vertical 9:16, realistic footage, documentary/observational style. "
    f"{CAMERA_CLAUSE} Continuing directly from the current state shown in the starting image.\n\n"
    "The cabin is fully finished - complete dark cladding, complete lake-facing glass facade, "
    "furnished interior faintly visible through the glass - sitting on the rocky peninsula with "
    "the turquoise glacial lake, snowcapped mountains, and evergreen shoreline around it in warm "
    "late-afternoon light. No construction activity of any kind, no builder visible, no tools or "
    "equipment remaining on site. As the camera pulls back, the full context of the finished "
    "cabin against the dramatic landscape is revealed as the final hero image of the piece. No "
    "posing, no presenter behavior, no text overlays."
)


def main() -> None:
    run_gated_video_shot(
        shot_key="shot8",
        title="SHOT 8 (FINAL REVEAL)",
        upstream_path=EDIT6_OUTPUT_PATH,
        upstream_label="Edit 6 (Exterior Reveal Viewpoint)",
        needs_frame_extraction=False,
        start_frame_path=EDIT6_OUTPUT_PATH,
        prompt=PROMPT,
        duration_seconds=DURATION_SECONDS,
        max_spend_usd=MAX_SPEND_USD,
        raw_output_path=SHOT8_RAW_PATH,
        job_state_path=JOB_STATE_PATH,
        review_checklist=[
            "starts from the exact Edit 6 exterior composition - no jarring recomposition",
            "simple steady pull-back only - no orbit, no push-in, no interior-to-exterior move",
            "cabin reads fully finished - no construction activity, tools, or equipment visible",
            "lake/mountains/shoreline read as the final hero backdrop, not background scenery",
        ],
        next_step_note=(
            "This is the FINAL shot of the pipeline. Once approved, run the final assembly script: "
            "scripts/run_alpine_video_2_final_assembly.py"
        ),
    )


if __name__ == "__main__":
    main()
