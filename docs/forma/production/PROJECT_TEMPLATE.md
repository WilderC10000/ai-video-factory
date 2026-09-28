# FORMA production template (Project #3 on)

Project #3 is the first project built on one generic engine instead of per-project scripts.
Projects #1 (Cliffside) and #2 (Alpine; the train car as R&D) stay in the studio as history; the train
car is **frozen** - viewable, recoverable, never launched or submitted again.

Doctrine: `docs/forma/creative/FORMA_CREATIVE_BRAIN.md` (rules 1-11 + production lessons 1-11).

## 1. Project folder

```
data/forma_project_3/
  project.json      THE PLAN - concept, bibles, cameras, checkpoints, shots (edited by a person)
  manifest.json     STATE - approvals, uploads, spend approvals, provider jobs (written by the engine)
  stills/           <key>.jpg|png|webp - exactly one file per manual still (uploaded in the studio)
  stills/_replaced/ every file an upload replaced (never deleted)
  clips/            <clip>__attemptN_fal_<model>_raw.mp4 - one file per provider job
  edit/             hard-cut assembly (later)
docs/forma/production/example_project.json   format reference (not a concept)
app/forma/production/                         the engine (spec, rules, state, stills, budget, submit)
```

`project.json` ships as an empty template: `status: "template"`, `concept: null`, **`budget.cap_usd: 0`** -
nothing can be spent until a person sets a cap.

## 2. Studio workflow

1. **Plan** - write checkpoints and shots in `project.json`. The studio re-reads it on every import and
   shows doctrine errors; errors block every clip.
2. **Stills (Continuity Office / Production flow)** - open a still, read its ChatGPT brief, make the image in
   ChatGPT, drop it on the panel (or Choose file… -> Upload still). It is saved as `<key>.<ext>` and is
   **placed**, never auto-approved. Look at it, write what you checked, **Approve still**.
3. **Clips (Render Bay / Production flow)** - a clip whose two anchor stills are approved is **ready**. Approve
   spend for ONE job (amount + reason), tick the confirmation, **Submit one job** (live mode only).
4. **Lifecycle** - the Render Bay follows the job by itself: submitted -> queued -> generating -> downloading
   -> review. Free status checks, persisted to the manifest, survive restarts; no Claude intervention.
5. **Review** - watch it, **Accept clip** or **Reject** (with a note). Rejected / failed = a new spend
   approval for a new job. Nothing is ever retried automatically.
6. **Edit** - accepted clips are joined with hard cuts (trimming / speed ramps allowed).

## 3. State machines (derived only from files + manifest)

```
STILL  missing --upload--> placed --approve--> approved --upload(replace)--> changed --approve--> approved

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
| time_jump (static completion) | 0 | manual ChatGPT still edit | - |

A shot on an unproven route must be marked `"proof": true`; production shots only get proven routes. Every
request is first/last-frame anchored, audio off, one prompt (Kling cannot combine an end frame with
multi_prompt), and checked against each model's run-time limits before upload.

## 5. Budget controls

- Project cap in `project.json` (`budget.cap_usd`, 0 in the template) and a per-clip ceiling
  (`per_clip_max_usd`).
- Every job needs its own spend approval (amount + note) - one approval pays for exactly one submission.
- A submit is refused if the estimate exceeds the approval, the ceiling, or the cap after counting spent and
  in-flight (reserved) money.
- Paid submits only in `STUDIO_EXECUTION_MODE=live`; the job id is recorded before anything else.
- No automatic retries anywhere; a fal rejection before a job exists costs nothing and keeps the approval.

## 6. Generalized vs left behind

**Generalized from the train car into the engine**
- manual still workflow (hash-verified approval, changed-after-approval detection) -> `production/stills.py`
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
- nano-banana still generation (stills are manual only)
