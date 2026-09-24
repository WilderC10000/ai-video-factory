#!/usr/bin/env python3
"""FORMA VIDEO #2 - JUMP CUT 4: CLADDING COMPLETE.

Only runnable after Shot 5 is generated AND approved. Roof sheathing is
already 100% complete by Shot 5's own midpoint, so this only closes the
final ~15-25% of exterior cladding (per the FORMA continuity rule, a jump
cut may skip only a task's final repetitive 10-30%, never the majority)
and nudges the camera to face the lake-facing glass wall for Shot 6.
"""
from scripts.run_alpine_video_2_common import EditSpec, MAX_SPEND_USD_EDIT, OUTPUT_DIR, run_gated_edit
from scripts.run_alpine_video_2_shot5_roof_cladding import SHOT5_RAW_PATH

SHOT5_LAST_FRAME_PATH = OUTPUT_DIR / "edit4_source_frame.jpg"
EDIT4_OUTPUT_PATH = OUTPUT_DIR / "edit4_roof_complete.jpg"

EDIT_PROMPT = (
    "This is an intentional editorial jump cut - the same construction project, filmed again "
    "some time later, with the exterior cladding now fully complete - not a different or "
    "redesigned build. Keep the underlying structure exactly as it is: the same footprint, "
    "fully-sheathed roof, and rib positions already established, the same site, lake, "
    "mountains, and shoreline geometry, the same builder identity, and the same lighting "
    "direction. Shift the camera to face the lake-facing side of the cabin directly, "
    "approximately 15 to 20 degrees from the previous angle - this will be the vantage for "
    "installing the glass facade. Advance ONLY the cladding: complete the final remaining "
    "stretch of dark charcoal cladding across the exterior shell - the roof sheathing is "
    "already complete and stays exactly as it was - with the framed openings for the door and "
    "lake-facing glass clearly visible but still empty. Do not install any glass or door yet - "
    "this is purely finishing the last of the cladding and repositioning the camera."
)


SPEC = EditSpec(
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
        "cladding fully complete across the whole shell; roof sheathing unchanged from Shot 5",
        "framed door + glass openings visible but empty - no glass/door installed yet",
        "camera now faces the lake-facing wall directly for the glass shot",
    ],
    next_step_note=(
        "Do NOT run Shot 6 (Glass Facade) until you have reviewed and approved this edit. "
        "That is scripts/run_alpine_video_2_shot6_glass.py."
    ),
)


def main() -> None:
    run_gated_edit(SPEC)


if __name__ == "__main__":
    main()
