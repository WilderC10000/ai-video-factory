#!/usr/bin/env python3
"""FORMA VIDEO #2 - SHOT 7: INTERIOR DESIGN.

Only runnable after Edit 5 (glass complete + interior move) is generated
AND approved. Required phase for any FORMA structure with a habitable
interior - 2-3 focused, clearly readable furnishing actions, not an
overloaded list.
"""
from scripts.run_alpine_video_2_common import OUTPUT_DIR, run_gated_video_shot
from scripts.run_alpine_video_2_edit5_glass_complete import EDIT5_OUTPUT_PATH

MAX_SPEND_USD = 0.50
DURATION_SECONDS = 10.0

SHOT7_RAW_PATH = OUTPUT_DIR / "shot7_interior_raw.mp4"
JOB_STATE_PATH = OUTPUT_DIR / "shot7_last_job.json"

CAMERA_CLAUSE = "Camera view: the fixed interior viewpoint established by the previous edit, looking out through the glass toward the lake, held completely steady."

PROMPT = (
    "Vertical 9:16, realistic footage, documentary/observational style. "
    f"{CAMERA_CLAUSE} Continuing directly from the current state shown in the starting image.\n\n"
    "The interior is structurally finished but completely empty - no furniture, no rug, no "
    "fixtures. The builder carries in a compact bed platform and positions it against one wall, "
    "then places a mattress and simple bedding onto it, then carries in a small wooden bench or "
    "table and places it nearby, then unrolls a rug that sweeps across most of the floor as it "
    "is laid out. Each item is carried in and positioned in turn - no item simply appears already "
    "in place. By the end of the clip, the space reads as a warm, minimalist, uncluttered, "
    "premium small cabin interior with the lake and mountains still clearly visible through the "
    "glass. No posing, no presenter behavior."
)


def main() -> None:
    run_gated_video_shot(
        shot_key="shot7",
        title="SHOT 7 (INTERIOR DESIGN)",
        upstream_path=EDIT5_OUTPUT_PATH,
        upstream_label="Edit 5 (Glass Complete + Interior Move)",
        needs_frame_extraction=False,
        start_frame_path=EDIT5_OUTPUT_PATH,
        prompt=PROMPT,
        duration_seconds=DURATION_SECONDS,
        max_spend_usd=MAX_SPEND_USD,
        raw_output_path=SHOT7_RAW_PATH,
        job_state_path=JOB_STATE_PATH,
        review_checklist=[
            "each furnishing item (bed/mattress, bench/table, rug) is carried in and placed, "
            "not conjured in place",
            "rug sweeps across most of the floor, not just a corner",
            "interior reads warm/minimalist/premium; lake+mountains still visible through glass",
        ],
        next_step_note=(
            "Do NOT run Edit 6 (Exterior Reveal Viewpoint) until you have reviewed and approved "
            "this clip. That is scripts/run_alpine_video_2_edit6_exterior_reveal_viewpoint.py."
        ),
    )


if __name__ == "__main__":
    main()
