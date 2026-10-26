# FORMA production template (Project #3 on)

Project #3 is the first project built on one generic engine instead of per-project scripts.
Projects #1 (Cliffside) and #2 (Alpine; the train car as R&D) stay in the studio as history; the train
car is **frozen** - viewable, recoverable, never launched or submitted again.

Doctrine: `docs/forma/creative/FORMA_CREATIVE_BRAIN.md` (rules 1-11 + production lessons 1-11).

## 1. Project folder

```
data/forma_project_3/
  project.json      THE PLAN - concept, bibles, cameras, checkpoints, shots, still models (edited by a person)
  manifest.json     STATE - approvals, generations, uploads, spend approvals, provider jobs (written by the engine)
  stills/           <key>.jpg|png|webp - exactly one file per still (generated or uploaded in the studio)
  stills/_generated/ the raw output of every still generation (<key>__genN.png)
  stills/_replaced/ every file a generation or upload replaced (never deleted)
  clips/            <clip>__attemptN_fal_<model>_raw.mp4 - one file per provider job
  edit/             hard-cut assembly (later)
docs/forma/production/example_project.json   format reference (not a concept)
app/forma/production/                         the engine (spec, rules, state, stills, still_gen, budget, submit)
```

`project.json` ships as an empty template: `status: "template"`, `concept: null`, **`budget.cap_usd: 0`** -
nothing can be spent until a person sets a cap.

## 2. Studio workflow

1. **Plan** - write checkpoints and shots in `project.json`. The studio re-reads it on every import and
   shows doctrine errors; errors block every clip.
2. **Stills (Continuity Office / Production flow)** - the default (`"stills": {"source": "manual"}`, from
   2026-10-26) is ChatGPT: open the next still (status **Waiting for ChatGPT image**), click **Copy ChatGPT Brief**,
   paste it into ChatGPT and attach the previous approved still shown on the panel (CP01 is text only), then drop
   the image on the panel. It is saved as `<key>.<ext>`, placed, never auto-approved. Write what you checked and
   **Approve still** - the studio opens the next still that needs an image. Generation is an optional paid
   fallback on each panel ("Optional fallback: generate this still with fal"); `generation_fallback: false` turns
   it off. With `"source": "generate"` the roles swap, as follows. Open the next still, check the spend amount,
   tick the confirmation and click **Generate still**: ONE fal call. CP01 is text-to-image from its brief; every later
   still is an **image edit of the previous approved still** (its exact file and hash), so the previous pixels
   are authoritative - camera, structure, environment, builder, lighting and geometry carry over and only that
   step's progress changes. This covers intermediates, static time jumps and camera changes. The result is
   saved as `<key>.png` and is **placed**, never auto-approved. Look at it, write what you checked, then
   **Approve & Continue** (opens the next still or ready clip - it generates nothing) or **Approve only**.
   Not right? **Regenerate still** (a new confirmed call; the old file goes to `stills/_replaced/`).
   **Optional override:** upload your own image (e.g. from ChatGPT, using the prompt as the brief) for any
   still; it is placed and approved the same way. `"stills": {"source": "manual"}` makes a project upload-only.
3. **Clips (Render Bay / Production flow)** - a clip whose two anchor stills are approved is **ready**. Approve
   spend for ONE job (amount + reason), tick the confirmation, **Submit one job** (live mode only).
4. **Lifecycle** - the Render Bay follows the job by itself: submitted -> queued -> generating -> downloading
   -> review. Free status checks, persisted to the manifest, survive restarts; no Claude intervention.
5. **Review** - watch it, **Accept clip** or **Reject** (with a note). Rejected / failed = a new spend
   approval for a new job. Nothing is ever retried automatically.
6. **Edit** - accepted clips are joined with hard cuts (trimming / speed ramps allowed).

## 3. State machines (derived only from files + manifest)

```
STILL  missing --generate|upload--> placed --approve--> approved --regenerate|upload(replace)--> changed
       changed --approve--> approved
       a still can only be generated once the still before it (its edit source) is approved

CLIP   blocked --stills approved--> ready --approve spend--> budget_approved --submit (paid)-->
       submitted -> queued -> generating -> downloading -> review --accept--> accepted
                                                          review --reject--> ready (new approval)
       failed / cancelled -> ready (new approval)
       accepted --an anchor still changes--> stale (regenerate)
```

## 4. Model routing (`app/forma/routing.py`, by shot class)

| Shot class | Clip count | Route | Status |
|---|---|---|---|
| environmental (motion, reveal, camera-only) | 1 | Wan 3.0 480p ($0.05/s) | proven_environmental |
|  |  | Veo 3.1 Fast first/last (hero, 720p+) | candidate_unproven |
| repetitive_labor | 2-3 (hard cuts) | Kling v3 Standard ($0.084/s) | candidate_unproven |
|  |  | Seedance 2.0, Seedance 2.5 | candidate_unproven |
|  |  | Wan 3.0 | failed (never selected) |
| precision (tool / material interaction) | 1-3 | Seedance 2.5 480p ($1.248 / 6 s) | proven_precision |
| time_jump (static completion) | 0 | generated still edit (or upload) | - |

**Still models** (`project.json` `stills`, `app/forma/production/still_gen.py`):

| Role | Default | Price | Status |
|---|---|---|---|
| first still (text-to-image) | `fal-ai/nano-banana` | $0.0398 | candidate_unproven |
| every later still (edit) | `fal-ai/nano-banana/edit` | $0.0398 | candidate_unproven |
| middle tier | `fal-ai/nano-banana-2` (+ `/edit`) | $0.08 at 1K | candidate_unproven |
| fallback | `fal-ai/nano-banana-pro` (+ `/edit`) | $0.15 | proven (Alpine / Video #1 / train-car stills) |

Edits are sent with `aspect_ratio: auto` (keep the source frame) and PNG output (no recompression drift
along the chain).

**Model policy (CP01 → CP02 proof, 2026-10-26):** the cheap edit holds continuity very well and handles additive
or local changes (a sawn stack, a brush pile, a builder pose), but it under-did large-area removals twice and
dropped approved objects. Use `stills.model_overrides` to put large-area removals / changes on
`fal-ai/nano-banana-2/edit` (it cleared CP02 in one call); escalate a still to `fal-ai/nano-banana-pro/edit` only if
Nano Banana 2 fails. The default stays cheap.

**Frame size:** `stills.frame_size` (Project #3: 768×1344, CP01's size). Every generated still is scaled to it
(models that change size stretch the same scene, so a scale - not a crop - keeps it aligned), and
`still_gen.normalize_approved()` scales an already-approved still and carries its approval over. A clip whose
start and end stills differ in size is blocked before any spend.

A shot on an unproven route must be marked `"proof": true`; production shots only get proven routes. Every
request is first/last-frame anchored, audio off, one prompt (Kling cannot combine an end frame with
multi_prompt), and checked against each model's run-time limits before upload.

## 5. Budget controls

- Project cap in `project.json` (`budget.cap_usd`, 0 in the template) and a per-clip ceiling
  (`per_clip_max_usd`).
- Every job needs its own spend approval (amount + note) - one approval pays for exactly one submission.
- Every still generation is its own confirmed call within `stills.per_still_max_usd`; its cost is counted
  as spent before fal is called (back to $0 only if fal refused the request) and it counts against the cap.
- A submit is refused if the estimate exceeds the approval, the ceiling, or the cap after counting spent and
  in-flight (reserved) money.
- Paid submits and generations only in `STUDIO_EXECUTION_MODE=live`; mock mode generates $0 placeholder
  stills in the sandbox. The job id / generation attempt is recorded before anything else.
- No automatic retries or chains anywhere: approving a still never generates the next one or submits a clip.
  A fal rejection before a job exists costs nothing and keeps the approval.

## 6. Generalized vs left behind

**Generalized from the train car into the engine**
- still workflow (hash-verified approval, changed-after-approval detection) -> `production/stills.py`
- approval-gated still generation, each still an edit of the previous approved one -> `production/still_gen.py`
- first/last-frame anchored clips, intermediate beat stills, adaptive clip counts -> `production/spec.py`
- construction/material/camera doctrine as executable checks -> `production/rules.py`
- fal model configs with schema + run-time limits, audio forced off -> `providers/video/fal.py`
- shot-class routing with evidence status -> `forma/routing.py`
- live attempt status, restart-proof, free checks -> `studio/attempt_status.py`
- per-clip spend approval and in-flight reservation -> `production/budget.py`, `production/submit.py`

**Left behind (kept as history, not used by Project #3)**
- the 20-checkpoint train-car plan, its stage runner and proof gate (`scripts/run_train_car_video_2_*`)
- per-provider proof runners and their setup/prepared/job files (`run_train_car_fal_proof.py`,
  Higgsfield runner - retired)
- the Wan-era single long-take prompts, the Alpine/Cliffside per-shot scripts and budget scripts
- the train car's own still stages (it stays manual-only; Project #3 generates stills through `still_gen.py`)
