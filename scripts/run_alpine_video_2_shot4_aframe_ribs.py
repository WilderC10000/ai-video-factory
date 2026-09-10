#!/usr/bin/env python3
"""FORMA VIDEO #2 - SHOT 4: A-FRAME RIB FRAMING (HERO MOMENT).

Only runnable after Edit 2 (floor complete) is generated AND approved.
Starting image is edit2_floor_complete.jpg directly.

The signature shot of the video: multiple triangular A-frame ribs erected
sequentially down the long axis - △ -> △△ -> △△△ -> △△△△ -> △△△△△. The
builder stays at the active frontier; completed ribs stand fixed behind
him; no rib ever appears ahead of the active work zone. Highest retry
priority in the whole pipeline.
"""
from scripts.run_alpine_video_2_common import CABIN_SPEC, OUTPUT_DIR, run_gated_video_shot
from scripts.run_alpine_video_2_edit2_floor_complete import EDIT2_OUTPUT_PATH

MAX_SPEND_USD = 0.75
DURATION_SECONDS = 15.0

SHOT4_RAW_PATH = OUTPUT_DIR / "shot4_aframe_ribs_raw.mp4"
JOB_STATE_PATH = OUTPUT_DIR / "shot4_last_job.json"

CAMERA_CLAUSE = "Camera view: the fixed viewpoint established by the previous edit, looking down the cabin's long axis, held completely steady. No camera movement, no further angle change."

PROMPT = (
    "Vertical 9:16, realistic construction footage, documentary/observational style. "
    f"{CAMERA_CLAUSE} Continuing directly from the current state shown in the starting image.\n\n"
    f"The floor is complete - no structure above it yet. This cabin will become {CABIN_SPEC} "
    "The builder has pre-fabricated triangular A-frame rib sections staged nearby. He carries "
    "one rib to the floor's edge, raises it upright, and secures it plumb in position, then "
    "immediately moves to the next position along the floor's length and repeats - erecting "
    "ribs one after another in one continuous direction: the first rib stands alone, then two "
    "ribs, then three, then four, then five or more, each new rib appearing immediately adjacent "
    "to the last. The builder remains at the active working frontier throughout; every "
    "already-erected rib stays fixed exactly where it was placed, and no rib ever appears ahead "
    "of where the builder is currently working. By the end of the clip, approximately 80 to 90 "
    "percent of the rib structure along the cabin's length is erected, reading as a growing row "
    "of triangular timber frames. No roof, no glass, no siding appear yet. The lake, mountains, "
    "and shoreline remain clearly visible and important throughout, sharing the frame with the "
    "rising structure. No posing, no presenter behavior."
)


def main() -> None:
    run_gated_video_shot(
        shot_key="shot4",
        title="SHOT 4 (A-FRAME RIBS - HERO MOMENT)",
        upstream_path=EDIT2_OUTPUT_PATH,
        upstream_label="Edit 2 (Floor Complete)",
        needs_frame_extraction=False,
        start_frame_path=EDIT2_OUTPUT_PATH,
        prompt=PROMPT,
        duration_seconds=DURATION_SECONDS,
        max_spend_usd=MAX_SPEND_USD,
        raw_output_path=SHOT4_RAW_PATH,
        job_state_path=JOB_STATE_PATH,
        review_checklist=[
            "HIGHEST RETRY PRIORITY: multiple ribs erected sequentially, ~80-90% of the run",
            "builder stays at the active frontier - no rib appears ahead of him",
            "already-erected ribs remain fixed, plumb, evenly spaced - no geometry drift",
            "no roof, glass, or siding appear; lake/mountains share the frame",
        ],
        next_step_note=(
            "Do NOT run Edit 3 (Framing Complete) until you have reviewed and approved this clip "
            "carefully - retry here if geometry fails, a rib leapfrogs the builder, or the "
            "structure reads as asymmetrical/wrong. That is "
            "scripts/run_alpine_video_2_edit3_framing_complete.py."
        ),
    )


if __name__ == "__main__":
    main()
