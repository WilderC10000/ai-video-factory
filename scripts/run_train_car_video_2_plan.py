#!/usr/bin/env python3
"""FORMA VIDEO #2 (TRAIN CAR) - 20-CHECKPOINT PRODUCTION PLAN.

Abandoned Train Car -> Luxury Forest Cabin. Canonical source:
docs/forma/creative/FORMA_20_Checkpoint_Train_Car_Storyboard_Updated.pptx

Pure local planning. NO API calls, NO FAL_API_KEY needed, NO spend. This
module is the single source of truth for the checkpoint definitions, the
continuity anchors, the locked camera setups, and the checkpoint-to-clip
stage plan with its cost estimate. It deliberately does NOT reuse the
Alpine 8-stage pacing model.

Permanent rules this plan is built to enforce:
  - No magical construction: a checkpoint wherever a viewer could ask
    "how did that get there?"
  - One major construction idea per video transition.
  - Jump cuts may skip only the repetitive tail of a task (show 70-90%).
  - The builder's visible action causes the visible progress.
  - Same railcar, location, proportions, builder, deck side, window layout
    and design language throughout.
  - Actual previous pixels are authoritative: every still is an edit of an
    earlier approved still, never a fresh re-imagining.

Production shape (stills first, then animation - per the storyboard deck):
  Phase A  20 checkpoint stills + camera "bridge" stills, each a Nano Banana
           Pro edit of an earlier approved still. Reviewed one by one.
  Phase B  20 video clips. Clip k animates ONLY the single task that turns
           the state before checkpoint k into checkpoint k, from ONE locked
           camera, pinned at both ends (start still -> checkpoint k still)
           with Wan 3.0 first/last-frame conditioning (end_image_url).
  A camera change never happens inside a construction clip: when checkpoint
  k is filmed from a different setup than k-1, a bridge still shows the SAME
  construction state from the new camera, and the edit cuts there.

Usage (from the repo root - no FAL_API_KEY needed):
    python -m scripts.run_train_car_video_2_plan            # print checkpoints, clip map, cost
    python -m scripts.run_train_car_video_2_plan --write    # also write data/train_car_video_2/
"""
import argparse
import json
import sys
import zipfile
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from xml.etree import ElementTree as ET

REPO_ROOT = Path(__file__).resolve().parent.parent
SLUG = "train_car_video_2"
PROJECT_NAME = "FORMA Video #2 - Abandoned Train Car to Luxury Forest Cabin"
OUTPUT_DIR = REPO_ROOT / "data" / SLUG
STORYBOARD_DECK = REPO_ROOT / "docs" / "forma" / "creative" / "FORMA_20_Checkpoint_Train_Car_Storyboard_Updated.pptx"

ASPECT_RATIO = "9:16"
RESOLUTION = "480p"          # decided 2026-09-24: this experiment tests logic/continuity, not resolution
BUDGET_CAP_USD = 15.00       # decided 2026-09-24: ~$9.75 baseline + ~$5.25 for selective retries

# Incremental generation: the first paid proof ends at clip03 (CP02 -> CP03 with first/last-frame
# conditioning). Nothing ordered after it may run until the proof is explicitly marked passed.
PROOF_STAGE = "clip03"

# Storyboard slide per checkpoint (slides 7-26 are CP01-CP20 in the deck). CP12-CP14 are remapped
# because the build order was corrected: glass (deck slide 20) -> cladding begins (slide 18) ->
# cladding near complete (slide 19).
STORYBOARD_SLIDE = {n: 6 + n for n in range(1, 21)} | {12: 20, 13: 18, 14: 19}
FINAL_SECONDS_PER_CHECKPOINT = 3.0

# Unit prices already used by this repo (app/providers/*/fal.py). The Wan 3.0
# first/last-frame price is ASSUMED equal to its image-to-video price - fal's
# API docs confirm end_image_url exists but this repo has never run it.
PRICE_IMAGE_GENERATE_USD = 0.15   # NANO_BANANA_PRO (site/establishing still)
PRICE_IMAGE_EDIT_USD = 0.15       # NANO_BANANA_PRO_EDIT, flat per image
PRICE_VIDEO_PER_SECOND_USD = {"480p": 0.05, "720p": 0.10}  # WAN_3_0_STANDARD

# --- continuity anchors (locked for every still and clip) ----------------------------------

LOCATION_BIBLE = (
    "a misty pine-forest valley with tall dark evergreens close around the site, snow-capped "
    "mountains rising behind the tree line, a short weed-covered stretch of old single railway "
    "track, and soft overcast daylight with light mist"
)
RAILCAR_SPEC = (
    "one vintage steel passenger railcar, about 60 feet long and 10 feet wide, with a gently "
    "arched roof, riveted steel skin rusted red-brown, a row of small original rectangular "
    "windows along its long side, and a recessed end door, sitting on its original wheel trucks "
    "on the track - the same car, same proportions and same position in every shot"
)
BUILDER_SPEC = (
    "one builder: a bearded man in a black beanie, dark charcoal hoodie, tan canvas work pants, "
    "leather tool belt and work gloves - always the same person, working, never posing"
)
FACADE_LAYOUT = (
    "the facade is the long side facing the camera; it will receive two large panoramic window "
    "openings in the middle section and one door opening near the left end, and the deck runs "
    "along this same side"
)
DESIGN_LANGUAGE = (
    "finished design: matte-black painted steel ends and roof, warm natural vertical wood "
    "cladding across the facade, black-framed panoramic glass, a natural-wood deck with black "
    "metal railing along the facade, a small flat awning over the entry, warm wall sconces"
)
CONTINUITY_ANCHORS = {
    "location": LOCATION_BIBLE,
    "railcar": RAILCAR_SPEC,
    "builder": BUILDER_SPEC,
    "facade_and_deck_side": FACADE_LAYOUT,
    "design_language": DESIGN_LANGUAGE,
}


@dataclass(frozen=True)
class Camera:
    id: str
    description: str


CAMERAS = {
    "WIDE": Camera("WIDE", "high wide establishing view from about 40 m, three-quarter from the facade side; "
                           "the railcar sits small in the valley with mountains behind"),
    "FACADE": Camera("FACADE", "exterior three-quarter view of the facade from about 7 m at chest height, left "
                               "end of the car nearest camera, the whole facade span and the ground in front "
                               "of it in frame; held completely still"),
    "INTERIOR": Camera("INTERIOR", "interior view from just inside the end door at eye height, looking down "
                                   "the car's length with the facade-side wall on the right; held completely still"),
}


@dataclass(frozen=True)
class Checkpoint:
    number: int
    title: str
    start_s: float
    end_s: float
    progress: int                      # target progress %, from the deck
    camera: str                        # locked camera setup id (see CAMERAS)
    storyboard_camera: str             # the deck's own framing note
    state: str                         # visual construction state AT this checkpoint
    action: str                        # what the builder visibly does in the clip that ends here
    tools: tuple[str, ...]
    adds: tuple[str, ...]              # items this checkpoint introduces (drives exists / not-yet)
    not_yet: str                       # the deck's own guardrail
    raw_seconds: int                   # raw clip length to generate (accelerated to 3 s later)
    extra_anchors: tuple[str, ...] = ()
    issues: tuple[str, ...] = ()       # storyboard problems found during planning, to decide on

    @property
    def key(self) -> str:
        return f"cp{self.number:02d}"

    @property
    def time_range(self) -> str:
        fmt = lambda s: f"{int(s // 60)}:{int(s % 60):02d}"  # noqa: E731
        return f"{fmt(self.start_s)}-{fmt(self.end_s)}"


C = Checkpoint
CHECKPOINTS: list[Checkpoint] = [
    C(1, "Abandoned railcar discovery", 0, 3, 0, "WIDE", "wide establish (drone/wide)",
      "the untouched rusted railcar in the misty valley; the builder, small in frame, walks toward it carrying a backpack",
      "builder walks in from frame edge toward the railcar", ("backpack", "flashlight", "gloves", "pry bar"),
      (),
      "No cleanup, no cuts, no deck, no windows, no interior finish.", 5),
    C(2, "Inspection + plan", 3, 6, 5, "FACADE", "three-quarter exterior at cargo side",
      "builder at the facade with the end door slid open, measuring the facade with a tape and sketching on a board",
      "builder slides the end door open, looks in, then measures the facade and sketches", ("tape measure", "sketch board", "marker"),
      ("end door open",),
      "No construction changes yet beyond opening/inspection.", 5,
      extra_anchors=("the viewer must understand this facade becomes the deck/window side",)),
    C(3, "Exterior clearing begins", 6, 9, 10, "FACADE", "side exterior",
      "weeds, brush and debris cleared from ~80% of the strip in front of the facade; a debris pile beside a wheelbarrow at the left",
      "builder shovels brush and debris into a wheelbarrow and dumps it on a growing pile, working left to right",
      ("shovel", "wheelbarrow", "gloves"), ("cleared ground strip along facade", "debris pile at left end"),
      "No new deck components yet.", 6),
    C(4, "Interior cleanout", 9, 12, 15, "INTERIOR", "interior doorway view",
      "interior stripped of old seats, insulation scraps and trash across ~80% of the length, floor swept bare near the camera",
      "builder pries out seats and carries junk to a bin, clearing from the doorway backward", ("pry bar", "bins", "broom", "respirator"),
      ("interior stripped bare", "junk bins outside the end door"),
      "No framing, insulation, glass, or furniture yet.", 6),
    C(5, "Mark openings", 12, 15, 20, "FACADE", "long-side exterior",
      "white chalk lines on the facade outlining two large window openings and one door opening",
      "builder snaps chalk lines and squares corners, marking each opening in turn", ("chalk line", "tape measure", "square"),
      ("chalk outlines of 2 windows + 1 door on facade",),
      "No finished holes yet, no glass yet.", 5),
    C(6, "Cut large openings", 15, 18, 25, "FACADE", "side exterior close/medium",
      "window opening 1 fully cut through, window opening 2 about 80% cut with the grinder still in it; raw metal edges; cut panels on the ground",
      "builder cuts along the chalk lines with an angle grinder, sparks flying, and lifts out the first panel",
      ("angle grinder", "clamps", "face shield"), ("window opening 1 cut", "window opening 2 mostly cut", "cut steel panels on ground"),
      "No windows installed yet; raw metal edges remain.", 6,
      issues=("The door opening and the last ~20% of window 2 are finished off-camera before CP08 (a repetitive tail, "
              "within the 70-90% rule). Confirm, or add a checkpoint for them.",)),
    C(7, "Interior rough framing", 18, 21, 30, "INTERIOR", "interior lengthwise",
      "wood studs/furring framed around the new openings and along ~80% of both walls",
      "builder measures, cuts and screws studs into place around the openings, moving down the car",
      ("drill", "nailer", "studs", "level"), ("interior stud framing",),
      "No insulation finish, no paneling, no decor.", 6),
    C(8, "Structural reinforcement", 21, 24, 35, "FACADE", "exterior close",
      "welded steel reinforcing frames around every opening, fresh weld seams visible",
      "builder clamps and welds a steel frame around each opening in turn", ("welder", "clamps", "grinder"),
      ("steel reinforcing frames around openings",),
      "Still no glazing or complete exterior cladding.", 5,
      issues=("Storyboard frames this as a close-up; decided 2026-09-24: keep the locked FACADE setup (no "
              "close-up camera families yet).",)),
    C(9, "Deck supports + materials", 24, 27, 40, "FACADE", "ground-level deck side",
      "a row of concrete support pads set level in front of the facade; a stack of deck lumber delivered at the left",
      "builder carries and levels the concrete pads one by one, then stacks the delivered lumber", ("concrete pads", "lumber", "level"),
      ("concrete support pads", "lumber stack"),
      "No floating deck boards; no finished deck.", 6),
    C(10, "Deck beams + joists", 27, 30, 45, "FACADE", "deck-side three-quarter",
      "beams laid on the pads and joists across ~80% of the deck span, clear frontier to the unjoisted end",
      "builder lays beams on the pads, then cuts and fastens joists one after another along the span",
      ("impact driver", "circular saw", "joist hangers"), ("deck beams", "deck joists"),
      "Deck boards not mostly complete yet.", 6),
    C(11, "Deck boards mostly laid", 30, 33, 50, "FACADE", "deck-side angle",
      "deck boards screwed down across ~80% of the deck, last section of bare joists at the right end",
      "builder lays and screws down boards one by one, sweeping across the deck", ("impact driver", "screws", "circular saw"),
      ("deck boards",),
      "Do not jump after one board; railings not final yet.", 6),
    C(12, "Install panoramic glass", 33, 36, 55, "FACADE", "exterior close/medium",
      "panoramic glass set in window opening 1, the second pane being set with suction cups (~80% glazed), glass entry "
      "door fitted in the door opening; the facade steel itself is still bare, uncladded, rust-brown",
      "builder carries a large pane from a padded crate with suction cups, sets it in the reinforced opening, shims and "
      "secures it, then lifts the next", ("glass suction cups", "glass crate", "caulk gun", "shims", "drill"),
      ("panoramic glass", "glass entry door"),
      "Never one pane -> instantly all glass without progress. No cladding, wrap or paint yet.", 6,
      issues=("REORDERED: glass now comes before cladding (was CP14). The storyboard art for this step shows two "
              "workers; production keeps the single builder.",)),
    C(13, "Cladding/weatherproofing begins", 36, 39, 60, "FACADE", "exterior side",
      "weather wrap and trim around the installed glass on the lower facade, and the first vertical wood cladding "
      "boards covering ~25% of the facade",
      "builder staples weather wrap around the glazed openings, then nails up the first cladding boards from a staged "
      "stack", ("nail gun", "weather wrap", "trim boards"), ("weather wrap and trim", "first wood cladding boards"),
      "Not fully luxury exterior yet; no paint, no porch cover.", 6,
      issues=("REORDERED: was CP12. Glass stays installed throughout; if the storyboard art is ambiguous about the "
              "glazing, the text governs.",)),
    C(14, "Exterior cladding near complete + finish", 39, 42, 65, "FACADE", "exterior facade",
      "wood cladding across ~80% of the facade around the glass; steel ends and roof being sprayed matte black",
      "builder continues cladding board by board, then spray-paints the rusted steel ends black",
      ("paint sprayer", "drill", "trim", "fasteners"), ("wood cladding ~80%", "black paint on steel ends"),
      "No final reveal yet; no fully styled interior; no porch cover yet.", 6,
      issues=("REORDERED: was CP13 (its storyboard art already shows glass + cladding, now consistent).",)),
    C(15, "Porch cover / entry finish", 42, 45, 70, "FACADE", "deck angle",
      "small flat awning over the entry, entry steps, black metal railing along ~80% of the deck, wall sconces mounted",
      "builder on a ladder fixes the awning, then installs the steps and railing sections", ("ladder", "nailer", "impact driver", "level"),
      ("entry awning", "entry steps", "deck railing", "wall sconces"),
      "Interior still not finished.", 6),
    C(16, "Interior insulation", 45, 48, 75, "INTERIOR", "interior lengthwise",
      "insulation batts fitted between the studs along ~80% of the car; glass now in the openings",
      "builder cuts and presses insulation batts into the framing, bay by bay down the car",
      ("driver", "insulation knife", "gloves"), ("insulation",),
      "No bed, rug, or finished decor yet.", 6),
    C(17, "Kitchenette + wall panels", 48, 51, 80, "INTERIOR", "interior",
      "wood wall panels over ~80% of the insulation; kitchenette counter and open shelving installed at the far end",
      "builder fixes wall panels, then sets the counter and screws up the shelving", ("saw", "toolbox", "brad nailer", "driver"),
      ("wood wall panels", "kitchenette counter", "open shelving"),
      "Not fully styled; no instant hotel room.", 6),
    C(18, "Interior styling nearly complete", 51, 54, 85, "INTERIOR", "interior warm view",
      "bed/bench with textiles, rug, pendant lights and plants placed; warm light on",
      "builder carries in and places the mattress, rug, lamps and plants one by one", ("finishing tools", "lighting", "textiles", "decor"),
      ("bed and textiles", "rug", "lighting", "decor"),
      "Do not teleport fully complete interior from empty shell.", 6),
    C(19, "Exterior landscaping + evening light", 54, 57, 90, "FACADE", "exterior dusk setup",
      "planters and gravel landscaping along the deck; dusk light, sconces and interior glowing warm",
      "builder rakes gravel and sets planters as the light fades, then switches the lights on", ("rake", "light fixtures", "planters"),
      ("landscaping", "evening lighting"),
      "Not the final hero pullback yet.", 5),
    C(20, "Final reveal", 57, 60, 100, "WIDE", "wide cinematic dusk reveal",
      "the finished luxury railcar cabin glowing at dusk in the valley - no new design elements",
      "no building: a slow camera pull-back to the wide reveal", (),
      (),
      "Do not introduce new design elements in the final reveal.", 5),
]


def must_exist(cp: Checkpoint) -> list[str]:
    """Everything introduced by earlier checkpoints (derived, not in the deck)."""
    return [item for earlier in CHECKPOINTS if earlier.number < cp.number for item in earlier.adds]


def must_not_exist(cp: Checkpoint) -> list[str]:
    """The deck's own guardrail plus everything a later checkpoint introduces (derived)."""
    return [cp.not_yet] + [item for later in CHECKPOINTS if later.number > cp.number for item in later.adds]


# --- stage plan ----------------------------------------------------------------------------

@dataclass
class Stage:
    key: str
    kind: str                     # image_generate | image_edit | video
    phase: str                    # A (stills) | B (clips)
    checkpoint: int
    camera: str
    label: str
    source: str | None = None     # still this one is edited from / clip start frame
    end_frame: str | None = None  # clip end frame (first/last-frame conditioning)
    purpose: str = ""
    raw_seconds: float | None = None
    accel_factor: float | None = None
    estimated_cost_usd: float = 0.0
    construction_delta: bool = True  # False for bridges and the reveal: no new construction


def build_stage_plan(resolution: str = RESOLUTION) -> list[Stage]:
    """Stills first (Phase A), then one clip per checkpoint (Phase B)."""
    stills: list[Stage] = []
    clips: list[Stage] = []
    last_still_by_camera: dict[str, str] = {}
    video_rate = PRICE_VIDEO_PER_SECOND_USD[resolution]

    first = CHECKPOINTS[0]
    stills.append(Stage(f"{first.key}_still", "image_generate", "A", 1, first.camera, f"CP01 still - {first.title}",
                        purpose="establishing still generated from the location + railcar anchors",
                        estimated_cost_usd=PRICE_IMAGE_GENERATE_USD))
    last_still_by_camera[first.camera] = f"{first.key}_still"
    clips.append(Stage("clip01", "video", "B", 1, first.camera, f"Clip 01 - {first.title}",
                       source=f"{first.key}_still", purpose=first.action, raw_seconds=first.raw_seconds,
                       accel_factor=round(first.raw_seconds / FINAL_SECONDS_PER_CHECKPOINT, 3),
                       estimated_cost_usd=round(first.raw_seconds * video_rate, 4)))

    for prev, cp in zip(CHECKPOINTS, CHECKPOINTS[1:]):
        prev_still = f"{prev.key}_still"
        start = prev_still
        is_reveal = not cp.adds  # the final reveal: camera move only, no construction
        if cp.camera != prev.camera and not is_reveal:
            bridge = f"{cp.key}_bridge"
            sync_from = last_still_by_camera.get(cp.camera)
            if sync_from:
                purpose = (f"state of {prev.key.upper()} seen from the {cp.camera} setup: {sync_from} updated with the "
                           "changes made since, on-screen elsewhere - no new construction")
            else:
                sync_from = prev_still
                purpose = f"camera change to the {cp.camera} setup showing {prev.key.upper()}'s state unchanged"
            stills.append(Stage(bridge, "image_edit", "A", cp.number, cp.camera, f"CP{cp.number:02d} bridge still",
                                source=sync_from, purpose=purpose, estimated_cost_usd=PRICE_IMAGE_EDIT_USD,
                                construction_delta=False))
            start = bridge
        stills.append(Stage(f"{cp.key}_still", "image_edit", "A", cp.number, cp.camera,
                            f"CP{cp.number:02d} still - {cp.title}", source=start,
                            purpose=("camera pull-back to the wide reveal, construction unchanged" if is_reveal
                                     else f"advance ONLY: {cp.title.lower()} ({cp.progress}%)"),
                            estimated_cost_usd=PRICE_IMAGE_EDIT_USD, construction_delta=not is_reveal))
        last_still_by_camera[cp.camera] = f"{cp.key}_still"
        clips.append(Stage(f"clip{cp.number:02d}", "video", "B", cp.number, cp.camera,
                           f"Clip {cp.number:02d} - {cp.title}", source=start, end_frame=f"{cp.key}_still",
                           purpose=cp.action, raw_seconds=cp.raw_seconds,
                           accel_factor=round(cp.raw_seconds / FINAL_SECONDS_PER_CHECKPOINT, 3),
                           estimated_cost_usd=round(cp.raw_seconds * video_rate, 4),
                           construction_delta=not is_reveal))
    return stills + clips


def execution_order(stages: list[Stage]) -> list[str]:
    """The order stages actually run in, one at a time behind approvals.

    First paid proof: CP01 still, the CP02 camera bridge, CP02, CP03, then clip03 (CP02 -> CP03,
    the first real construction transition) - and STOP. The two non-construction clips (01
    establishing, 02 inspection) are back-filled right after the proof passes, then every later
    checkpoint runs as [bridge] -> still -> clip: GENERATE STILL -> REVIEW -> APPROVE -> GENERATE
    CLIP -> REVIEW -> APPROVE -> NEXT CHECKPOINT."""
    keys = {s.key for s in stages}
    order = ["cp01_still", "cp02_bridge", "cp02_still", "cp03_still", "clip03", "clip01", "clip02"]
    for cp in CHECKPOINTS[3:]:
        order += [k for k in (f"{cp.key}_bridge", f"{cp.key}_still", f"clip{cp.number:02d}") if k in keys]
    assert sorted(order) == sorted(keys), "execution order must cover every stage exactly once"
    return order


def _join(items) -> str:
    return "; ".join(items) if items else "nothing yet"


CLIP_REVIEW_CHECKLIST = [
    "same railcar geometry, proportions and window layout as the start and end stills",
    "same location, same builder, same lighting",
    "same camera - no movement, zoom or angle change",
    "exactly one construction task, no other changes",
    "visible causal labor: every bit of progress is caused by the builder's hands/tools",
    "construction frontier (completed | active | untouched) moves steadily in one direction",
    "70-90% of the task is visibly performed on-screen",
    "no magical spawning of materials or structure",
    "the clip naturally approaches the approved end still (end-frame pinning held)",
]
STILL_REVIEW_CHECKLIST = [
    "exactly the checkpoint state described - no more, no less",
    "nothing already built has disappeared, moved or regressed",
    "nothing from a later checkpoint is present",
    "same railcar, location, builder and camera as the still it was edited from",
    "builder caught mid-task with a readable construction frontier; new materials have a visible source",
]


def still_prompt(stage: Stage) -> str:
    from app.forma.doctrine import STILL_DOCTRINE

    cp = CHECKPOINTS[stage.checkpoint - 1]
    cam = CAMERAS[stage.camera].description
    anchors = f"The railcar: {RAILCAR_SPEC}. The builder: {BUILDER_SPEC}. {FACADE_LAYOUT}."
    if stage.kind == "image_generate":
        return (
            f"Vertical 9:16 realistic documentary photograph, not illustration. Camera: {cam}. Location: "
            f"{LOCATION_BIBLE}. In the valley sits {RAILCAR_SPEC}; it is abandoned and completely untouched - "
            f"no cleanup, cuts, deck, glass or finish of any kind. {cp.state}. The builder: {BUILDER_SPEC}. "
            f"Candid, unposed. {STILL_DOCTRINE}"
        )
    if stage.key.endswith("_bridge"):
        prev = CHECKPOINTS[stage.checkpoint - 2]
        return (
            f"Same build, same moment: keep the railcar, location, lighting, builder and every construction detail "
            f"exactly as they are in reality at this point (the state after '{prev.title}'). Change ONLY the camera "
            f"to: {cam}. Everything completed so far must be visible where this camera can see it: "
            f"{_join(must_exist(prev) + list(prev.adds))}. Do not add, remove or advance any construction. "
            f"Must NOT appear: {_join(must_not_exist(prev)[1:])}. {anchors} {STILL_DOCTRINE}"
        )
    if not cp.adds:  # the reveal
        return (
            f"Same finished cabin, same dusk light, nothing added or changed. Change ONLY the camera: pull back to "
            f"{cam}, the finished railcar cabin glowing in the valley. No new design elements. {anchors} {STILL_DOCTRINE}"
        )
    return (
        f"The next checkpoint of the same continuous build, from the exact same camera ({cam}). The input image's "
        f"pixels are authoritative: keep the railcar, location, lighting, builder and everything already built "
        f"exactly as they are. ADVANCE ONLY ONE TASK - {cp.title}: {cp.state}. The builder is caught mid-task: "
        f"{cp.action}, using {', '.join(cp.tools)}. Already built and must stay unchanged: {_join(must_exist(cp))}. "
        f"Must NOT appear yet: {_join(must_not_exist(cp))}. {anchors} {STILL_DOCTRINE}"
    )


def clip_prompt(stage: Stage) -> str:
    from app.forma.doctrine import VIDEO_DOCTRINE

    cp = CHECKPOINTS[stage.checkpoint - 1]
    cam = CAMERAS[stage.camera].description
    same = (f"Keep the same railcar ({RAILCAR_SPEC}), the same location ({LOCATION_BIBLE}) and the same builder "
            f"({BUILDER_SPEC}).")
    if stage.end_frame is None:  # clip01: establishing, start frame only
        return (
            f"Vertical 9:16, realistic documentary footage. Camera: {cam} - locked, no movement. The abandoned "
            f"railcar sits untouched in the misty valley while the builder walks steadily toward it from the edge "
            f"of frame. No construction of any kind. {same} {VIDEO_DOCTRINE}"
        )
    if not stage.construction_delta:  # clip20: the reveal
        return (
            f"Vertical 9:16, cinematic documentary footage. The clip starts exactly on the first image and ends "
            f"exactly on the last image. A slow, steady camera pull-back from the finished glowing railcar cabin to "
            f"{cam}. No construction, nothing added or changed - only the camera moves. {same} {VIDEO_DOCTRINE}"
        )
    return (
        f"Vertical 9:16, realistic documentary construction footage. Camera: {cam} - locked, no movement, no zoom, "
        f"no angle change. The clip starts exactly on the first image and must end exactly on the last image. "
        f"Everything in between is the builder performing ONE task - {cp.title}: {cp.action}. Show 70 to 90 "
        f"percent of this task being done on-screen, continuously, the construction frontier advancing steadily "
        f"until the scene matches the last image: {cp.state}. Tools: {', '.join(cp.tools)}. Nothing else changes. "
        f"{same} {VIDEO_DOCTRINE}"
    )


def stage_prompt(stage: Stage) -> str:
    return clip_prompt(stage) if stage.kind == "video" else still_prompt(stage)


def cost_summary(stages: list[Stage]) -> dict:
    stills = [s for s in stages if s.phase == "A"]
    clips = [s for s in stages if s.phase == "B"]
    return {
        "stills": len(stills),
        "bridges": sum(s.key.endswith("_bridge") for s in stills),
        "clips": len(clips),
        "raw_video_seconds": sum(s.raw_seconds or 0 for s in clips),
        "final_seconds": len(clips) * FINAL_SECONDS_PER_CHECKPOINT,
        "phase_a_usd": round(sum(s.estimated_cost_usd for s in stills), 2),
        "phase_b_usd": round(sum(s.estimated_cost_usd for s in clips), 2),
        "total_usd": round(sum(s.estimated_cost_usd for s in stages), 2),
    }


# --- storyboard references -----------------------------------------------------------------

_NS = {
    "p": "http://schemas.openxmlformats.org/presentationml/2006/main",
    "r": "http://schemas.openxmlformats.org/officeDocument/2006/relationships",
    "rel": "http://schemas.openxmlformats.org/package/2006/relationships",
}


def extract_storyboard_images(deck: Path, dest: Path) -> dict[str, str]:
    """Copy the deck's checkpoint images (slides 7-26 = CP01-CP20) and the 20-panel overview
    (slide 4) out of the .pptx. Read-only on the deck. Returns {name: path}."""
    written: dict[str, str] = {}
    with zipfile.ZipFile(deck) as z:
        pres = ET.fromstring(z.read("ppt/presentation.xml"))
        rels = {r.get("Id"): r.get("Target") for r in
                ET.fromstring(z.read("ppt/_rels/presentation.xml.rels")).findall("rel:Relationship", _NS)}
        slides = [rels[s.get(f"{{{_NS['r']}}}id")] for s in pres.find("p:sldIdLst", _NS)]

        def slide_images(index: int) -> list[str]:
            rel_path = "ppt/" + slides[index - 1].replace("slides/", "slides/_rels/") + ".rels"
            return ["ppt/media/" + r.get("Target").split("/")[-1]
                    for r in ET.fromstring(z.read(rel_path)).findall("rel:Relationship", _NS)
                    if "media/" in r.get("Target")]

        dest.mkdir(parents=True, exist_ok=True)
        (dest / "original").mkdir(exist_ok=True)
        targets = {"overview": slide_images(4)} | {f"cp{n:02d}": slide_images(STORYBOARD_SLIDE[n]) for n in range(1, 21)}
        for name, images in targets.items():
            if not images:
                continue
            original = dest / "original" / f"{name}{Path(images[0]).suffix}"
            original.write_bytes(z.read(images[0]))
            out = dest / f"{name}{Path(images[0]).suffix}"
            if name == "overview" or not _relabel(original, out, CHECKPOINTS[int(name[2:]) - 1]):
                out.write_bytes(original.read_bytes())
            written[name] = str(out)
    return written


def _relabel(src: Path, dst: Path, cp: Checkpoint) -> bool:
    """Crop off the deck's burned-in caption (which carries the OLD numbering for CP12-14) and stamp
    the corrected checkpoint number/progress, so image and plan text agree. Local ffmpeg; returns
    False (caller keeps the original) if ffmpeg or a font isn't available."""
    import shutil
    import subprocess

    ffmpeg = shutil.which("ffmpeg")
    font = next((f for f in (Path("C:/Windows/Fonts/arialbd.ttf"), Path("C:/Windows/Fonts/arial.ttf"),
                             Path("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf")) if f.exists()), None)
    if not ffmpeg or font is None:
        return False
    fontfile = str(font).replace("\\", "/").replace(":", "\\:")
    label = f"CP{cp.number:02d}  {cp.progress}%"
    # Even output dimensions (JPEG's 4:2:0 needs them) and expansion=none so "%" is literal.
    vf = (f"crop=trunc(iw/2)*2:trunc((ih-64)/2)*2:0:0,drawbox=x=0:y=0:w=124:h=34:color=black@0.85:t=fill,"
          f"drawtext=fontfile='{fontfile}':expansion=none:text='{label}':x=8:y=9:fontsize=17:fontcolor=white")
    result = subprocess.run([ffmpeg, "-y", "-loglevel", "error", "-i", str(src), "-vf", vf, "-q:v", "2", str(dst)],
                            capture_output=True, text=True)
    return result.returncode == 0 and dst.exists()


# --- output --------------------------------------------------------------------------------

def plan_document(stages: list[Stage], storyboard: dict[str, str]) -> dict:
    checkpoints = []
    for cp in CHECKPOINTS:
        d = asdict(cp)
        d.update(key=cp.key, time_range=cp.time_range, camera_setup=CAMERAS[cp.camera].description,
                 must_already_exist=must_exist(cp), must_not_exist_yet=must_not_exist(cp),
                 continuity_anchors=list(CONTINUITY_ANCHORS.values()) + list(cp.extra_anchors),
                 storyboard_reference=storyboard.get(cp.key))
        checkpoints.append(d)
    return {
        "project": SLUG, "name": PROJECT_NAME, "source_deck": str(STORYBOARD_DECK.relative_to(REPO_ROOT)),
        "aspect_ratio": ASPECT_RATIO, "resolution": RESOLUTION,
        "continuity_anchors": CONTINUITY_ANCHORS,
        "cameras": {k: v.description for k, v in CAMERAS.items()},
        "checkpoints": checkpoints,
        "budget_cap_usd": BUDGET_CAP_USD,
        "proof_stage": PROOF_STAGE,
        "execution_order": execution_order(stages),
        "stages": [asdict(s) | {"prompt": stage_prompt(s)} for s in stages],
        "cost_estimate": cost_summary(stages),
        "storyboard_overview": storyboard.get("overview"),
    }


def write_project(stages: list[Stage]) -> None:
    storyboard = extract_storyboard_images(STORYBOARD_DECK, OUTPUT_DIR / "storyboard") if STORYBOARD_DECK.exists() else {}
    (OUTPUT_DIR / "plan.json").write_text(json.dumps(plan_document(stages, storyboard), indent=2))
    manifest_path = OUTPUT_DIR / "manifest.json"
    if not manifest_path.exists():
        manifest = {"experiment": SLUG, "created_at": datetime.now(timezone.utc).isoformat(), "plan": "plan.json"}
    else:
        manifest = json.loads(manifest_path.read_text())
    if manifest.get("budget_cap_usd") is None:  # set once; never overwrite a cap or any stage entry
        manifest["budget_cap_usd"] = BUDGET_CAP_USD
        manifest_path.write_text(json.dumps(manifest, indent=2))
    print(f"\nWrote {OUTPUT_DIR / 'plan.json'} and {len(storyboard)} storyboard references; manifest at {manifest_path}")


def print_plan(stages: list[Stage]) -> None:
    print("=" * 100)
    print(f"{PROJECT_NAME} - 20-checkpoint plan (local, no API calls)")
    print("=" * 100)
    for cp in CHECKPOINTS:
        print(f"CP{cp.number:02d} {cp.time_range:>9} {cp.progress:>3}%  [{cp.camera:<8}] {cp.title}")
    print("\nCheckpoint -> clip map")
    print("-" * 100)
    stills = {s.key: s for s in stages if s.phase == "A"}
    for clip in (s for s in stages if s.phase == "B"):
        span = f"{clip.source} -> {clip.end_frame}" if clip.end_frame else f"{clip.source} (start frame only)"
        bridge = stills.get(f"cp{clip.checkpoint:02d}_bridge")
        print(f"{clip.key}  {clip.raw_seconds:>2.0f}s raw -> 3s ({clip.accel_factor}x)  ${clip.estimated_cost_usd:.2f}  "
              f"[{clip.camera}]  {span}{'  (after bridge still)' if bridge else ''}")
    c = cost_summary(stages)
    print("-" * 100)
    print(f"Phase A: {c['stills']} stills ({c['bridges']} camera bridges) = ${c['phase_a_usd']:.2f}")
    print(f"Phase B: {c['clips']} clips, {c['raw_video_seconds']:.0f}s raw -> {c['final_seconds']:.0f}s final = ${c['phase_b_usd']:.2f}")
    print(f"Total estimate: ${c['total_usd']:.2f}  (excludes retries)")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--write", action="store_true", help=f"Write plan.json + storyboard refs into {OUTPUT_DIR}")
    args = parser.parse_args()
    stages = build_stage_plan()
    print_plan(stages)
    if args.write:
        write_project(stages)


if __name__ == "__main__":
    sys.exit(main())
