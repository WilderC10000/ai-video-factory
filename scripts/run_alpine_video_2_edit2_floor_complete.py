#!/usr/bin/env python3
"""FORMA VIDEO #2 - JUMP CUT 2: FLOOR COMPLETE.

Only runnable after Shot 3 is generated AND approved. Closes the last
~10-15% of decking and nudges the camera toward a vantage that shows the
cabin's long axis, setting up the A-frame rib hero shot.
"""
from scripts.run_alpine_video_2_common import MAX_SPEND_USD_EDIT, OUTPUT_DIR, run_gated_edit
from scripts.run_alpine_video_2_shot3_floorboards import SHOT3_RAW_PATH

SHOT3_LAST_FRAME_PATH = OUTPUT_DIR / "edit2_source_frame.jpg"
EDIT2_OUTPUT_PATH = OUTPUT_DIR / "edit2_floor_complete.jpg"

EDIT_PROMPT = (
    "This is an intentional editorial jump cut - the same construction project, filmed again "
    "some time later, with the floor now fully decked - not a different or redesigned build. "
    "Keep the underlying structure exactly as it is: the same floor footprint and proportions, "
    "the same site, lake, mountains, and shoreline geometry, the same builder identity, and the "
    "same lighting direction. Shift the camera to a nearby viewpoint that looks down the long "
    "axis of the floor, approximately 15 to 20 degrees from the previous angle, so the full "
    "length of the floor is visible - this will be the vantage for the next construction phase. "
    "Advance ONLY the decking: complete the remaining floorboards so the entire floor is now "
    "finished, matching the boards already installed. Do not add any walls, roof, or glass - this "
    "is purely completing the floor and repositioning the camera, not inventing new construction."
)


def main() -> None:
    run_gated_edit(
        edit_key="edit2_floor_complete",
        title="JUMP CUT 2 (FLOOR COMPLETE)",
        upstream_path=SHOT3_RAW_PATH,
        upstream_label="Shot 3 (Floorboards)",
        needs_frame_extraction=True,
        start_frame_path=SHOT3_LAST_FRAME_PATH,
        edit_prompt=EDIT_PROMPT,
        output_image_path=EDIT2_OUTPUT_PATH,
        max_spend_usd=MAX_SPEND_USD_EDIT,
        review_checklist=[
            "entire floor now fully decked, no exposed joists",
            "camera now shows the cabin's long axis, ready for the rib hero shot",
            "no walls, roof, or glass appear; site/lighting preserved",
        ],
        next_step_note=(
            "Do NOT run Shot 4 (A-Frame Ribs - the hero shot) until you have reviewed and "
            "approved this edit. That is scripts/run_alpine_video_2_shot4_aframe_ribs.py."
        ),
    )


if __name__ == "__main__":
    main()
