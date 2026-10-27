# Project #3 R&D: the 3 m pipe still chain (2026-10-26, superseded 2026-10-27)

This folder keeps the first Project #3 still chain. Its pipe had a 3 m inside diameter and was 12 m long. The user
restarted the visual chain on 2026-10-27 with a larger pipe (about 4 m inside diameter, about 13 m long) and a
10-stage plan.

**History only.** Nothing here may be used as a source image. Every new still descends from the new CP01 in
`data/forma_project_3/stills/`.

## Contents
- `project.json`: the 3 m plan at the restart. It had 20 checkpoints and 19 shots, with s02 as three clips and the
  proof and model-override settings.
- `manifest.json`: the full state at the restart.
  - All 13 fal still generations, each with its prompt, source hash, cost and review.
  - The approvals, including the user's re-approvals of 2026-10-27. Those were made while a relative-vs-absolute
    path bug showed approved stills as "changed".
  - The CP02 normalization record and the archive records.
- `stills/`: the last approved or placed file per key. `cp01`, `s01_mid1` and `cp02` were approved; `s02_mid1`
  (Nano Banana 2, attempt 4) was approved on 2026-10-27.
- `stills/_replaced/`: every rejected or superseded attempt.
- `stills/_generated/`: raw fal outputs. They are local only and gitignored; byte-identical copies are in
  `stills/` and `stills/_replaced/`.

## Spend
$0.6388 on fal still generations, with no video. That amount is carried into the live manifest as `rnd_spend`, so
the project's spend total stays honest.

## What was learned
- The CP01 brief needs explicit geometry: one standalone section, both ends, the camera height and the side.
  Otherwise the model draws a pipeline running into the forest.
- `fal-ai/nano-banana/edit` ($0.0398) holds camera and scene continuity very well and handles additive or local
  edits. It failed large-area removals twice and dropped approved objects (a sawn stack went from 3 logs to 1).
- `fal-ai/nano-banana-2/edit` ($0.08) did the CP02 large-area clearing in one call, at the cost of a slightly
  different output size. Normalize it by scaling, not cropping.
- Neither tier reliably moves an object. A wheelbarrow "moved" to the opening was duplicated instead. A small dark
  area deep inside the pipe was over-removed once and reshaped into a stripe another time. Plans that work:
  objects stay where they are, a small area keeps its shape, and progress shows in large readable things (the
  barrow load, a spoil pile).
- End states must be explicit final visual conditions. A removal must say what is gone and where it went (still
  doctrine rules 1-2).
