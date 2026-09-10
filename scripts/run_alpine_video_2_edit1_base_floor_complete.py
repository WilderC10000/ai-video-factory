#!/usr/bin/env python3
"""FORMA VIDEO #2 - JUMP CUT 1: BASE/FLOOR STRUCTURE COMPLETE.

Only runnable after Shot 2 is generated AND approved. Advances the
base/floor phase to completion (per the FORMA 90% Process Rule - Shot 2
already carried ~70-80%, this edit only closes the remaining stretch) and
applies a conservative ~15-20 degree camera nudge toward the floorboard-
laying angle.

Makes exactly ONE Nano Banana Pro EDIT call. No video call. No retries.
"""
import sys

from scripts.run_alpine_video_2_common import MAX_SPEND_USD_EDIT, OUTPUT_DIR, run_gated_edit
from scripts.run_alpine_video_2_shot2_base_floor import SHOT2_RAW_PATH

SHOT2_LAST_FRAME_PATH = OUTPUT_DIR / "edit1_source_frame.jpg"
EDIT1_OUTPUT_PATH = OUTPUT_DIR / "edit1_base_floor_complete.jpg"

EDIT_PROMPT = (
    "This is an intentional editorial jump cut - the same construction project, filmed again "
    "some time later, with the base and floor structure now fully complete - not a different or "
    "redesigned build. Keep the underlying structure exactly as it is: the same pad size and "
    "position, the same site, lake, mountains, and shoreline geometry, the same builder identity, "
    "and the same lighting direction. Shift the camera only slightly - approximately 15 to 20 "
    "degrees - to a nearby, modestly different viewpoint. Advance ONLY the base/floor structure: "
    "complete the remaining floor joists so the entire perimeter base and full joist run are now "
    "finished, matching the style and spacing already established. Do not add any decking, walls, "
    "roof, or glass - this is purely completing the joist structure and a small camera nudge, not "
    "inventing new construction."
)


def main() -> None:
    run_gated_edit(
        edit_key="edit1_base_floor_complete",
        title="JUMP CUT 1 (BASE/FLOOR COMPLETE)",
        upstream_path=SHOT2_RAW_PATH,
        upstream_label="Shot 2 (Base + Floor Structure)",
        needs_frame_extraction=True,
        start_frame_path=SHOT2_LAST_FRAME_PATH,
        edit_prompt=EDIT_PROMPT,
        output_image_path=EDIT1_OUTPUT_PATH,
        max_spend_usd=MAX_SPEND_USD_EDIT,
        review_checklist=[
            "entire floor joist structure now complete - no gaps",
            "no decking, walls, roof, or glass appear",
            "camera change modest (~15-20 degrees), pad/site/lighting preserved",
        ],
        next_step_note=(
            "Do NOT run Shot 3 (Floorboards) until you have reviewed and approved this edit. "
            "That is scripts/run_alpine_video_2_shot3_floorboards.py."
        ),
    )


if __name__ == "__main__":
    main()
