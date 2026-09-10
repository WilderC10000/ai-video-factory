#!/usr/bin/env python3
"""FORMA VIDEO #2 - JUMP CUT 5: GLASS COMPLETE + MOVE TO INTERIOR.

Only runnable after Shot 6 is generated AND approved. Closes the last
1-2 glass panels AND moves the camera to an interior vantage looking out
through the glass at the lake - a bigger compositional change than the
usual ~15-20 degree nudge, since it crosses from exterior to interior.
"""
from scripts.run_alpine_video_2_common import MAX_SPEND_USD_EDIT, OUTPUT_DIR, run_gated_edit
from scripts.run_alpine_video_2_shot6_glass import SHOT6_RAW_PATH

SHOT6_LAST_FRAME_PATH = OUTPUT_DIR / "edit5_source_frame.jpg"
EDIT5_OUTPUT_PATH = OUTPUT_DIR / "edit5_glass_complete_interior.jpg"

EDIT_PROMPT = (
    "This is an intentional editorial jump cut - the same construction project, filmed again "
    "some time later, with the glass facade now fully installed - not a different or redesigned "
    "build. Keep the underlying structure exactly as it is: the same footprint, wall/roof "
    "proportions, window and door positions already established, the same site, lake, "
    "mountains, and shoreline geometry visible through the glass, the same builder identity, and "
    "the same lighting direction. Move the camera to a vantage INSIDE the cabin, looking out "
    "through the now-complete glass facade toward the lake and mountains - an empty, unfurnished "
    "interior space, structurally finished but with no furniture yet. Advance ONLY the glass: "
    "complete the one or two remaining panels so the entire lake-facing facade is now glazed, "
    "matching the panels already installed. Do not add any furniture, rugs, or decor yet - this "
    "is purely completing the glazing and moving the camera inside."
)


def main() -> None:
    run_gated_edit(
        edit_key="edit5_glass_complete",
        title="JUMP CUT 5 (GLASS COMPLETE + INTERIOR MOVE)",
        upstream_path=SHOT6_RAW_PATH,
        upstream_label="Shot 6 (Glass Facade)",
        needs_frame_extraction=True,
        start_frame_path=SHOT6_LAST_FRAME_PATH,
        edit_prompt=EDIT_PROMPT,
        output_image_path=EDIT5_OUTPUT_PATH,
        max_spend_usd=MAX_SPEND_USD_EDIT,
        review_checklist=[
            "entire lake-facing facade now fully glazed - no empty openings",
            "camera now shows a genuine interior vantage, looking out at the lake/mountains",
            "interior is empty/unfurnished, structurally finished; no furniture/decor yet",
            "this is a bigger compositional change than usual - check it doesn't drift into a "
            "different structure",
        ],
        next_step_note=(
            "Do NOT run Shot 7 (Interior Design) until you have reviewed and approved this edit. "
            "That is scripts/run_alpine_video_2_shot7_interior.py."
        ),
    )


if __name__ == "__main__":
    main()
