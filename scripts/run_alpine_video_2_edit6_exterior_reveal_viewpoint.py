#!/usr/bin/env python3
"""FORMA VIDEO #2 - JUMP CUT 6: ESTABLISH EXTERIOR REVEAL VIEWPOINT.

Only runnable after Shot 7 (interior) is generated AND approved. Moves
the camera back OUTSIDE to a wide exterior vantage of the now fully
finished cabin - explicitly per instruction, the Reveal itself uses a
clean exterior pull-back, NOT an ambitious in-generation interior-to-
exterior camera move. This edit does that harder work as a still image
instead, so Shot 8 only has to do a simple pull-back from an
already-exterior composition.
"""
from scripts.run_alpine_video_2_common import CABIN_SPEC, LOCATION_BIBLE, MAX_SPEND_USD_EDIT, OUTPUT_DIR, run_gated_edit
from scripts.run_alpine_video_2_shot7_interior import SHOT7_RAW_PATH

SHOT7_LAST_FRAME_PATH = OUTPUT_DIR / "edit6_source_frame.jpg"
EDIT6_OUTPUT_PATH = OUTPUT_DIR / "edit6_exterior_reveal_viewpoint.jpg"

EDIT_PROMPT = (
    "This is an intentional editorial jump cut - the same construction project, filmed again "
    "some time later, moving the camera back outside the now fully finished cabin - not a "
    "different or redesigned build. Keep the underlying structure exactly as it is: "
    f"{CABIN_SPEC}, with the same footprint, roof, cladding, and glass already established. "
    f"Keep the site exactly as established: {LOCATION_BIBLE}. Keep the same furnished interior "
    "visible through the glass (bed, bench/table, rug), the same builder identity, and the same "
    "lighting direction. Move the camera to a wide exterior vantage that shows the entire "
    "completed cabin against the lake and mountains, positioned and framed so a smooth pull-back "
    "from here would naturally reveal the full landscape - the cabin should occupy a moderate "
    "portion of the frame, not fill it entirely, leaving clear room for the lake, mountains, and "
    "shoreline around it. Do not add any new construction or change anything about the finished "
    "cabin - this is purely re-establishing the camera outside."
)


def main() -> None:
    run_gated_edit(
        edit_key="edit6_exterior_reveal_viewpoint",
        title="JUMP CUT 6 (EXTERIOR REVEAL VIEWPOINT)",
        upstream_path=SHOT7_RAW_PATH,
        upstream_label="Shot 7 (Interior Design)",
        needs_frame_extraction=True,
        start_frame_path=SHOT7_LAST_FRAME_PATH,
        edit_prompt=EDIT_PROMPT,
        output_image_path=EDIT6_OUTPUT_PATH,
        max_spend_usd=MAX_SPEND_USD_EDIT,
        review_checklist=[
            "full completed cabin now visible from outside - matches everything built so far",
            "cabin occupies a moderate frame share, leaving clear room for lake/mountains",
            "this is a large compositional change (interior->exterior) - check carefully for "
            "structure identity drift before proceeding",
        ],
        next_step_note=(
            "Do NOT run Shot 8 (Final Reveal) until you have reviewed and approved this edit - "
            "it is the foundation of the whole reveal. That is "
            "scripts/run_alpine_video_2_shot8_reveal.py."
        ),
    )


if __name__ == "__main__":
    main()
