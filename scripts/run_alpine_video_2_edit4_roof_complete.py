#!/usr/bin/env python3
"""FORMA VIDEO #2 - JUMP CUT 4: ROOF + CLADDING COMPLETE.

Only runnable after Shot 5 is generated AND approved. Closes the last
stretch of sheathing/cladding and nudges the camera to face the
lake-facing glass wall for Shot 6.
"""
from scripts.run_alpine_video_2_common import MAX_SPEND_USD_EDIT, OUTPUT_DIR, run_gated_edit
from scripts.run_alpine_video_2_shot5_roof_cladding import SHOT5_RAW_PATH

SHOT5_LAST_FRAME_PATH = OUTPUT_DIR / "edit4_source_frame.jpg"
EDIT4_OUTPUT_PATH = OUTPUT_DIR / "edit4_roof_complete.jpg"

EDIT_PROMPT = (
    "This is an intentional editorial jump cut - the same construction project, filmed again "
    "some time later, with the roof and exterior cladding now fully complete - not a different "
    "or redesigned build. Keep the underlying structure exactly as it is: the same footprint, "
    "wall/roof proportions, and rib positions already established, the same site, lake, "
    "mountains, and shoreline geometry, the same builder identity, and the same lighting "
    "direction. Shift the camera to face the lake-facing side of the cabin directly, "
    "approximately 15 to 20 degrees from the previous angle - this will be the vantage for "
    "installing the glass facade. Advance ONLY the roof and cladding: complete the remaining "
    "sheathing and dark charcoal cladding across the entire exterior shell, with the framed "
    "openings for the door and lake-facing glass clearly visible but still empty. Do not install "
    "any glass or door yet - this is purely completing the shell and repositioning the camera."
)


def main() -> None:
    run_gated_edit(
        edit_key="edit4_roof_complete",
        title="JUMP CUT 4 (ROOF/CLADDING COMPLETE)",
        upstream_path=SHOT5_RAW_PATH,
        upstream_label="Shot 5 (Roof + Cladding)",
        needs_frame_extraction=True,
        start_frame_path=SHOT5_LAST_FRAME_PATH,
        edit_prompt=EDIT_PROMPT,
        output_image_path=EDIT4_OUTPUT_PATH,
        max_spend_usd=MAX_SPEND_USD_EDIT,
        review_checklist=[
            "roof/cladding fully complete across the whole shell",
            "framed door + glass openings visible but empty - no glass/door installed yet",
            "camera now faces the lake-facing wall directly for the glass shot",
        ],
        next_step_note=(
            "Do NOT run Shot 6 (Glass Facade) until you have reviewed and approved this edit. "
            "That is scripts/run_alpine_video_2_shot6_glass.py."
        ),
    )


if __name__ == "__main__":
    main()
