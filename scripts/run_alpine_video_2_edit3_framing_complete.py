#!/usr/bin/env python3
"""FORMA VIDEO #2 - JUMP CUT 3: A-FRAME FRAMING COMPLETE.

Only runnable after Shot 4 (the hero shot) is generated AND approved.
Closes the last ~10-20% of the rib run and nudges the camera toward a
vantage suited to viewing the roof/sheathing.
"""
from scripts.run_alpine_video_2_common import CABIN_SPEC, MAX_SPEND_USD_EDIT, OUTPUT_DIR, run_gated_edit
from scripts.run_alpine_video_2_shot4_aframe_ribs import SHOT4_RAW_PATH

SHOT4_LAST_FRAME_PATH = OUTPUT_DIR / "edit3_source_frame.jpg"
EDIT3_OUTPUT_PATH = OUTPUT_DIR / "edit3_framing_complete.jpg"

EDIT_PROMPT = (
    "This is an intentional editorial jump cut - the same construction project, filmed again "
    "some time later, with the A-frame rib structure now fully complete along the cabin's entire "
    "length - not a different or redesigned build. Keep the underlying structure exactly as it "
    "is: the same floor footprint, the same rib spacing and style already established, the same "
    f"overall scale ({CABIN_SPEC}), the same site, lake, mountains, and shoreline geometry, the "
    "same builder identity, and the same lighting direction. Shift the camera only slightly - "
    "approximately 15 to 20 degrees - to a vantage well suited to viewing the roof and sheathing "
    "work to come. Advance ONLY the framing: complete the remaining ribs so the full triangular "
    "frame structure now stands along the entire length, matching what is already built. Do not "
    "add any roof surface, siding, glass, or door yet - this is purely completing the rib "
    "structure and a small camera reposition."
)


def main() -> None:
    run_gated_edit(
        edit_key="edit3_framing_complete",
        title="JUMP CUT 3 (FRAMING COMPLETE)",
        upstream_path=SHOT4_RAW_PATH,
        upstream_label="Shot 4 (A-Frame Ribs)",
        needs_frame_extraction=True,
        start_frame_path=SHOT4_LAST_FRAME_PATH,
        edit_prompt=EDIT_PROMPT,
        output_image_path=EDIT3_OUTPUT_PATH,
        max_spend_usd=MAX_SPEND_USD_EDIT,
        review_checklist=[
            "full rib structure complete along the entire cabin length, symmetrical",
            "no roof surface, siding, glass, or door yet",
            "camera repositioned toward the roof vantage; site/lighting preserved",
        ],
        next_step_note=(
            "Do NOT run Shot 5 (Roof + Cladding) until you have reviewed and approved this edit. "
            "That is scripts/run_alpine_video_2_shot5_roof_cladding.py."
        ),
    )


if __name__ == "__main__":
    main()
