# AI Video Factory

A system for producing realistic, AI-generated short-form "transformation" videos
(e.g. "he buried a private jet and turned it into an underground bunker") for
TikTok/YouTube Shorts/Reels, with persistent per-project state, a continuity
bible to keep every shot visually consistent, swappable AI providers, and
built-in cost tracking.

This repo is being built incrementally, milestone by milestone. **We are
currently on Milestone 2**, now optimized for minimum cost per finished
video rather than maximum quality (see "Cost model" below): a shot can be
given a cheap reference image first, then submitted as an asynchronous
image-to-video generation job, polled until it completes (or fails, or
times out), ending with a real clip file on disk and a cost record - all
using free mock providers. **No paid API calls happen anywhere yet** - real
providers will only be wired in after you explicitly approve the first one
(see "Cost model and provider research" below).

## How it's organized

```
app/
  main.py              FastAPI application entrypoint
  config.py            All settings, loaded from environment variables / .env
  db.py                SQLAlchemy engine/session setup
  models/
    project.py           Database tables: Project, Shot, CostRecord
    video_job.py          Database table: VideoJob (one generation attempt for one shot)
  schemas/project.py   API request/response shapes (Pydantic)
  providers/           Swappable AI provider interfaces
    base.py              Abstract LLM/Video/Image/Voice provider classes
    llm/mock.py           Free, deterministic mock LLM (used until Milestone 8)
    video/mock.py         Free, controllable mock video provider (used until a real
                           provider is approved) + a tiny real fixture MP4 it "generates"
    image/mock.py         Free, controllable mock reference-image provider + a tiny
                           real fixture JPG it "generates"
  services/
    errors.py            Exceptions shared by every service (paused, invalid state, over budget, ...)
    project_service.py  Concept/script/storyboard state transitions + continuity inheritance
    image_job_service.py Generate a shot's reference image: pause/spend-limit check, cost recording
    video_job_service.py Submit/poll/regenerate a shot's video job: pause check, spend-limit
                         check, retry-on-transient-error, timeout, cost recording, auto-uses
                         the shot's reference image if one exists (image-to-video)
  routers/projects.py  HTTP endpoints
scripts/
  seed_demo_project.py Runs one project end-to-end (incl. one rendered shot) from the terminal
tests/                 pytest suite (service layers + HTTP API)
data/                  SQLite database + per-project generated files (gitignored)
```

**Why it's split this way:** `services` is where every decision actually
happens (create a project, advance it to the next stage, submit/poll a video
job, record what it cost). `models` is what gets saved to the database.
`providers` is the "who actually generates the content" layer - swapping the
mock video provider for a real one later means adding one new file under
`providers/video/`, not rewriting the app. `routers` just exposes `services`
over HTTP so a future dashboard (or ChatGPT/Claude collaboration, or a queue
worker) can call it.

## Project state machine

Each project moves through: `IDEA -> CONCEPT_APPROVED -> SCRIPT_READY ->
STORYBOARD_READY -> ...` (later milestones add `KEYFRAMES_READY`,
`VIDEO_RENDERING`, `VIDEO_QA`, `VOICE_READY`, `EDITING`, `FINAL_QA`,
`READY_FOR_REVIEW`, `APPROVED`, `PUBLISHED`, `FAILED`). Each transition is
its own function in `project_service.py` and its own API endpoint, so any
step can be re-run without restarting the whole project.

Individual shots have their own status: `PENDING -> PROMPT_READY ->
GENERATING -> GENERATED -> QA_PASSED/QA_FAILED`, or `FAILED` if generation
didn't work out. This is real now, not just a placeholder: submitting a
shot moves it to `GENERATING`, and a completed job moves it to `GENERATED`
with a real clip file path - so a single bad shot can be regenerated
(`regenerate_shot_video`) without touching any other shot or restarting
the project.

## Reference images (image-to-video)

Since we're optimizing for cost, we prefer **image-to-video** over plain
text-to-video: a cheap still reference image gives the video model a
concrete starting frame, which noticeably improves continuity (same
subject, same colors, same framing) for very little extra cost - a
reference image costs roughly 1-2% of what the video itself costs (see
"Cost model" below).

```
shot (has a prompt, from the storyboard)
  -> generate_shot_reference_image()   calls an ImageProvider, saves the
                                        image, records its cost, sets
                                        shot.reference_image_path
```

This is synchronous (real image APIs like fal.ai's FLUX return a finished
image in seconds - no submit/poll needed, unlike video). Once a shot has a
reference image, `submit_shot_video_job()` **automatically** uses it -
callers don't need to wire the two together themselves. Regenerating a
failed shot's video reuses the existing reference image rather than paying
for a new one, since the image usually wasn't the problem.

## Video generation jobs

Generating one shot's clip is asynchronous, mirroring how every real AI
video API actually works (Veo/Kling/Runway/etc. all render in the
background and give you a job to poll):

```
shot (PROMPT_READY, reference image already generated if you want image-to-video)
  -> submit_shot_video_job()   creates a VideoJob row, calls the provider,
                                shot -> GENERATING
  -> poll_shot_video_job()     called repeatedly until the job reaches a
                                terminal state:
       PROCESSING  -> call again later
       COMPLETED   -> clip downloaded to data/projects/<project>/shots/<shot>.mp4,
                       shot -> GENERATED, a CostRecord is written
       FAILED      -> shot -> FAILED (provider rejected the request, or a
                       transient error exceeded max_job_poll_retries)
       TIMED_OUT   -> shot -> FAILED (stuck in PROCESSING past video_job_timeout_seconds)
  -> regenerate_shot_video()   for a FAILED/QA_FAILED shot: starts a brand
                                new job, up to max_regenerations_per_shot times
```

Every `VideoJob` row keeps a full audit trail for its attempt: provider,
provider's own job id, the exact prompt sent (built from the continuity
bible, same as Milestone 1), status, timestamps, output file, estimated
vs. actual cost, retry count, and any error message.

**Spending safety**: before a job is ever submitted, the service estimates
its cost and checks it against `MAX_SPEND_PER_PROJECT_USD` - if submitting
would push the project over budget, it's rejected immediately with no
provider call at all (so no money, real or simulated, is ever risked past
the limit). `FACTORY_PAUSED=true` blocks submission the same way.

## Continuity bible

When a project's concept is generated, a **continuity bible** is created
alongside it - a structured dictionary describing the main subject,
location, characters, materials/colors, time of day, weather, camera
style, and current construction state. Every shot's generation prompt is
built by combining this bible with that shot's specific beat description
(see `build_shot_prompt` in `project_service.py`), so later shots can't
randomly drift (e.g. a jet becoming an airliner). Later, AI visual QA will
compare generated footage against this same bible.

### Permanent visual rules (builder attention / camera behavior)

Discovered from the V2A keyframe experiment: a reference image generated
with no explicit camera-angle instruction defaults to a centered,
front-facing "portrait of a construction worker" composition - the
statistically dominant framing for "person + tool" prompts - and an
*edit* pass cannot reliably fix that afterward, because editing models are
built for small local corrections, not full pose/camera reorientation
("change as little else as possible" actively works against a fix this
large). The rules below are now a standing part of prompt generation and
(eventually) automated QA, not a one-off fix - not yet implemented in
code, but binding on every future prompt this project writes:

**BUILDER ATTENTION RULE** - During construction, the builder is absorbed
in his work and never acknowledges the camera. His gaze follows the
active tool/material/work area. Direct eye contact with the camera is a
QA failure unless a future storyboard explicitly requests it. Facial
visibility is NOT required in every shot - character consistency comes
from overall appearance, clothing, build, hair, beard, and silhouette,
not constant frontal facial visibility. Don't force the recurring
character's face into every frame.

**OBSERVATIONAL CAMERA RULE** - Construction footage should resemble
candid documentary footage captured by someone observing a real builder,
camera positioned roughly 30-120 degrees off his frontal direction. Favor
side, three-quarter-rear, and over-the-shoulder viewpoints, medium-wide
construction framing, and occasional closer action detail. An
occasional slightly elevated observational angle is fine. Avoid
portrait/presenter framing, symmetrical hero poses, commercial/product-ad
staging, and fashion/influencer posing. Documentary/imperfect framing is
fine - these should not look like polished advertising photography.

**COMPOSITIONAL HIERARCHY RULE** - The builder is not automatically the
dominant, centered subject of every frame. Depending on the shot, the
hierarchy should read as ACTION/BUILD -> BUILDER -> ENVIRONMENT or
BUILD+BUILDER -> ENVIRONMENT, not BUILDER -> everything else. The viewer
needs to watch construction happening ("candid footage of a man actually
building a cabin"), not admire a portrait of the character ("portrait of
a construction worker with a cabin behind him"). The landscape stays
visible for scale and atmosphere but is not used as a portrait backdrop -
the builder should read as genuinely occupying and working within the
environment.

**QA flags** (conceptual - not yet implemented): `builder_looking_at_camera`,
`portrait_pose`, `action_body_mechanics_implausible`, `tool_interaction_obscured`.

## Cost tracking

Every provider call writes a `CostRecord` row (provider name, operation
type, cost in USD). LLM calls are always `$0.00` (mock provider). Image and
video generation calls now carry a small **simulated** cost that matches
real-world pricing we researched (see "Cost model" below) - mock images
cost `$0.003/megapixel` and mock video costs `$0.04/second` by default -
purely so the spend-limit and cost-reporting logic (and the estimates
below) reflect real numbers. No real money changes hands from the mocks.
`Project.total_cost_usd` sums these. This means the moment a real paid
provider is added, cost tracking already works - no schema changes needed.

## Cost model and provider research

You told us cost matters more than quality for this first experiment - the
goal is to test whether the concepts/hooks get views and whether the
automation is economically viable, not to maximize visual fidelity. So we
researched the cheapest *credible* (not just cheapest possible) options,
and switched our primary candidate to **Wan 2.2 A14B Turbo** after you
independently verified its pricing against fal.ai's own model pages.

**On sourcing:** fal.ai's own site is blocked by this environment's network
policy, so our research came from several independent third-party
trackers. You separately confirmed the numbers below directly against
fal.ai's official model pages - that's now the authoritative source, and it
matches what we found. Still worth reconfirming on fal.ai's dashboard right
before spending, since pricing can change.

### Turbo vs. standard: technically compatible with our pipeline

We checked `fal-ai/wan/v2.2-a14b/image-to-video/turbo` against what our
image-to-video flow needs:

| Requirement | Turbo | Compatible? |
|---|---|---|
| Takes an image + text prompt | `image_url` + `prompt` params | Yes |
| 9:16 vertical output | `aspect_ratio: "9:16"` param, or follows the input image's own aspect ratio | Yes |
| Selectable cheap resolution | `resolution` param: 480p/580p/720p | Yes - **but defaults to 720p ($0.10) if not set**, so our adapter must always pass `resolution: "480p"` explicitly |
| Async submit/poll (matches our `VideoProvider` interface) | fal.ai's standard queue API (submit -> poll status -> fetch result) | Yes |

One real difference from the standard model: Turbo's output length is
governed by a `num_frames` param (81-100 inclusive, default 81 - **not the
fixed ~4s/65-frame output originally assumed here**, corrected after
re-verification in the Wan Turbo cost-down timelapse test below).
Frame counts above 81 bill at a 1.25x multiplier, so `WAN_TURBO`'s config
pins `num_frames: 81` explicitly (~5.06s @ 16fps) rather than trusting the
API's own default to stay put - resolution remains the only cost lever we
intend to vary. That's a minor pacing change (a 12-shot video becomes
~61s instead of ~48s) and no architectural problem -
`Shot.target_duration_seconds` stays a planning value; what a provider
actually delivered is on the `VideoJob` row. No technical reason not to
use Turbo.

### The cheapest credible pair, updated

| Purpose | Model | Endpoint identifier | Price | Billing |
|---|---|---|---|---|
| Reference image | **FLUX.1 [schnell]** | `fal-ai/flux/schnell` | $0.003/megapixel (rounds up; our 576x1024 default = 1MP) | Per megapixel |
| Video clip | **Wan 2.2 A14B Turbo, 480p** | `fal-ai/wan/v2.2-a14b/image-to-video/turbo` | **$0.05/video flat** (580p $0.075, 720p $0.10) | **Flat per video, NOT per second** |

Wan 2.2 A14B **standard** (non-turbo) stays available as a swappable
alternative - `fal-ai/wan/v2.2-a14b/image-to-video`, billed per-second
($0.04/580p... $0.04/480p, $0.06/580p, $0.08/720p at standard rates) - for
whenever a shot is worth spending more on for quality. See "Provider
configuration" below for how the code switches between them.

### Cost estimator now supports flat *and* per-second billing

The `VideoProvider.estimate_cost(request)` interface itself never assumed
a billing model - it always just returns a float. What needed updating was
our pricing configs, since the mock and the real adapter had been written
assuming every provider bills per-second. Both now use a shared
`VideoPricingConfig`/`FalVideoModelConfig` shape:

```python
# app/providers/video/mock.py and app/providers/video/fal.py
WAN_TURBO_PRICING    = VideoPricingConfig(billing="flat",       price_by_resolution={"480p": 0.05, "580p": 0.075, "720p": 0.10})
WAN_STANDARD_PRICING = VideoPricingConfig(billing="per_second", price_per_second_by_resolution={"480p": 0.04, "580p": 0.06, "720p": 0.08})
```

`estimate_cost()` looks at `billing` and either looks up a flat price by
resolution or multiplies a per-second price by the requested duration.
Every cost figure in this README, the mock provider's simulated costs, and
the spend-limit checks all go through this same logic now - not a
per-second assumption baked into one formula.

### The optimized (cost-first) pipeline

1. **480p, not 720p/1080p** for video - half (or less) the cost of the next
   tier up. Our adapter always sends `resolution: "480p"` explicitly, since
   Turbo defaults to 720p if you don't.
2. **Turbo over standard** - a flat $0.05/video beats standard's
   ~$0.16-0.20 for a 4-5s clip at 480p, for the same underlying 14B model
   family, just optimized for speed over marginal quality.
3. **Image-to-video, not text-to-video** - the reference image is ~6% of
   the shot's cost ($0.003 of $0.053) but meaningfully helps continuity.
4. **A reference image is generated once per shot and reused** on every
   regeneration - `regenerate_shot_video()` never re-generates the image,
   only the video, unless you explicitly ask for a new image.
5. **No native audio from the video provider** - we'll add voiceover
   separately later (Milestone 4) with a provider chosen the same way.

### Estimated costs (updated for Turbo's flat pricing)

Based on our current 12-shot storyboard template at Turbo's rates:
**1 reference image = $0.003, one video clip = $0.05 flat, one shot
(image + video) = $0.053.**

| | Cost |
|---|---|
| 1 reference image | $0.003 |
| 1 Wan Turbo 480p video clip | $0.05 |
| 1 finished video (12 shots, ~48s, 0% regeneration) | **$0.636** |
| 10 finished videos | $6.36 |
| 100 finished videos | $63.60 |

(For comparison, the previous per-second Wan-standard estimate was $2.44 /
$24.36 / $243.60 for the same 12 shots - Turbo cuts this to about a
quarter.) These cover image + video generation only. LLM costs stay $0
(mock provider through Milestone 8), and voiceover/assembly (Milestones
4-5) aren't built yet so aren't included.

**With regeneration.** A regenerated shot reuses its existing reference
image, so a regeneration only costs the flat video price again ($0.05),
not the full $0.053:

| Regeneration rate | Cost / video | Cost / 10 videos | Cost / 100 videos |
|---|---|---|---|
| 0% | $0.636 | $6.36 | $63.60 |
| 20% | $0.756 | $7.56 | $75.60 |
| 50% | $0.936 | $9.36 | $93.60 |

### Provider configuration - switching models

`FalVideoProvider` (app/providers/video/fal.py) and `FalImageProvider`
(app/providers/image/fal.py) both take a config object in their
constructor:

```python
FalVideoProvider(WAN_TURBO)      # cheapest baseline - $0.05/video flat @480p, ~5s (81 frames, pinned)
FalVideoProvider(WAN_STANDARD)   # per-second alternative, e.g. for one important shot
FalVideoProvider(KLING_2_6_PRO)  # quality bake-off candidate - $0.07/s, no resolution tiers
FalVideoProvider(VEO_3_1_FAST)   # quality bake-off candidate - $0.10/s, 1080p
FalVideoProvider(SEEDANCE_2_0_FAST)  # one-time premium benchmark - $0.2419/s flat, 480p/720p
FalVideoProvider(WAN_3_0_STANDARD)   # cost-down 15s+ candidate - $0.05/$0.10/$0.20 per s @ 480p/720p/1080p
FalImageProvider(FLUX_SCHNELL)            # cheapest reference image - $0.003/MP
FalImageProvider(FLUX_PRO)                # higher-fidelity reference image - $0.04/MP
FalImageProvider(NANO_BANANA_PRO_GENERATE)  # fresh text-to-image, aspect_ratio-based - $0.15/image flat
FalImageProvider(NANO_BANANA_PRO_EDIT)      # EDITS an existing image (not text-to-image) - $0.15/image flat
```

`NANO_BANANA_PRO_EDIT` and `NANO_BANANA_PRO_GENERATE` are both different
from the two FLUX configs, and from each other: `NANO_BANANA_PRO_EDIT`
edits an *existing* image via `edit_image()`/`ImageEditRequest`;
`NANO_BANANA_PRO_GENERATE` generates fresh from a text prompt via
`generate_image()`/`ImageGenerationRequest` like FLUX, but with a
different request shape (`aspect_ratio`/`resolution`, not `image_size:
{width, height}` - `FalImageModelConfig.uses_aspect_ratio` selects which
shape `generate_image()` builds). Both bill a flat per-image price
(`price_per_image`) instead of per-megapixel. See "Running the V2A
keyframe experiment" and "Running the composition test" below for what
each is used for.

Adding a future fal.ai model (or upgrading one shot to a premium provider
later) means adding one more named config, not touching
`video_job_service.py`, the routers, or anything else that calls
`VideoProvider`.

`FalVideoModelConfig` also carries the per-model request-shape differences
discovered while verifying Kling and Veo against their own docs (not
assumed from Wan's shape): `image_param_name` (Kling uses
`start_image_url`, not `image_url`), `supports_resolution_param` (Kling has
no selectable resolution - quality is inherent to the pro tier), and
`extra_payload` (static fields always sent for that model, e.g. Kling's
fixed `duration`/`generate_audio`/`negative_prompt`, Veo's fixed
`duration`/`generate_audio`). Kling's `cfg_scale` is deliberately left
unset so fal.ai's own documented default applies, rather than us pushing it
toward an extreme - the bake-off is meant to be a fair comparison of each
model's own out-of-the-box behavior.

FLUX_PRO (not "ultra") was deliberately chosen over FLUX pro Ultra for the
bake-off's reference image: Ultra's billing was ambiguous between two
conflicting figures across sources ($0.06/image vs. $0.05/megapixel), and
Ultra sizes its output via `aspect_ratio` rather than explicit
width/height, which would make the exact megapixel count - and so the
exact cost - impossible to know before the call. FLUX_PRO takes the same
explicit width/height as FLUX_SCHNELL, keeping every candidate's cost
exactly pre-computable, consistent with every other provider in this
codebase.

**These real adapters are written and locally tested (35 tests in
`tests/test_fal_providers.py`, using `httpx.MockTransport` to simulate
fal.ai's documented request/response shapes with zero network calls and
zero cost) but are NOT wired in as the active provider anywhere in the
app** - `routers/projects.py` still uses the mocks. Wan Turbo, Kling, and
Veo have all been executed against the live API in the quality bake-off;
Nano Banana Pro Edit has too, in V2A (its frames were rejected for
composition, not for the adapter itself - see "Permanent visual rules"
above). Nano Banana Pro Generate has not yet - its first real invocation
is the approved composition test.

### The one real test - what happened, and a bug it found

**Endpoints:**
- Video: `fal-ai/wan/v2.2-a14b/image-to-video/turbo`, called with
  `resolution: "480p"` explicitly set
- Image: `fal-ai/flux/schnell`

This test is approved (max spend $0.06). It couldn't be run from the
development sandbox this app was originally built in - that sandbox's
network egress policy returns a hard 403 policy denial on every fal.ai
host - so it was run from a local machine that can reach fal.ai instead,
using `scripts/run_first_fal_test.py`.

**Result:** the FLUX schnell image succeeded (2.0s, $0.003) and the Wan
Turbo video job submitted successfully (job accepted, estimated cost
$0.0500) - but the status check failed with **HTTP 405**. The script
correctly stopped immediately both times below: no retry, no second job
ever submitted.

**Two bugs, found in sequence, both from getting fal.ai's queue routing
wrong** - the second only surfaced after fixing the first and testing
again for real, so it's worth recording both:

1. *First attempt* (wrong): assumed only the `turbo` subpath needed
   stripping for status/result requests, keeping
   `fal-ai/wan/v2.2-a14b/image-to-video` as the base. Still 405'd on the
   next real test.
2. *Actual root cause*, confirmed by reading fal.ai's own official Python
   client source (`fal_client.client.AppId.from_endpoint_id`, from
   github.com/fal-ai/fal) rather than guessing from documentation prose
   again: fal.ai's queue tracks requests under **owner/alias only** -
   `fal-ai/wan` - dropping *everything* after that (`v2.2-a14b/`
   `image-to-video/turbo`), not just the subpath. Submission still uses
   the full path; status/result never does.
3. The same source also showed fal.ai's own client doesn't reconstruct
   these URLs at all - it saves and reuses the `status_url`/`response_url`
   fal.ai returns in the submission response. `get_job_status()` now does
   the same: it prefers those server-provided URLs when available (the
   robust path, immune to us getting the formula wrong a third time), and
   only falls back to reconstructing from `owner/alias` when they're not
   available (e.g. recovering a job whose original response wasn't
   saved). `FalVideoModelConfig.queue_app_id` implements the fallback;
   `app/providers/video/fal.py`'s module docstring and that property's
   docstring have the full detail.

Our own adapter tests had mocked the same wrong assumption the code made
each time, which is why they kept passing despite the bugs - only the
real calls surfaced them. The tests now cover both the server-provided-URL
path and the corrected fallback, and would fail again if either regressed.

**Diagnostics:** every outgoing request `FalVideoProvider` makes now
prints its exact method and URL (`[fal debug] GET https://...`) - never
headers, so the API key is never printed - specifically so a routing
problem like this is visible immediately instead of needing another round
of guessing.

**Recovering the orphaned job:** the video job that already succeeded in
being submitted (job id `01a06472-6d21-7642-b26e-1dbb856b1e87`, likely
already billed $0.05 by fal.ai regardless of our polling bugs) can be
checked and downloaded - never resubmitted - with
`scripts/recover_fal_video_job.py`. `run_first_fal_test.py` now also saves
the job id and fal.ai's own status/result URLs to `data/fal_test/last_job.json`
immediately after a successful submission (before polling even starts),
so a future failure like this one leaves the recovery script able to use
the robust server-provided-URL path automatically instead of only the
fallback. See "Running the one real fal.ai test" below for exact commands
for both scripts.

## Requirements

- Python 3.11+
- `ffmpeg` on PATH - required to run `scripts/run_continuity_test.py`
  (extracts a propagated reference frame from each clip between stages;
  see "Running the continuity test" below), `scripts/run_wan_turbo_2clip_timelapse_test.py`
  (same last-frame extraction, plus final concatenation), or to
  regenerate the mock providers' placeholder fixtures. Not required for
  anything else - the mock/API/demo flows don't need it. Install from
  https://ffmpeg.org/download.html, or on Windows: `winget install ffmpeg`.
- No paid API keys needed through Milestone 2 for anything except the
  real fal.ai test scripts, which are opt-in and always ask for confirmation.

## Setup

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env   # defaults are fine as-is
```

## Running the demo (no server needed)

This runs one project through the full pipeline from the terminal - concept,
script, storyboard, then submitting and polling a video job for the first
shot to completion - using only free mock providers:

```bash
python -m scripts.seed_demo_project
# or with your own idea:
python -m scripts.seed_demo_project "He converted an enormous concrete pipe into a hidden luxury home."
```

## Running the one real fal.ai test (spends real money - max $0.06)

`scripts/run_first_fal_test.py` generates exactly one FLUX schnell
reference image and exactly one Wan 2.2 A14B Turbo (480p, 9:16) video from
it, using the real `FalImageProvider`/`FalVideoProvider` adapters directly
- not the mocks, and not routed through the project/database pipeline.

**Safety properties, all in the script itself:**
- Refuses to run if `FAL_API_KEY` isn't found in `.env` (prints whether it
  loaded, without printing the key).
- Computes and prints the exact cost estimate ($0.0530 expected) and
  refuses to proceed if it exceeds the $0.06 hard cap - before any network
  call.
- Prints the full plan (prompts, model ids, resolution, aspect ratio, cost)
  and asks you to type `yes` before spending anything (skip with `--yes`).
- No automatic retries anywhere - image generation, video submission, each
  status check, and the download are each a single attempt; any failure
  stops the script immediately with a clear message. Waiting for a
  still-processing video is normal polling, not a retry, and is itself
  capped (5 minutes) so the script can't hang forever.
- Generates exactly one image and exactly one video. No regeneration path.
- Saves both outputs to `data/fal_test/` (gitignored) and prints the final
  image/video paths, actual cost, and generation time.

Requires `FAL_API_KEY=your_key_here` in your `.env` file first (get one at
https://fal.ai/dashboard/keys).

```bash
python -m scripts.run_first_fal_test
# or, to skip the "type yes to proceed" confirmation prompt:
python -m scripts.run_first_fal_test --yes
```

### Recovering a job if something goes wrong after submission

If the video job was submitted successfully (you have a provider job id)
but the script then failed for any reason - a status-check bug, a dropped
connection, closing the terminal - **the job may already be running or
billed on fal.ai's side regardless.** `scripts/recover_fal_video_job.py`
checks on and downloads that exact job. It never creates a new job, so
running it repeatedly costs nothing extra:

```bash
python -m scripts.recover_fal_video_job <provider_job_id>
# if the original job used Wan standard instead of Turbo:
python -m scripts.recover_fal_video_job <provider_job_id> --standard
# to choose where the clip is saved:
python -m scripts.recover_fal_video_job <provider_job_id> --out clip.mp4
```

`run_first_fal_test.py` itself prints this exact command (with your job id
already filled in) if it fails after a job has been submitted, so you
don't need to copy the id by hand.

## Running the continuity test (spends real money - max $0.20)

A research probe, not the final architecture: does chronological
construction *continuity* survive across several sequential Wan
generations, and how much visual drift accumulates? `scripts/run_continuity_test.py`
generates 3 shots of the same construction project (a lone builder in a
sea cave: site prep -> floor/platform built -> wall framing erected),
using **last-frame propagation** instead of independent generations:

```
Shot 1: FLUX schnell reference image (the only image call)
        -> Wan Turbo animates it -> clip 1
Shot 2: ffmpeg extracts the actual last frame of clip 1 (free, local,
        no API call) -> that frame becomes shot 2's reference image
        directly -> Wan Turbo animates it -> clip 2
Shot 3: same idea, seeded from clip 2's last frame -> clip 3
```

Each stage inherits the literal pixels of the previous one (the same
cave, the same worker, whatever was already built), not a fresh
text-to-image reinterpretation - see "Continuity bible" below for why
that matters, and the cost model section above for why this is also the
cheapest option available with our current FLUX + Wan Turbo setup. A
shared **continuity bible** text fragment (worker appearance, cave
geometry, material palette, camera style) is repeated in every prompt on
top of the propagated image, and each stage's prompt explicitly prohibits
later-stage elements (e.g. shot 2 must show no walls/furniture/interior;
shot 3 must show no insulation/cabinetry/decor) to fight drift from both
directions.

**Safety, same pattern as the other real-call scripts:**
- Exactly 1 FLUX call + exactly 3 Wan Turbo calls - hard-coded, no loop
  that could ever submit a 4th, no regeneration path.
- Total cost computed and checked against the $0.20 cap before any call;
  one `yes` confirmation gates the whole chain.
- No automatic retries - any failure at any stage (image, submit, status
  check, download, frame extraction) stops the script immediately.
- `manifest.json` is written incrementally after every step - even a
  failure partway through leaves a complete diagnostic record (every
  prompt, which image fed which stage and how it was obtained, extraction
  offset, provider job id, status/result URLs, costs, timestamps) and a
  recoverable job (`recover_fal_video_job.py` still works on any of the 3
  job ids).

Requires `FAL_API_KEY` in `.env` (like the other real-call scripts) and
`ffmpeg` on PATH (only script that actually needs it to run, not just to
regenerate fixtures):

```bash
python -m scripts.run_continuity_test
# adjust how many seconds before each clip's end the propagated frame is taken from:
python -m scripts.run_continuity_test --frame-offset 0.5
# skip the "type yes" confirmation prompt:
python -m scripts.run_continuity_test --yes
```

Outputs land in `data/fal_continuity_test/` (gitignored): the FLUX
reference image, all 3 clips, both propagated frames, and `manifest.json`.
Review the 3 clips yourself afterward for continuity and drift - that's
the actual experiment; this tooling only gets you the clips and the data
to judge them by.

## Running the quality bake-off (spends real money - max $1.25)

The continuity probe validated the pipeline mechanics at Wan Turbo 480p;
this test asks the actual product question from the current creative
spec - which video model is worth paying for? `scripts/run_bakeoff_test.py`
sends the **same reference image** and the **same construction action**
through 3 candidates, so any difference in the output reflects model
quality, not different creative direction:

| Candidate | Endpoint | Resolution | Duration | Billing |
|---|---|---|---|---|
| `wan_turbo_480p` | `fal-ai/wan/v2.2-a14b/image-to-video/turbo` | 480p | ~5s (81 frames, fal.ai's default - `num_frames` wasn't yet pinned explicitly at the time; corrected below) | $0.05 flat |
| `kling_2.6_pro` | `fal-ai/kling-video/v2.6/pro/image-to-video` | n/a (inherent) | 5s | $0.07/s = $0.35 |
| `veo_3.1_fast` | `fal-ai/veo3.1/fast/image-to-video` | 1080p | 6s | $0.10/s = $0.60 |

Reference image: one `FLUX_PRO` (`fal-ai/flux-pro/v1.1`) generation of the
recurring builder mid-construction on a beautiful natural site ($0.04).
Estimated total: **$1.04**, against a **$1.25** hard cap.

**Test action, chosen deliberately to stress the models** (per the current
creative spec's priority order - hand/tool realism and structural
continuity over raw prettiness): the builder cuts a timber board with a
circular saw, then carries and fastens it onto an incomplete wall frame on
an ocean-cliff building site. Both the reference-image prompt and the
action prompt are shared verbatim across all 3 candidates - the only
controlled variable is the video model itself.

**Safety, same pattern as every other real-call script:**
- Exactly 1 image call + exactly 3 video calls - hard-coded, no loop that
  could ever submit a 4th of anything, no regeneration path.
- Total cost computed and checked against the $1.25 cap before any call;
  one `yes` confirmation gates the whole run.
- No automatic retries - any failure at any stage stops the script
  immediately, printing a `recover_fal_video_job.py <job_id>` hint for any
  candidate that had already been submitted.
- `manifest.json` written incrementally after every step: exact prompt,
  model/endpoint, resolution, duration, estimated cost, actual cost, job
  id, status/response URLs, timestamps, and output path for every
  candidate - even a partial failure leaves a full diagnostic trail.

Requires `FAL_API_KEY` in `.env` (like the other real-call scripts):

```bash
python -m scripts.run_bakeoff_test
# skip the "type yes" confirmation prompt:
python -m scripts.run_bakeoff_test --yes
```

Outputs land in `data/fal_bakeoff_test/` (gitignored): the shared
reference image, all 3 candidate clips (clearly labeled by filename -
`wan_turbo_480p.mp4`, `kling_2.6_pro.mp4`, `veo_3.1_fast.mp4`), and
`manifest.json`. Verified entirely offline before any real call: a full
mocked-transport dry run exercises the image generation, all 3 submit/
poll/download cycles, and the manifest write, asserting each candidate's
request payload matches its model's documented shape (e.g. Kling's
`start_image_url` with no `resolution` key, Veo's `duration: "6s"` string)
and that the total cost math lands at $1.04. Review the 3 clips yourself
afterward against the bake-off's comparison criteria - this tooling only
gets you the clips and the data to judge them by.

## Running the atomic-cut experiment (spends real money - max $1.15)

The bake-off's clips all shared one weakness: rigid-object/tool morphing
in the timber, most visible where the prompt asked for several physical
state changes in one generation (pick up saw -> cut -> lift board -> carry
-> position -> fasten). `scripts/run_atomic_cut_test.py` tests a specific
hypothesis - does restricting a clip to ONE dominant physical action
(continuous saw-cutting, nothing else) materially reduce that morphing? -
as a **single-variable experiment** against the bake-off, so the model
comparison stays valid:

- **Reuses the bake-off's own reference image** - reads its path straight
  out of `data/fal_bakeoff_test/manifest.json` and fails immediately if
  that file doesn't exist yet (run `run_bakeoff_test.py` first). No new
  image generation, no image cost.
- **Same 3 models, same configs** as the bake-off (`WAN_TURBO` 480p/4s,
  `KLING_2_6_PRO` 5s, `VEO_3_1_FAST` 1080p/6s) - nothing about resolution,
  duration, or provider settings changed.
- **The only thing that changes is the prompt** - a new `ATOMIC_CUT_PROMPT`
  restricted to continuous circular-saw cutting, explicitly forbidding any
  second action (picking up/carrying/installing the board, changing tools,
  walking away) - sent identically to all 3 candidates, no per-model
  rewriting, so model choice stays the only real variable.

This makes a direct, one-to-one comparison possible per model: `wan_turbo_480p.mp4`
(compound) vs. `wan_atomic_cut.mp4` (atomic), and likewise for Kling and
Veo - same model, same reference image, same environment/builder/structure,
only the action's complexity changed.

**Safety, same pattern as every other real-call script:**
- Exactly 3 video calls, zero image calls - hard-coded, no loop that could
  ever submit a 4th of anything or regenerate the reference image.
- Total cost computed and checked against the $1.15 cap before any call
  (estimated $1.00: $0.05 + $0.35 + $0.60); one `yes` confirmation gates
  the whole run.
- No automatic retries - any failure stops the script immediately, with a
  `recover_fal_video_job.py <job_id>` hint for any candidate already
  submitted.
- `manifest.json` written incrementally, including which bake-off
  manifest/image path it reused, for full traceability.

Requires `FAL_API_KEY` in `.env` and a completed `run_bakeoff_test.py` run
(its `manifest.json` and `reference_image.jpg` must already exist):

```bash
python -m scripts.run_atomic_cut_test
python -m scripts.run_atomic_cut_test --yes
```

Outputs land in `data/fal_atomic_cut_test/` (gitignored): `wan_atomic_cut.mp4`,
`kling_atomic_cut.mp4`, `veo_atomic_cut.mp4`, and `manifest.json`. Verified
entirely offline before any real call: a mocked-transport dry run (using a
fake pre-existing bake-off manifest/image so the "reuse, don't regenerate"
path is actually exercised) asserts no image endpoint is ever called, each
candidate's payload carries the atomic-cut prompt and not the old
compound-action one, and the total cost lands at exactly $1.00. A second
check confirms the script fails safely (no call made) if the bake-off
manifest is missing.

If at least 2 of the 3 models show substantially less morphing/more
believable tool-object interaction on the atomic clip than their compound
counterpart, that validates the atomic-action hypothesis and the next step
is the Stage/Clip storyboard architecture (see "What's next"). If none do,
the morphing is a model-level limitation rather than a prompt-complexity
problem, and model choice/reference conditioning need another look before
any architecture change.

## Running the V2A keyframe experiment (spends real money - max $0.35)

Atomic V1 confirmed one-action-per-clip helps, but not enough on its own -
hand placement, saw orientation, and blade/wood contact still looked
AI-generated across all 3 models. `scripts/run_v2a_keyframes_test.py`
tests a narrower hypothesis first, **before spending anything on video**:
can a start/end frame pair be made mechanically correct enough to be worth
animating at all?

It makes exactly 2 **image-edit** calls (`NANO_BANANA_PRO_EDIT` -
`fal-ai/nano-banana-pro/edit`, $0.15/image flat) against the existing
bake-off reference image - **no video generation happens in this step**:

- `saw_start_frame.jpg` - the bake-off reference image edited so the saw's
  base plate sits flat against the board, the blade is aligned with the
  cut and just touching the wood, and the builder's hand/tool grip and
  stance are anatomically plausible (five fingers per hand, no merged
  hand/tool geometry).
- `saw_end_frame.jpg` - edited **from the start frame's own output** (not
  independently from the base image), showing the same setup with the cut
  visibly progressed (kerf, light sawdust) - chaining keeps both frames
  describing one continuous physical configuration rather than two
  separately-invented ones, the same forward-propagation principle used
  elsewhere in this project.

This needed one small, scoped provider addition (not the Stage/Clip
architecture): `ImageEditRequest` (`app/providers/base.py`) and
`FalImageProvider.edit_image()`/`estimate_edit_cost()` plus the
`NANO_BANANA_PRO_EDIT` config (`app/providers/image/fal.py`) - prompt-
guided editing of an *existing* image is a different capability from
FLUX's text-to-image generation, needing its own upload step (the same
2-step upload `FalVideoProvider` already uses for video reference images)
and flat per-image billing instead of per-megapixel. Covered by 3 new
unit tests (mocked transport) alongside the existing 60.

**This script does not generate video and never will on its own** - it
stops after the 2 image edits so you can inspect them by eye against the
mechanical-correctness checklist above. **No automatic regeneration**: if
either frame is physically wrong, the script does not retry or fix it -
that decision belongs to you, informed by looking at the images.

**Safety, same pattern as every other real-call script:**
- Exactly 2 image-edit calls, zero video calls - hard-coded.
- Total cost ($0.30 estimated) checked against the $0.35 cap before any
  call; one `yes` confirmation gates the run.
- No automatic retries.
- `manifest.json` records both prompts, costs, and output paths.

Requires `FAL_API_KEY` in `.env` and a completed `run_bakeoff_test.py` run:

```bash
python -m scripts.run_v2a_keyframes_test
python -m scripts.run_v2a_keyframes_test --yes
```

Outputs land in `data/fal_v2a_keyframes_test/` (gitignored):
`saw_start_frame.jpg`, `saw_end_frame.jpg`, `manifest.json`. Verified
entirely offline: a mocked-transport dry run confirms no video endpoint is
ever touched, exactly 2 edit calls happen, the end frame is chained from
the start frame's own output (not the base image), and the total lands at
exactly $0.30.

**V2B (a separate, later, human-gated step, not yet built)**: only after
these keyframes are manually approved, animate them with a first/last-
frame-conditioned video model (candidates researched: Wan 2.1 FLF2V,
Kling O1) - see the project's own research notes for the fuller comparison
against motion-transfer approaches (Kling 3.0 Motion Control, Wan Motion).

**V2A was run for real and rejected** - not for mechanical saw accuracy
(the actual target of that experiment) but for a different, more
fundamental problem: the builder read as centered, front-facing, and
posed for the camera, like a portrait rather than candid footage. Root
cause and fix: see "Permanent visual rules" above and "Running the
composition test" below - V2A will be re-run against a correctly-composed
base image once the composition test passes.

## Running the composition test (spends real money - max $0.20)

V2A's rejection traced back further than V2A itself: the *bake-off's*
original reference image had no camera-angle instruction in its prompt,
so it defaulted to a centered, front-facing "hero shot" - and V2A's edit
pass inherited and preserved that (edit models make small local
corrections; a full pose/camera reorientation is a global change that
"change as little else as possible" actively works against). The fix has
to happen at generation time, not edit time.

`scripts/run_composition_test.py` tests that fix in isolation, before
spending anything on mechanical correction or video: **one freshly
generated** (not edited) base action image, using `NANO_BANANA_PRO_GENERATE`
(`fal-ai/nano-banana-pro`'s text-to-image endpoint, not `/edit` - a
different request shape, `aspect_ratio` + `resolution` instead of
`image_size: {width, height}`), with the observational-camera and
builder-attention rules above written directly into the prompt from the
start, rather than requested as changes to an existing image.

**Exactly 1 call, no reference image, no edit call, no video call:**
- Total cost ($0.15 estimated) checked against the $0.20 cap before the
  call; one `yes` confirmation gates it.
- No retries, no auto-regeneration.
- `manifest.json` records the prompt, cost, and output path.

```bash
python -m scripts.run_composition_test
python -m scripts.run_composition_test --yes
```

Outputs land in `data/fal_composition_test/` (gitignored): `action_base_frame.jpg`,
`manifest.json`. Verified entirely offline: a mocked-transport dry run
confirms no `/edit` or video endpoint is ever touched, exactly 1 call
happens, the payload uses `aspect_ratio`/`resolution` (not `image_size`),
and the cost lands at exactly $0.15. Mechanical saw accuracy is
deliberately NOT a pass/fail criterion for this step - only composition,
gaze, and working posture are; mechanical correction is the next, later
stage, reusing V2A's existing `NANO_BANANA_PRO_EDIT` capability against
whatever this test produces once approved.

**Result: PASSED and approved.** `action_base_frame.jpg` is now the target
visual language for construction-action shots - side/three-quarter-rear
observational angle, zero eye contact, natural working posture, cabin
reading as an active project rather than a backdrop. Subsequent stages
must preserve this composition exactly, not regenerate or reangle it -
see "Running the mechanical still-image test" below.

## Running the mechanical still-image test (spends real money - max $0.20)

The composition is now locked in as approved - this next gate asks a
narrower question on top of it: can `NANO_BANANA_PRO_EDIT` correct the
saw's mechanics on the *approved* `action_base_frame.jpg` **without**
regressing the composition it took two prior experiments to get right?
This is the opposite failure mode from V2A: V2A edited a *wrong*
composition and asked for mechanical + implicit pose changes together;
this test edits an *already-correct* composition and asks for mechanical
changes only, with an explicit, exhaustive preserve-list (camera
angle/position, body orientation, downward gaze, posture, cabin,
landscape, lighting, framing, clothing) - the kind of small, local
correction edit models are actually good at.

`scripts/run_mechanical_start_frame_test.py` reads the approved frame's
path straight out of `data/fal_composition_test/manifest.json` (fails
safely, no call made, if that experiment hasn't been run/approved yet) and
makes exactly ONE edit call - **start frame only, no end frame yet**. The
next end-frame stage is a deliberately separate, later, human-gated step
once this one is reviewed.

**Success requires BOTH, not either:**
- **A. Mechanical improvement** - base plate flush, blade aligned,
  plausible grip, five fingers per hand, hands clear of the blade path,
  board properly supported.
- **B. Composition preserved** - camera angle, body orientation, gaze,
  posture, cabin, landscape, lighting, framing, and clothing all
  unchanged from the approved frame.

A saw fix that breaks the composition is a **failure**, even if the
mechanics improved - the script does not judge this itself, it produces
one image for manual review against both criteria.

**Exactly 1 call, no reused end-frame chaining, no video call:**
- Total cost ($0.15 estimated) checked against the $0.20 cap before the
  call; one `yes` confirmation gates it.
- No retries, no automatic regeneration of a bad result.
- `manifest.json` records the source frame path, prompt, cost, and output path.

```bash
python -m scripts.run_mechanical_start_frame_test
python -m scripts.run_mechanical_start_frame_test --yes
```

Outputs land in `data/fal_mechanical_start_test/` (gitignored):
`mechanical_start_frame.jpg`, `manifest.json`. Verified entirely offline: a
mocked-transport dry run against a fake pre-existing composition manifest
confirms no video endpoint and no 2nd edit call ever happens, the prompt
carries both the mechanical-fix language and the exhaustive preserve-list,
and the cost lands at exactly $0.15. No provider/adapter code changed for
this step - it's a new script reusing `NANO_BANANA_PRO_EDIT` exactly as
V2A already established and tested it.

**Result: PASSED and approved.** `mechanical_start_frame.jpg` preserved
every approved composition quality (no eye contact, downward gaze,
observational angle, posture, cabin/landscape/framing) while making the
saw/body interaction materially more believable - confirming the local
mechanical-edit approach works when the source composition is already
correct.

## Running the mechanical end-frame test (spends real money - max $0.20)

The narrowest possible next gate: can the same edit approach produce a
SECOND frame - the same cut progressed further - that stays visually
consistent with the approved start frame? This is deliberately not yet a
video test; it only asks whether two mechanically plausible *endpoints* of
one physical action can be created at all, since that's the actual
prerequisite for a first/last-frame interpolation experiment later.

`scripts/run_mechanical_end_frame_test.py` reads the approved start
frame's path out of `data/fal_mechanical_start_test/manifest.json` (fails
safely, no call made, if that stage hasn't been run/approved yet) and
makes exactly ONE edit call, asking for the cut to progress ~40-60%
further along the same cut line - kerf and light sawdust to show it,
saw/blade advanced but base plate still seated - while explicitly keeping
the board rigid, fully supported, and unchanged in size/shape. Board
separation or a sagging waste side is deliberately out of scope here -
that's its own future atomic-action test, not conflated with this one.
Everything from the still-image test's preserve-list (camera, builder
orientation/gaze/posture, identity, cabin, landscape, lighting, framing)
carries over unchanged, plus the saw's own identity/appearance.

**Success requires ALL of:** visible progression along the same cut, board
rigidity preserved (not cut through/separated/sagging), and the full
composition preserve-list from the start-frame stage. Any one of these
failing is a failure, even if the others succeed.

**Exactly 1 call, no video call:**
- Total cost ($0.15 estimated) checked against the $0.20 cap before the
  call; one `yes` confirmation gates it.
- No retries, no automatic regeneration of a bad result.
- `manifest.json` records the source frame path, prompt, cost, and output path.

```bash
python -m scripts.run_mechanical_end_frame_test
python -m scripts.run_mechanical_end_frame_test --yes
```

Outputs land in `data/fal_mechanical_end_test/` (gitignored):
`mechanical_end_frame.jpg`, `manifest.json`. Verified entirely offline: a
mocked-transport dry run against a fake pre-existing start-frame manifest
confirms no video endpoint and no 2nd edit call ever happens, the prompt
carries both the progression language and the rigidity/preserve language,
and the cost lands at exactly $0.15. No provider/adapter code changed -
reuses `NANO_BANANA_PRO_EDIT` exactly as the prior two image stages did.

Once both frames are approved together, the first/last-frame video-
interpolation test (candidates: Wan 2.1 FLF2V, Kling O1) becomes its own
separate, later, explicitly gated experiment.

## Running the Seedance 2.0 benchmark (spends real money - max $2.30)

A deliberately different kind of test from every still-image gate above: a
**one-time quality-ceiling benchmark**, not a step toward a production
model. The still-image gates ask whether a workflow can fix one specific
mechanical detail (the saw); this asks a bigger question - using a current
premium model, what does the upper bound of "exciting, believable
accelerated construction progression" actually look like across a full
8-second clip? Once that ceiling is established, cheaper models (Wan,
etc.) get judged against a concrete target instead of a vague one, and
premium generation stays reserved for hook/reveal/hard-interaction shots
in the eventual tiered production system - not every second of a final
video.

**Model: `SEEDANCE_2_0_FAST`** (`bytedance/seedance-2.0/fast/image-to-video`,
`app/providers/video/fal.py`) - verified against fal.ai's own
`seedance-2.0-api` repository schema (request params, pricing, resolution/
duration/aspect-ratio options) rather than assumed. Chosen over Standard:
the only capability difference is a 1080p ceiling (Fast tops out at
720p) at a higher flat per-second rate ($0.3024/s vs. Fast's $0.2419/s) -
not something a motion/progression benchmark needs, so Fast is the right
call rather than paying for a resolution ceiling this test doesn't use.
Audio (`generate_audio: true`) is left on because fal.ai's documented
pricing does not change whether audio is requested or not.

This is also the first candidate under a genuinely different fal.ai owner
(`bytedance`, not `fal-ai`) - a real test of whether the owner/alias-only
queue-routing rule (verified for Wan, then confirmed for Kling/Veo) holds
for a different vendor entirely, not just a new alias under the same
owner. `FalVideoProvider.get_job_status()`'s preference for the
server-returned `status_url`/`response_url` (the fix from the original
Wan 405 bugs) is what actually matters in practice here - the owner/alias
reconstruction is only ever a fallback.

**Source image: reused, $0 cost.** `data/fal_mechanical_start_test/mechanical_start_frame.jpg` -
the most refined approved frame available (correct composition *and*
corrected saw mechanics layered on top of it) - read from its own
manifest.json, same reuse pattern as every prior script. This benchmark
makes **no image call at all**.

**Exactly 1 video call:**
- Duration 8s, resolution 720p, aspect ratio 9:16.
- Total cost ($1.9352 estimated: $0.2419/s x 8s) checked against the
  $2.30 cap before the call; one `yes` confirmation gates it.
- No retries, no alternate model, no additional generations of any kind.
- `manifest.json` records the prompt, model, duration, resolution, job id,
  status/response URLs, cost, and output path.

```bash
python -m scripts.run_seedance_benchmark_test
python -m scripts.run_seedance_benchmark_test --yes
```

Outputs land in `data/fal_seedance_benchmark_test/` (gitignored):
`seedance_benchmark.mp4`, `manifest.json`. Verified entirely offline: a
mocked-transport dry run confirms no image-generation endpoint is ever
touched, exactly one submission happens, the payload matches the
documented schema (`image_url`, `resolution: "720p"`, `duration: "8"`,
`generate_audio: true`, `aspect_ratio: "9:16"`), queue routing resolves to
`bytedance/seedance-2.0` (owner/alias only), and the cost lands at exactly
$1.9352.

## Running the Wan Turbo cost-down timelapse test (spends real money - max $0.05)

Once the Seedance benchmark established a quality ceiling, the natural
next question is: how much of that feel survives at roughly 1/40th the
cost, on the model we already use as the cheap production baseline?
`scripts/run_wan_turbo_timelapse_test.py` reuses the same source image and
creative goal as the Seedance benchmark, optimized for Wan Turbo's actual
strengths rather than a scaled-down copy of the Seedance prompt - broad,
visible construction progression (carrying lumber, adding studs/bracing,
the cabin getting denser) instead of demanding precise continuous tool
physics.

**Re-verified before writing this script** (the request was explicit: do
not assume old research still holds): the Turbo endpoint's duration is
governed by `num_frames`, 81-100 inclusive, default 81 (~5.06s @ 16fps) -
counts above 81 bill at a 1.25x multiplier. **15 seconds is not achievable
on this endpoint at any price** - the absolute ceiling is 100 frames
(~6.25s), and even that costs more than the flat $0.05 rate. So this
experiment targets the closest valid alternative: ~5 seconds (81 frames),
pinned explicitly via `WAN_TURBO.extra_payload["num_frames"] = 81` (see
`app/providers/video/fal.py`) rather than left to the API's own default -
this also corrects an earlier project assumption of a fixed ~4s/65-frame
output (see "Cost model" above). Also re-verified: this endpoint has no
native audio parameter (Wan's audio-capable sibling is a separate
Speech-to-Video model requiring an input audio file - a different
capability) - no audio is requested here; SFX stays a future editing-
pipeline concern.

**Exactly 1 video call, $0 image cost (source reused):**
- Total cost ($0.05 - flat, deterministic, no per-second variability)
  checked against the $0.05 cap before the call; one `yes` confirmation
  gates it.
- No retries, no alternate model, no additional generations.
- `manifest.json` records the prompt, model, resolution, frame count,
  cost, job id, and output path.

```bash
python -m scripts.run_wan_turbo_timelapse_test
python -m scripts.run_wan_turbo_timelapse_test --yes
```

Outputs land in `data/fal_wan_turbo_timelapse_test/` (gitignored):
`wan_turbo_timelapse.mp4`, `manifest.json`. Verified entirely offline: a
mocked-transport dry run confirms no image-generation endpoint is ever
touched, exactly one submission happens, the payload carries
`num_frames: 81` (pinned, not the bare API default), `resolution: "480p"`,
no audio field, and the prompt favors broad progression language over
fine tool-mechanics language - and the cost lands at exactly $0.05.

## Running the Wan Turbo 2-clip timelapse test (spends real money - max $0.10)

Since the $0.05 Turbo endpoint can't produce a single ~10s clip (see
above - its ceiling is ~6.25s and only at a higher 1.25x-multiplier
price), this tests the alternative: **two** $0.05 clips chained into one
~10s sequence, staying strictly on the flat-rate tier throughout.
`scripts/run_wan_turbo_2clip_timelapse_test.py` generates clip 1 from the
approved `mechanical_start_frame.jpg` (same as every prior gate), then
generates clip 2 from **clip 1's own last frame** - extracted locally with
ffmpeg (`app/services/frame_extraction.extract_last_frame`, the same
last-frame-propagation mechanism proven in the original 3-shot continuity
experiment), not a new image generation. This is what makes clip 2 a
continuation of clip 1's actual pixels rather than an independently
imagined restart.

Both clips share identical camera/attention/identity language; only the
construction-stage goal differs - clip 1 targets framing progress (lumber
carried/positioned, more studs/bracing), clip 2 explicitly targets a
*later* structural stage (upper framing, roof framing, cross-bracing)
built on top of what clip 1 already established, with the prompt
explicitly forbidding any reset or disappearance of existing structure.

A new small, reusable utility was added for this:
`app/services/video_assembly.concatenate_videos()` - ffmpeg's `concat`
*filter* (re-encodes, robust to minor stream differences between two
separately generated clips, unlike the `concat` demuxer's `-c copy`) -
used here purely to produce one file for human review, not as the
project's real trim-aware assembly system (that's still future work).
Covered by 4 new tests using the same real-ffmpeg-against-a-real-fixture-
clip approach as `frame_extraction`'s own tests.

**Exactly 2 video calls, $0 image cost (clip 1's source reused, clip 2's
source extracted locally):**
- 81 frames, 480p each; total cost $0.10 (two flat, deterministic $0.05
  charges - no per-second variability) checked against the $0.10 cap
  before either call; one `yes` confirmation gates the whole run.
- No retries, no alternate model, no additional generations.
- `manifest.json` records both clips' prompt/cost/job id/output path, the
  extracted mid-sequence frame, and the final concatenated review file.

```bash
python -m scripts.run_wan_turbo_2clip_timelapse_test
python -m scripts.run_wan_turbo_2clip_timelapse_test --yes
```

Requires `ffmpeg` on PATH (for the last-frame extraction and the final
concatenation - same requirement as `run_continuity_test.py`).

Outputs land in `data/fal_wan_turbo_2clip_timelapse_test/` (gitignored):
`clip1.mp4`, `clip1_last_frame.jpg`, `clip2.mp4`, `combined_review.mp4`,
`manifest.json`. Verified entirely offline: a mocked-transport dry run -
using the *real* committed fixture clip's bytes as the fake download
response, so the ffmpeg steps run against a genuinely valid video, not
fake garbage - confirms no image-generation endpoint is ever touched,
exactly two submissions happen, clip 2's source is the path ffmpeg
actually extracted from clip 1 (not the original mechanical start frame
reused again), and the total cost lands at exactly $0.10.

## Running the Wan Turbo 2-clip 720p test (spends real money - max $0.20)

A deliberately controlled, single-variable comparison against the 480p
test above: same source image, same two-clip structure, same last-frame
propagation, same prompts - **only resolution changes, 480p -> 720p**
($0.05 -> $0.10 per clip). The question it answers: does paying double
per clip buy enough visible improvement to make 720p (not 480p) the
high-volume production tier - not to beat the Seedance benchmark, just to
find the cheapest tier that doesn't read as obviously low-quality inside
a fast-paced final video.

`scripts/run_wan_turbo_2clip_timelapse_720p_test.py` imports
`CLIP_1_PROMPT`/`CLIP_2_PROMPT` directly from
`scripts/run_wan_turbo_2clip_timelapse_test.py` (the 480p script) rather
than retyping them - a controlled comparison would be undermined by even
a small copy-paste drift between the two prompt sets, so byte-identity is
enforced by import, not convention. Re-verified before writing this
script: 720p on this endpoint is $0.10/video flat (matches
`WAN_TURBO.price_by_resolution["720p"]` already in this codebase - no
config change needed), and the `num_frames` pinning (81, ~5.06s) already
established for 480p applies the same way at 720p.

**Exactly 2 video calls, $0 image cost, own dedicated output directory**
(so the 480p results are never overwritten - both stay on disk for direct
side-by-side comparison):
- 81 frames, 720p each; total cost $0.20 (two flat, deterministic $0.10
  charges) checked against the $0.20 cap before either call; one `yes`
  confirmation gates the whole run.
- No retries, no alternate model, no additional generations.

```bash
python -m scripts.run_wan_turbo_2clip_timelapse_720p_test
python -m scripts.run_wan_turbo_2clip_timelapse_720p_test --yes
```

Outputs land in `data/fal_wan_turbo_2clip_720p_timelapse_test/`
(gitignored, separate from the 480p test's own directory): `clip1.mp4`,
`clip1_last_frame.jpg`, `clip2.mp4`, `combined_review.mp4`,
`manifest.json`. Verified entirely offline: a mocked-transport dry run
confirms the imported prompts are byte-identical to the 480p script's own
constants, no image-generation endpoint is touched, exactly two
submissions happen with `resolution: "720p"`, and the total cost lands at
exactly $0.20.

## Running the Wan 3.0 15s timelapse test (spends real money - max $0.75)

A cost-down candidate for one *continuous* ~15s generation with the same
accelerated-montage feel as the successful Seedance 2.0 Fast benchmark -
explicitly NOT modeled on either Wan Turbo test, which were the wrong
creative format (slow, continuous, glitch-prone). `scripts/run_wan3_15s_timelapse_test.py`
imports `BENCHMARK_PROMPT` directly from `scripts/run_seedance_benchmark_test.py`
(not retyped) as the base camera/attention/style language, then extends
it with an explicit multi-stage montage structure for 15s of *more*
progression, not the same amount paced more slowly - natural jump/cut-
like shifts between construction stages are called out as desirable, not
a flaw to avoid.

**Model: `WAN_3_0_STANDARD`** (`alibaba/wan-3.0/image-to-video`, 480p) -
a third distinct fal.ai owner (`alibaba`, after `fal-ai` and `bytedance`),
confirming queue routing generalizes across vendors. Verification here
was **partial before the first real attempt**: endpoint path, 2-30s
duration range (comfortably covers 15s), 480p/720p/1080p tiers, 9:16
support, and per-second pricing ($0.05/s at 480p) were cross-confirmed
across multiple fal.ai model-page searches; the exact image-field name
was not (fal.ai itself is unreachable from this sandbox, unlike for
Seedance, which had an actual schema repo to check against).

**That gap surfaced for real, safely, exactly as designed**: the first
live submission was rejected with fal.ai's own HTTP 422 - `"body ->
start_image_url: Field required"` - while the payload sent `image_url`.
No charge occurred; fal.ai validates a request's schema before any
billable work starts. This is now fixed using this project's existing
per-model `image_param_name` mechanism (the same one `KLING_2_6_PRO`
already uses for its own `start_image_url` field) - `WAN_3_0_STANDARD`
now sends `start_image_url`, confirmed by this live 422, not secondhand
research. The `duration`/`resolution`/`aspect_ratio` fields were not
flagged as errors in that same 422, so they're now believed correct -
though a 422 only confirms what's wrong, not everything that's right, so
this remains slightly less certain than a fully successful call would
make it. The audio-field question remains genuinely unresolved and is
still deliberately omitted from the payload for the same reason as
before - it fails the same safe way (immediate 4xx, no charge) if wrong.

**Exactly 1 video call, $0 image cost (source reused):**
- 480p, 15s, 9:16. Hard cap is set **exactly equal to the computed
  estimate** ($0.75, $0.05/s x 15s) - zero margin, per instruction, since
  this is a deterministic per-second rate with a fixed duration.
- No retries, no alternate model, no additional generations.
- `manifest.json` records the prompt, model, resolution, duration, cost,
  job id, and output path.

```bash
python -m scripts.run_wan3_15s_timelapse_test
python -m scripts.run_wan3_15s_timelapse_test --yes
```

Outputs land in `data/fal_wan3_15s_timelapse_test/` (gitignored):
`wan3_15s_timelapse.mp4`, `manifest.json`. Verified entirely offline: a
mocked-transport dry run confirms no image-generation or other-model
endpoint is ever touched, exactly one submission happens, the payload
matches the best-verified schema (`duration: 15` as a bare int, no audio
field present under any of the candidate names, `resolution: "480p"`,
`aspect_ratio: "9:16"`), the prompt contains both the imported Seedance
benchmark language and the 15s multi-stage extension, queue routing
resolves to `alibaba/wan-3.0` (owner/alias only), and the cost lands at
exactly $0.75.

**Result: ran for real, PASSED technically, FAILED creatively.** Visual
quality was good enough and the corrected `start_image_url` field worked
(see below), but construction read as continuous and too slow -
not the extreme, hard-cut timelapse feel of the liked Seedance benchmark.
Root cause suspected: importing the Seedance prompt's own phrasing
("works continuously and rapidly," "moves quickly but plausibly between
tasks") plausibly nudged the model toward one continuous action instead
of discontinuous time-lapse jumps. See "Running the Wan 3.0 15s timelapse
test V2" below for the fix.

### The real schema bug this test found

The first live submission was rejected with fal.ai's own HTTP 422 -
`"body -> start_image_url: Field required"` - while the payload sent
`image_url`. No charge occurred; fal.ai validates a request's schema
before any billable work starts. Fixed via the existing per-model
`image_param_name` mechanism (the same one `KLING_2_6_PRO` already uses
for its own `start_image_url` field) - confirmed by a real error, not
secondhand research. `duration`/`resolution`/`aspect_ratio` were not
flagged as errors in that same 422, so they're now believed correct.

## Running the Wan 3.0 15s timelapse test V2 (spends real money - max $0.75)

V1 succeeded technically but failed the central creative requirement:
the construction read as slow and continuous, not an extreme time-lapse.
`scripts/run_wan3_15s_timelapse_v2_test.py` keeps every technical
parameter from V1 identical (model, 480p, 15s, 9:16, source image,
`start_image_url`, no audio field, $0.75) and changes **only the
prompt** - rewritten from scratch rather than appended to V1's
Seedance-derived prompt, since that base prompt's own phrasing is the
suspected cause of the pacing problem.

The new prompt is built around ~6 explicit "HARD TIME JUMP" transitions
across the 15s (sparse framing -> many more studs already exist -> walls
substantially framed -> upper beams/header -> roof framing appears ->
roof substantially developed -> dramatically more complete cabin), with
only brief activity bursts described between jumps rather than
continuous work, and an explicit "NOT continuous real-time footage"
framing up front.

**Exactly 1 video call, $0 image cost, own dedicated output directory**
(V1's result is never overwritten):
- Hard cap set exactly equal to the computed estimate ($0.75) - no
  margin, same as V1.
- No retries, no alternate model, no additional generations.

```bash
python -m scripts.run_wan3_15s_timelapse_v2_test
python -m scripts.run_wan3_15s_timelapse_v2_test --yes
```

Outputs land in `data/fal_wan3_15s_timelapse_v2_test/` (gitignored):
`wan3_15s_timelapse_v2.mp4`, `manifest.json`. Verified entirely offline:
a mocked-transport dry run confirms no image-generation or other-model
endpoint is ever touched, exactly one submission happens with the
confirmed-correct `start_image_url` field (no `image_url`), the prompt
contains the new hard-time-jump language and explicitly does NOT contain
the V1/Seedance phrases suspected of causing the continuous-motion
pacing problem, and the cost lands at exactly $0.75.

## Running the cross-angle continuity test (spends real money - max $0.30)

With Wan 3.0 V2 validated as the core generation approach, planning has
moved to the first full ~65-70s production video, using 6 different stable
camera positions across 6 segments. Last-frame propagation (the mechanism
that keeps continuity between clips *at a fixed camera angle*) cannot
itself change the camera position - a fresh reference image must be
generated for every angle change, conditioned on a shared "continuity
bible" text description plus an angle-specific framing clause. Before
generating any video for the full production, this test isolates and
checks that mechanism on its own: can two independently generated still
images, shot from two clearly different camera angles, convincingly depict
the same builder, same cabin, same construction state, and same
ocean-cliff location?

`scripts/run_cross_angle_continuity_test.py` makes **exactly 2** Nano
Banana Pro Generate calls (`fal-ai/nano-banana-pro`, text-to-image, no
source/reference image for either call - both are fresh generations), each
built from the identical continuity-bible text plus a different
camera-angle clause. No video call is made. For this test, continuity is
deliberately prioritized over beauty: both prompts over-specify shared
landmarks (a distinctive boulder, cabin dimensions, framing state, ocean
orientation, lighting) precisely so they can be directly checked against
each other afterward.

**Continuity bible** (identical text in both prompts):

> A rugged male builder in his mid-40s, with slightly messy dark brown
> hair, a short dark beard/stubble, and a medium athletic build, wearing
> worn faded blue-grey jeans, a plain heather-grey crew-neck work shirt
> with no visible logo or branding, and brown leather work boots. He is
> building a small single-story timber cabin under construction on a flat
> rocky clifftop clearing. The cabin has a rectangular footprint roughly 5
> meters wide by 4 meters deep, with eaves about 1.5 times the builder's
> standing height. The timber floor deck is fully complete and level. Wall
> framing is already built on two adjacent sides - one landward-facing
> side and one side-facing wall - using evenly spaced raw, unfinished,
> pale-yellow structural timber studs. The third side, facing the ocean,
> is completely open with no framing at all. There is no roof yet and no
> windows or doors yet. The clifftop clearing is roughly triangular,
> narrowing toward the cliff edge, which drops sharply about 8-10 meters
> beyond the open ocean-facing side of the cabin; the ocean and horizon are
> visible directly beyond that open side. A distinctive large flat grey
> boulder sits near the rear corner of the platform, on the same side as
> the landward-facing framed wall. Sparse wind-bent low shrubs and scrub
> grass line the cliff edge, and a narrow dirt access path approaches from
> the landward side. The lighting is warm, low-angle, late-afternoon
> golden hour sunlight coming from the landward side of the cabin, casting
> long soft shadows. Candid documentary/observational photography style,
> vertical 9:16 aspect ratio.

**Image 1 angle clause** (wide three-quarter-rear):

> Camera view: a wide three-quarter-rear observational angle, positioned
> behind and to one side of the builder, looking past him toward the open
> ocean-facing side of the structure - the shot shows the timber floor
> deck, both framed walls, the open ocean-facing side, the large flat grey
> boulder near the rear corner on the builder's side of the frame, and the
> ocean and cliff edge beyond. The builder is working naturally - handling
> a length of timber near the wall framing, his weight engaged in the task
> - facing away from the camera and never looking toward it. No posing, no
> presenter stance, no eye contact with the camera.

**Image 2 angle clause** (opposite-side three-quarter):

> Camera view: an opposite-side three-quarter observational angle -
> positioned on the OTHER side of the structure from a companion shot,
> roughly diagonally across the platform from that position, looking
> across the floor deck toward the framed walls from this new direction.
> The shot still shows the open ocean-facing side and the ocean and cliff
> edge beyond, with the large flat grey boulder now appearing on the
> opposite side of the frame compared to a three-quarter-rear view,
> consistent with the camera having moved around to the other side of the
> same site. The builder is working naturally on the wall framing, body
> oriented toward his work, never looking toward the camera. No posing, no
> presenter stance, no eye contact with the camera.

```bash
python -m scripts.run_cross_angle_continuity_test
python -m scripts.run_cross_angle_continuity_test --yes
```

Outputs land in `data/fal_cross_angle_continuity_test/` (gitignored):
`angle_1_wide_three_quarter_rear.jpg`, `angle_2_opposite_three_quarter.jpg`,
`manifest.json`. Exactly 2 calls, $0.15 each, $0.30 total = the hard cap
with zero margin (flat per-image billing makes this exactly precomputable).
Verified entirely offline: a mocked-transport dry run confirms Nano Banana
Pro Generate's endpoint is synchronous (`https://fal.run/fal-ai/nano-banana-pro`,
not the queue-based flow the video providers use, and no reference-image
upload happens for either call), that no `/edit` or video/other-image-model
endpoint is ever touched, that exactly 2 submissions are made (not 1, not
3+), that both payloads use the `aspect_ratio`/`resolution` shape (not
`image_size`), that both prompts start with the byte-identical continuity
bible and differ only in their angle clause, and that the total cost lands
at exactly $0.30.

After generation, compare the two images on: builder identity/clothing,
cabin dimensions, framing geometry, door/window positions, ocean direction,
cliff/terrain geometry, recognizable landmarks (the boulder, access path,
shrubs), lighting, and overall impression - would a viewer immediately
believe these are two cameras filming the same construction project? This
script does not generate any video; it stops after the two images so they
can be manually reviewed before any segment of the full production video is
attempted.

## Running the full video segment 1A test (spends real money - max $0.45)

First of 7 segments in Full Video #1's production plan (see "What's next"
above for the full spec). `scripts/run_full_video_segment_1a_test.py`
covers the opening: the first ~1.5-2s hold on the completely untouched
clifftop site, then the builder clears brush/scrub through several hard
time-lapse jumps, ending on a fully cleared but still entirely unbuilt
site. This is the ONLY segment this script builds - 1B and every later
segment are separate scripts, each built and approved only after the
previous one is reviewed.

Makes exactly 2 calls, same "reference image, then video from it" pattern
as `scripts/run_first_fal_test.py`: 1 Nano Banana Pro Generate still image
(the segment's start-frame reference, no source image), then 1 Wan 3.0
standard video (image-to-video, 480p, 9:16, 6s) generated from it. The
video model uses a local `dataclasses.replace()` copy of
`WAN_3_0_STANDARD` with `extra_payload={"duration": 6}` - the shared
module-level config (still used at `duration=15` by the earlier 15s
timelapse tests) is never mutated.

Between the two calls sits a **mandatory manual review gate**: after the
image is generated, the script prints its path and stops, requiring a
separate "type yes" before submitting the $0.30 video job. This gate is
NOT skippable by `--yes` (`--yes` only skips the upfront cost
confirmation) - its purpose is to let you actually judge the generated
image before spending on video from it, rather than trusting the video
call to fire automatically regardless of what the image looks like.

**Site continuity bible** (fixed text, shared verbatim across all 7
segments' reference-image prompts - only a build-state clause and a
camera clause change per segment):

> A rugged male builder in his mid-40s, with slightly messy dark brown hair, a short dark beard/stubble, and a medium athletic build, wearing worn faded blue-grey jeans, a plain heather-grey crew-neck work shirt with no visible logo or branding, and brown leather work boots, working on a flat rocky clifftop clearing. The clearing is roughly triangular, narrowing toward a cliff edge that drops sharply 8-10 meters to the ocean; the ocean and horizon are visible beyond the site. A distinctive large flat grey boulder sits near the rear/landward corner of the clearing. Sparse wind-bent low shrubs and scrub grass line the cliff edge, with a narrow dirt access path from the landward side. Warm, low-angle, late-afternoon golden-hour sunlight from the landward side, long soft shadows. Candid documentary/observational photography style, vertical 9:16.

**Segment 1A build states** (S0 = this segment's start, used in the
reference-image prompt; S0.5 = this segment's end, handed off byte-
identical as segment 1B's own start-state text when that script is built):

> S0: Current construction state: the clifftop clearing is completely untouched - natural rocky ground with low brush, small shrubs, loose rock, and some scattered debris across the site. There is no cabin structure of any kind, no framing, no stakes, no materials, and no tools laid out beyond what the builder is personally carrying.
>
> S0.5: Current construction state: the clearing has been fully cut back and is now visibly bare - brush, scrub, and debris removed, exposed ground across the whole working area. It is still completely unbuilt: no stakes, no footprint markings, no materials staged, and no structure of any kind yet.

**Camera clause** (wide environmental, shared by 1A and 1B): "a wide
environmental angle, pulled back and slightly elevated, taking in the
whole clifftop clearing - the ocean and cliff edge beyond, the distinctive
flat grey boulder near the rear corner, and the sparse shrubs along the
edge - with the builder positioned within this wide view rather than
filling the frame."

**Video prompt**: built on the validated Wan 3.0 V2 hard-time-jump
structure - explicitly holds on the untouched site for the first 1.5-2s,
then 3 "HARD TIME JUMP" beats through brush-cutting to a fully cleared
site, with the builder moving ~25-30% faster than typical real-time work,
alive environment (ocean/wind/clouds), and forward-only progress language.

```bash
python -m scripts.run_full_video_segment_1a_test
python -m scripts.run_full_video_segment_1a_test --yes
```

Outputs land in `data/fal_full_video_segment_1a/` (gitignored):
`segment_1a_start_frame.jpg`, `segment_1a.mp4`, `manifest.json`,
`last_job.json` (job state for `recover_fal_video_job.py`, same pattern as
every other real-call script here). Exactly 1 image ($0.15) + 1 video (6s
@ $0.05/s = $0.30) = $0.45 total = the hard cap with zero margin. Verified
entirely offline: a mocked-transport dry run confirms the image call is
synchronous with no source image, the video call uploads that exact image
and submits with `start_image_url` (not `image_url`), `duration=6` as a
bare int (proving the local per-segment config variant is actually used,
NOT the shared module-level config's `duration=15`), no audio field,
correct resolution/aspect ratio, the video prompt contains the segment's
hard-time-jump and "first 1.5-2 seconds" language, exactly 1 call to each
endpoint, a total cost of exactly $0.45, and that the manual review gate
fires exactly once between the two calls even when `--yes` is passed. The
shared `WAN_3_0_STANDARD`
config is asserted unchanged (`duration=15`) both before and after the
run.

## Running the segment 1A image V2 candidate test (spends real money - max $0.15)

The original segment 1A start frame was rejected at the manual review gate:
the camera was pitched too far downward, so foreground ground/vegetation
dominated the frame while the ocean/cliff environment was compressed into
the upper background - a real problem for FORMA's visual identity, which
needs the dramatic environment to be a major retention element, not
background scenery. `scripts/run_full_video_segment_1a_image_v2_test.py`
fixes ONLY the camera/composition clause; builder identity, site geometry,
lighting, and the S0 untouched-construction-state text are imported
directly from `run_full_video_segment_1a_test.py` (`SITE_BIBLE`,
`SEGMENT_1A_START_STATE_S0`), byte-identical, not retyped.

**New composition clause:**

> Camera view: a wide environmental establishing shot taken from approximately human chest/eye height, with the camera axis close to horizontal rather than elevated and angled downward. The horizon is clearly visible. Roughly the upper 40-50% of the frame showcases the dramatic coastal landscape - open ocean, horizon, sky, and, where composition permits, glimpses of distant coastline or cliff geography rather than only open water. The remaining lower portion of the frame contains the builder and the untouched worksite, with enough foreground ground and vegetation visible to clearly read as material that will be cleared; the builder occupies a noticeably smaller portion of the frame than in a close or elevated shot, positioned further back within the scene rather than filling it. The composition shows clear depth from front to back: foreground worksite, then the builder, then the cliff edge and coastline, then the ocean and horizon beyond. Candid, fixed-camera construction-documentary feeling, not a posed or hero composition.

Plus a builder-action clause: naturally preparing a brush-cutter, gaze
toward the work area, never toward the camera, no posing.

Makes exactly ONE Nano Banana Pro Generate call ($0.15, no source image,
same as `run_composition_test.py`). No video call.

```bash
python -m scripts.run_full_video_segment_1a_image_v2_test
python -m scripts.run_full_video_segment_1a_image_v2_test --yes
```

Saves to a **new candidate path** in `data/fal_full_video_segment_1a/`:
`segment_1a_start_frame_v2_candidate.jpg` and its own
`candidate_v2_manifest.json` - the original (rejected)
`segment_1a_start_frame.jpg` and the segment's main `manifest.json` are
both left completely untouched. Verified entirely offline: a mocked-
transport dry run confirms exactly 1 call, no video/edit endpoint ever
touched, the prompt starts with the byte-identical site bible + S0 state,
contains every new composition requirement, does NOT contain the old
rejected downward-pitch language, the original image file's bytes and
mtime are unchanged after the run, and cost is exactly $0.15.

## Running the full video segment 1B test (spends real money - max $0.55)

Segment 1A is approved and locked. `scripts/run_full_video_segment_1b_test.py`
builds and runs Segment 1B ONLY - Segment 2 and everything after it are
separate scripts, built after this one's result is reviewed. Same
2-call, image-then-video pattern as Segment 1A, including the mandatory
image-review gate.

**Start state** (imported byte-identical from
`SEGMENT_1A_END_STATE_S0_5`, Segment 1A's own hand-off text):

> Current construction state: the clearing has been fully cut back and is now visibly bare - brush, scrub, and debris removed, exposed ground across the whole working area. It is still completely unbuilt: no stakes, no footprint markings, no materials staged, and no structure of any kind yet.

**End state (S1)**:

> Current construction state: string lines and stakes mark the building footprint, with foundation piers set at the corners. Stacks of raw timber, a tool case, and a circular saw are staged beside the footprint. Most of the floor joist system is now installed, running parallel across nearly the entire footprint with only one or two gaps remaining - the beginning of a timber floor structure is clearly visible. There is still no floor decking, no wall framing, no roof, and no windows or doors.

**Camera** (carries forward Segment 1A's approved V2 visual language, at a
somewhat closer scale): chest/eye height, near-horizontal axis, horizon
clearly visible, ocean/horizon/coastline occupying ~30-40% of the frame,
front-to-back depth preserved (foreground worksite -> builder ->
cliff/coast -> ocean/horizon).

**Video prompt's hard-time-jump sequence** (4 distinct beats, not
repeated "more joists" shots): footprint marked with stakes/string ->
foundation piers + materials staged -> first floor joists appear -> most
of the joist system installed (only 1-2 gaps left). Varied, non-lingering
builder activity between jumps: hammering a stake, carrying timber,
positioning a joist, fastening with an impact driver.

```bash
python -m scripts.run_full_video_segment_1b_test
python -m scripts.run_full_video_segment_1b_test --yes   (skips only the upfront cost confirmation - the image review gate always runs)
```

Model settings: Nano Banana Pro Generate (image, $0.15) then Wan 3.0
standard 480p, 9:16, **8 seconds** (a new local `dataclasses.replace()`
variant, `WAN_3_0_SEGMENT_1B`, `extra_payload={"duration": 8}` - touching
neither the shared module-level config nor Segment 1A's own duration=6
variant), `start_image_url`, no audio field. $0.15 + $0.40 (8s @
$0.05/s) = **$0.55 total, hard cap with zero margin**.

Outputs land in `data/fal_full_video_segment_1b/` (gitignored):
`segment_1b_start_frame.jpg`, `segment_1b.mp4`, `manifest.json`,
`last_job.json`. Verified entirely offline: a mocked-transport dry run
confirms exactly 1 call to each endpoint, the image prompt starts with
the byte-identical site bible + Segment 1A's S0.5 end state, the video
payload uses `start_image_url`/bare-int `duration=8`/no audio field, the
prompt contains all 4 distinct jump stages plus the preserved "no wall
framing, no roof, and no windows or doors" S1 constraint, the
environment-forward camera language, the review gate fires exactly once
and is not skippable by `--yes`, Segment 1A's own config
(`WAN_3_0_SEGMENT_1A`, duration=6) and the shared `WAN_3_0_STANDARD`
(duration=15) are both asserted unchanged, and total cost is exactly
$0.55.

## Running the segment 1B resume-video test (spends real money - max $0.40)

The user exited at the mandatory review gate after Segment 1B's $0.15
image call, then separately approved and locked
`segment_1b_start_frame.jpg` as the canonical Segment 1B starting image.
`scripts/run_full_video_segment_1b_resume_video_test.py` makes ONLY the
remaining Wan 3.0 video call from that exact image - no Nano Banana Pro
call, no regeneration. The video prompt is imported directly from
`run_full_video_segment_1b_test` (`VIDEO_PROMPT`) and used **completely
unchanged** - unlike segment 1A's resume, no emphasis sentence is added
here, since the prompt was approved as-is.

```bash
python -m scripts.run_full_video_segment_1b_resume_video_test
python -m scripts.run_full_video_segment_1b_resume_video_test --yes
```

Validates against the segment's own `manifest.json` (written by the
image step before the review gate) - confirms its `image_path` matches
the locked image, that the image was actually generated, and that no
video is already recorded for this segment (no accidental double-spend) -
then updates that same manifest in place with the video result. $0.40 =
the hard cap with zero margin (8s @ $0.05/s, exactly precomputable).
Verified entirely offline: a mocked-transport dry run seeds a fake
pre-existing manifest.json + approved image, confirms no image-generation
endpoint is ever touched, exactly 1 video call with the correct payload
shape (`start_image_url`, bare-int `duration=8`, no audio field), the
prompt byte-identical to the approved `VIDEO_PROMPT` (all 4 distinct jump
stages and the "no floor decking, no wall framing, no roof, and no
windows or doors" constraint intact), cost exactly $0.40, and the
manifest updated correctly (image fields preserved, video fields newly
populated).

## Running the full video segment 2 test (spends real money - max $0.75)

Segment 1B's real footage was reviewed: its actual appearance reads as a
much smaller starter platform (~3m x 3m relative to the builder) than its
own prompt implied. `scripts/run_full_video_segment_2_test.py` treats that
ACTUAL appearance as the continuity truth (a new standing rule - see
"What's next" above) rather than importing `SEGMENT_1B_END_STATE_S1`
verbatim, and is entirely one transformation: that small platform expands
on-camera into a substantially larger ~10m x 6m floor structure, several
times its original size, with the original platform staying visually
recognizable throughout - never magically swapped for a bigger one
between cuts. No wall framing begins here; the completed floor platform,
held clean for the segment's final ~1.5-2s, is this segment's own payoff.

**Start state** (corrected to the actual Segment 1B footage, not its
prompt text):

> Current construction state (matching the actual generated appearance, not the original prompt's stated dimensions): a small, compact starter floor platform - roughly 3 meters by 3 meters relative to the builder's scale - sits on foundation piers, with a dense grid of floor joists already installed across it. Stacks of raw timber, a tool case, and a circular saw remain staged beside it. There is still no floor decking, no wall framing, no roof, and no windows or doors.

**End state (S2)** - the new canonical ~10m x 6m footprint, locked from
here onward for every future segment:

> Current construction state: the original small starter platform is fully incorporated into a single, substantially larger floor structure, its foundation piers, perimeter beams, and joist grid now spanning roughly 10 meters wide by 6 meters deep - several times larger than the original starter platform, which remains recognizable as one section within it. The builder appears noticeably small relative to the completed floor platform. There is still no floor decking, no wall framing, no roof, and no windows or doors.

**Camera** - first real implementation of the camera-variation rule:

> Camera view: a substantially different observational angle from previous segments - positioned on the opposite side of the site, at a natural vantage point slightly higher than the platform, but with the camera axis kept near-horizontal rather than tilted downward. This reveals a fresh sweep of coastline, ocean, and cliff geography not yet shown, occupying a clearly major share of the frame alongside the structure - never a downward-looking construction shot. From this angle the small starter platform and the full extent of its expansion are both legible, with the builder appearing small against the completed floor structure and the surrounding landscape alike. Candid, fixed-camera construction-documentary feeling, not a posed or hero composition.

**Video prompt structure**: opening 1.5-2s hold on the small platform as
it actually appears, 4 distinct HARD TIME JUMP beats (new piers farther
out -> perimeter beams establish the larger outline -> new joists extend
outward from and integrate the original platform -> additional joists
fill the expanded area), then a closing 1.5-2s hold on the completed
~10m x 6m structure with the builder reading as noticeably small against
it. No wall-framing language anywhere in this segment - that's segment 3's
payoff.

```bash
python -m scripts.run_full_video_segment_2_test
python -m scripts.run_full_video_segment_2_test --yes   (skips only the upfront cost confirmation - the image review gate always runs)
```

Model settings: Nano Banana Pro Generate (image, $0.15) then Wan 3.0
standard 480p, 9:16, **12 seconds** (`WAN_3_0_SEGMENT_2`, a new local
`dataclasses.replace()` variant, `extra_payload={"duration": 12}` -
touching neither the shared module-level config nor any earlier segment's
own duration variant), `start_image_url`, no audio field. $0.15 + $0.60
(12s @ $0.05/s) = **$0.75 total, hard cap with zero margin**.

Outputs land in `data/fal_full_video_segment_2/` (gitignored):
`segment_2_start_frame.jpg`, `segment_2.mp4`, `manifest.json`,
`last_job.json`. Verified entirely offline: a mocked-transport dry run
confirms exactly 1 call to each endpoint, the image prompt starts with
the byte-identical site bible + the corrected ~3x3m start state (and does
NOT yet claim the 10x6m target on the start frame), the video payload
uses `start_image_url`/bare-int `duration=12`/no audio field, the prompt
contains the opening hold, all 4 distinct expansion beats, the closing
hold on the completed structure, explicitly does NOT contain any
wall-framing-begins language, still preserves "no floor decking, no wall
framing, no roof, and no windows or doors" at the very end, the review
gate fires exactly once and is not skippable by `--yes`, every earlier
segment's own config (`WAN_3_0_SEGMENT_1A` duration=6,
`WAN_3_0_SEGMENT_1B` duration=8) and the shared `WAN_3_0_STANDARD`
(duration=15) are all asserted unchanged, and total cost is exactly
$0.75.

## Running the segment 2 resume-video test (spends real money - max $0.60)

The user exited at Segment 2's mandatory review gate after the $0.15
image call, then separately approved and locked
`segment_2_start_frame.jpg`, along with a scale correction: the visible
platform in that approved image - not absolute meter dimensions - is now
the visual source of truth. `scripts/run_full_video_segment_2_resume_video_test.py`
makes ONLY the remaining Wan 3.0 video call from that exact image (no
Nano Banana Pro call), with a **revised** video prompt: every absolute
meter callout from the original script's prompt ("roughly 3 meters by 3
meters", "roughly 10 meters wide by 6 meters deep") is replaced with
framing relative to the actual approved image - approximately 2x width
and 2x depth, ~4x floor area, explicitly proportionate rather than
site-consuming. The camera clause, opening/closing holds, 4-beat
hard-time-jump structure, and the "no floor decking, no wall framing, no
roof, and no windows or doors" end-state constraint are all otherwise
unchanged.

```bash
python -m scripts.run_full_video_segment_2_resume_video_test
python -m scripts.run_full_video_segment_2_resume_video_test --yes
```

Validates against the segment's own `manifest.json` (image already
recorded, video not yet) before submitting, then updates it in place -
the manifest's standing `build_state_end` (still recording the project's
~10m x 6m canonical footprint fact for future-segment planning) is left
untouched; only the field recording what prompt was actually sent for
this video call is updated to the revised text. $0.60 = the hard cap with
zero margin (12s @ $0.05/s, exactly precomputable). Verified entirely
offline: a mocked-transport dry run seeds a fake pre-existing
manifest.json + approved image, confirms no image-generation endpoint is
ever touched, exactly 1 video call with the correct payload shape
(`start_image_url`, bare-int `duration=12`, no audio field), the prompt
byte-identical to `VIDEO_PROMPT_RESUME` with the opening/closing holds and
all 4 jump beats intact, the relative-scale language present and every
absolute meter callout confirmed absent, cost exactly $0.60, and the
manifest updated correctly (image fields preserved, `build_state_end`
untouched, video fields newly populated with the revised prompt).

## Running the full video segment 3 test (spends real money - max $0.85)

Segment 2 is approved and locked. `scripts/run_full_video_segment_3_test.py`
is the moment the project transitions from a large open platform into an
actual building - Segment 4 and everything after it are separate scripts,
built only after this one's result is reviewed. This script does not
touch or regenerate Segments 1A, 1B, or 2.

**Start state** (re-describes Segment 2's actual approved appearance
using relative-scale language, not a byte-identical import of Segment 2's
own absolute-meter text - the same one-time-deviation pattern used going
into Segment 2 itself):

> Current construction state: the joist platform now spans approximately twice the width and twice the depth of the original starter section (matching the actual appearance confirmed in the approved Segment 2 footage) - fully continuous and dense, sitting on its foundation piers and perimeter beams. There is still no floor decking, no wall framing, no roof, and no windows or doors.

**End state (S3)** - every stud is a normal full-height stud; the second
wall's progress is horizontal extent only, never partial stud height:

> Current construction state: floor decking now fully covers the expanded platform. The near-side wall is completely framed at full height, from end to end. On one adjacent side wall, a substantial horizontal portion has been framed at the same full stud height, while the remainder of that wall's length is not yet framed - progress on this second wall is represented by how much of its length is built, not by partial stud height. The ocean-facing side of the platform remains predominantly open. The cabin's volume is clearly recognizable as a building skeleton. There is still no roof framing, no roof sheathing, no exterior siding, no installed windows, no installed doors, and no interior finishes.

**Camera** - a fresh angle, different from every prior segment, with an
explicit scale-preservation instruction:

> Camera view: a fresh three-quarter diagonal angle, different from Segment 2's - positioned near one corner of the expanded platform, looking diagonally down its long axis toward the open ocean-facing side, so the full length of the platform recedes toward the coastline. This reveals a different beautiful sweep of cliff and coastline not yet shown from this vantage. The near-side wall framing rises along one side of the frame rather than blocking the view - the ocean, horizon, and cliff geography remain clearly visible beside and beyond the rising structure, never obscured by it. The full extent of the platform stays visible so its increased scale relative to the builder remains obvious. This new camera angle must preserve the platform's actual established scale from the previous segment - the platform must read as the same large, substantially expanded structure already shown, never smaller or reduced in size merely because the camera position changed. Candid, fixed-camera construction-documentary feeling, not a posed or hero composition.

**Hard-time-jump sequence** (opening hold + 4 beats + closing hold): the
platform as-is -> decking rapidly fills it -> first wall plates/studs
appear -> the near-side wall becomes completely framed at full height,
end to end -> a substantial horizontal portion of the adjacent wall
framed at that same full height -> a clean closing hold on the skeleton.

```bash
python -m scripts.run_full_video_segment_3_test
python -m scripts.run_full_video_segment_3_test --yes   (skips only the upfront cost confirmation - the image review gate always runs)
```

Model settings: Nano Banana Pro Generate (image, $0.15) then Wan 3.0
standard 480p, 9:16, **14 seconds** (`WAN_3_0_SEGMENT_3`, a new local
`dataclasses.replace()` variant, `extra_payload={"duration": 14}` -
touching neither the shared module-level config nor any earlier
segment's own duration variant), `start_image_url`, no audio field. $0.15
+ $0.70 (14s @ $0.05/s) = **$0.85 total, hard cap with zero margin**.

Outputs land in `data/fal_full_video_segment_3/` (gitignored):
`segment_3_start_frame.jpg`, `segment_3.mp4`, `manifest.json`,
`last_job.json`. Verified entirely offline: a mocked-transport dry run
confirms exactly 1 call to each endpoint, the image prompt starts with
the byte-identical site bible + the relative-scale start state and
includes the scale-preservation instruction, the video payload uses
`start_image_url`/bare-int `duration=14`/no audio field, the prompt
contains the opening hold, all 4 distinct jump beats, the closing hold,
the "ocean-facing side... predominantly open" constraint, explicitly does
NOT contain "several studs high" anywhere (in either the live prompts or
the manifest's own recorded build-state text), the review gate fires
exactly once and is not skippable by `--yes`, every earlier segment's own
config (`WAN_3_0_SEGMENT_1A` duration=6, `WAN_3_0_SEGMENT_1B` duration=8,
`WAN_3_0_SEGMENT_2` duration=12) and the shared `WAN_3_0_STANDARD`
(duration=15) are all asserted unchanged, and total cost is exactly
$0.85.

## Running the causal action test (spends real money - max $0.50)

Segment 3 production is stopped pending this validation. Reviewing the
real Segment 3 output exposed two fundamental pipeline problems (see
"What's next" above): text-only continuity between segments isn't real
visual conditioning, and packing several "HARD TIME JUMP" state changes
into one clip disconnects the structure's progress from the builder's
depicted actions. `scripts/run_causal_action_test.py` tests the fix for
both, isolated, before any more segment production: real-pixel
conditioning (no text re-anchor) plus one causally simple action (no
time-jump prompting), with time compression deferred entirely to a local
FFmpeg pass afterward.

**Extracted-frame strategy**: `extract_last_frame()` runs locally against
`data/fal_full_video_segment_2/segment_2.mp4` (read-only - the file is
never modified) and saves the result to
`data/fal_causal_action_test/segment_2_real_last_frame.jpg`. Those literal
pixels become Wan's `start_image_url`. No Nano Banana Pro call of any
kind, no camera-angle change - the video prompt reuses Segment 2's own
`CAMERA_OPPOSITE_ELEVATED` clause verbatim (imported, not retyped) to
describe the same fixed framing the extracted pixels already show.

**Video prompt** (deliberately contains **zero** "HARD TIME JUMP" or
time-compression language - the whole point of this test): the builder
picks up a single deck board, carries it into position across the joists,
kneels, aligns it, and fastens it with a drill; then repeats for
~3-5 boards. Each new board appears **only** at the moment and location
his hands actually place and fasten it - never elsewhere on the
structure. Nothing else about the structure changes.

```bash
python -m scripts.run_causal_action_test
python -m scripts.run_causal_action_test --yes
```

Model settings: Wan 3.0 standard, 480p, 9:16, **10 seconds**
(`WAN_3_0_CAUSAL_TEST`, a local `dataclasses.replace()` variant, touching
no existing segment's config), `start_image_url`, no audio field. $0.50
(10s @ $0.05/s), **no image-generation cost at all** = hard cap with zero
margin.

After the raw clip downloads, a new `app/services/video_assembly.
accelerate_video()` function (ffmpeg `setpts=PTS/factor`, real - not
mocked - tests against the repo's fixture clip in
`tests/test_video_assembly.py`) produces three accelerated versions
**locally, for free**, from the exact same raw clip, without ever
overwriting it (`accelerate_video()` refuses if `output_path` would equal
`input_path`):

Outputs land in `data/fal_causal_action_test/` (gitignored):
- `segment_2_real_last_frame.jpg` - the real extracted starting frame
- `causal_action_raw.mp4` - the raw 10s generation, preserved untouched
- `causal_action_2x.mp4`, `causal_action_3x.mp4`, `causal_action_4x.mp4` - accelerated versions (~5s, ~3.3s, ~2.5s)
- `manifest.json`, `last_job.json`

Verified entirely offline: a mocked-transport dry run uses the repo's
real fixture clip in place of `segment_2.mp4` (not present in the
offline test environment) so the real `extract_last_frame()` call runs
against genuine video data, and returns that same fixture clip's bytes as
the mocked video download, so the real `accelerate_video()` calls at the
end also run ffmpeg against genuine data - not fake placeholder bytes.
Confirms: no image-generation endpoint is ever touched, the uploaded
bytes are a genuine JPEG, the submit payload uses `start_image_url`/
bare-int `duration=10`/no audio field, the prompt contains no "HARD TIME
JUMP" language and does contain the single-causal-action language, cost
is exactly $0.50, three real accelerated files are produced (confirmed
via `ffprobe`, each strictly shorter than the raw clip and in the correct
relative order), the raw file's bytes are unchanged after acceleration,
and the source `segment_2.mp4` stand-in's bytes/mtime are completely
unchanged throughout (read-only).

## Running the construction frontier test (spends real money - max $0.50)

Validation Test #1 proved individual board handling can look believable,
but failed on ordered progression - additional decking appeared elsewhere
on the platform even while the builder correctly installed real boards.
`scripts/run_construction_frontier_test.py` tests the fix: the
**CONSTRUCTION FRONTIER** principle - a single, strict spatial direction
of progress with exactly one active boundary at all times. For decking:
**right to left.**

Same mechanism as Test #1 (freshly re-extracted real Segment 2 last
frame, same camera, no Nano Banana Pro call, no "HARD TIME JUMP"
language, FFmpeg-deferred acceleration) - only the prompt changes, now
built around an explicit priority order:

1. Ordered right-to-left progression
2. The builder visibly causing that progression
3. Believable board handling
4. Fine tool detail (individual fastening motions) - **last**, and the
   first thing simplified away if the model has to trade something off

**Prompt excerpt** (states the frontier concept first, as "the single
most important visual behavior," before any tool-handling detail):

> ...at all times, the platform reads as three clear zones in a fixed left-to-right order - completed decking on the right, the builder working at the boundary in the middle, and untouched exposed joists on the left - and that entire boundary steadily advances from right to left over the course of the clip, like a progress bar filling in behind him. Nothing is ever allowed to leapfrog the builder: no board appears anywhere except directly beside the most recently completed board, immediately adjacent to his current position... Fine mechanical detail (how many screws, exact hand position) matters far less than this strict, unbroken right-to-left ordering - if anything must be simplified, simplify the small tool motions, never the ordering.

```bash
python -m scripts.run_construction_frontier_test
python -m scripts.run_construction_frontier_test --yes
```

Same model settings as Test #1: Wan 3.0 standard, 480p, 9:16, 10s
(`WAN_3_0_FRONTIER_TEST`, its own local config, separate from
`WAN_3_0_CAUSAL_TEST` and every segment's own variant), `start_image_url`,
no audio field. $0.50 (10s @ $0.05/s), zero image cost - **hard cap with
zero margin.** Board count is explicitly not a pass/fail factor - 2-3
correctly-sequenced boards passes; more boards with any ordering
violation does not.

Outputs land in `data/fal_construction_frontier_test/` (gitignored):
`segment_2_real_last_frame.jpg`, `construction_frontier_raw.mp4`
(preserved untouched), `construction_frontier_2x.mp4`, `_3x.mp4`,
`_4x.mp4`, `manifest.json`, `last_job.json`.

Verified entirely offline the same way as Test #1 (real fixture clip
standing in for `segment_2.mp4`, real ffmpeg extraction and acceleration
against genuine video data): no image-generation endpoint touched,
correct payload shape, no "HARD TIME JUMP" language, the frontier/
leapfrog/progress-bar language present in the prompt **before** the
tool-handling language (confirmed by string position, not just presence),
Test #1's heavier fastening-detail phrasing absent, no "3 to 5 boards"
target language, cost exactly $0.50, three real accelerated files with
correctly decreasing durations (via `ffprobe`), the raw file unchanged
after acceleration, the source clip's bytes/mtime unchanged throughout,
and Test #1's own config (`WAN_3_0_CAUSAL_TEST`) confirmed as a genuinely
separate, unmutated object.

## Running the checkpoint chain test (spends real money - max $0.50)

Validation Test #2 passed - construction-frontier progression works
within a single clip, and 4x acceleration is close to the target FORMA
timelapse feel. `scripts/run_checkpoint_chain_test.py` tests the next
question: can a second Wan generation continue that exact same operation
from the first clip's own real final frame, so two separately generated
clips read as one continuous timelapse when concatenated? This is the
basis for eventually completing larger construction phases through
checkpoint chains instead of one AI generation simulating an entire
phase.

**Starting frame**: the real last frame of Test #2's own **raw** output
(`data/fal_construction_frontier_test/construction_frontier_raw.mp4`) -
never the 4x file, since propagation must come from the model's actual
unaccelerated output, and never Segment 2's original frame. Both of Test
#2's source files (`construction_frontier_raw.mp4` and
`construction_frontier_4x.mp4`) are read-only inputs to this script.

**Priority clarification baked into the prompt**: continuity across the
Clip A -> Clip B seam is the #1 success criterion, ranked above how much
additional decking Clip B completes. The prompt names every element that
must stay visually identical to the starting frame - existing decking,
exposed joists, the frontier position, camera/framing, structure
geometry, builder appearance, site/background, lighting - **before** any
instruction about continuing construction, and explicitly states that
even one or two correctly placed boards is a good outcome if everything
else stays continuous:

> This is a direct continuation of an ongoing right-to-left decking operation, picking up from the exact visual state shown in the starting image - not a fresh start. The following must remain visually identical to the starting image for the entire clip: every board already installed as completed decking, the exposed joists still untouched, the position of the construction frontier..., the camera framing, the structure's geometry and proportions, the builder's appearance and clothing, the site and background..., and the lighting... It is far more important that the existing completed decking, camera, structure, and lighting remain visually identical to the starting image than how many additional boards get installed in this clip - even one or two correctly placed boards, with everything else held perfectly continuous, is a good outcome.

```bash
python -m scripts.run_checkpoint_chain_test
python -m scripts.run_checkpoint_chain_test --yes
```

Same model settings as Tests #1/#2 (Wan 3.0 standard, 480p, 9:16, 10s,
`WAN_3_0_CHECKPOINT_CHAIN_TEST`, its own separate local config,
`start_image_url`, no audio). $0.50, zero image cost - **hard cap with
zero margin**. Only the 4x version of Clip B is generated locally (the
2x/3x/4x speed question was already settled by Test #2 - not re-tested
here), then concatenated with Test #2's own real 4x file into
`combined_preview_4x.mp4` via the existing `concatenate_videos()` - the
**primary output**, meant to be judged as one continuous timelapse the
way a viewer would, not as two separate technical clips.

Outputs land in `data/fal_checkpoint_chain_test/` (gitignored):
`clip_b_start_frame.jpg`, `clip_b_raw.mp4` (preserved untouched),
`clip_b_4x.mp4`, **`combined_preview_4x.mp4`**, `manifest.json`,
`last_job.json`.

Verified entirely offline the same way as Tests #1/#2 (the repo's real
fixture clip standing in for both of Test #2's source files, real ffmpeg
extraction/acceleration/concatenation against genuine video data): no
image-generation endpoint touched, correct payload shape, no "HARD TIME
JUMP" language, every continuity element confirmed present in the prompt
**before** the continuation instructions (by string position), the
board-quantity deprioritization sentence confirmed present, cost exactly
$0.50, a real accelerated Clip B and a real combined preview both
produced (via `ffprobe`), Clip B's raw file unchanged after
acceleration/concatenation, both of Test #2's source files completely
unchanged throughout (read-only), and every other test's and segment's
own config confirmed as a genuinely separate, unmutated object.

## Running the camera transition edit test (spends real money - max $0.15)

FORMA Video #1's planned camera-transition mechanism - `NANO_BANANA_PRO_EDIT`
image-conditioned on a real previous frame, asked for a conservative
angle nudge - has never been tested in this project. Everything tried
before was either a small local correction (V2A, mechanical start/end
frame tests) or a large-swing full regeneration (which failed once
structures got geometrically complex, at Segment 3). `scripts/
run_camera_transition_edit_test.py` tests the untested middle ground in
isolation, using real, already-existing footage, before committing FORMA
Video #1's architecture to it.

**Source**: the real, literal last frame of the approved cliff-cabin
Segment 2 video (`data/fal_full_video_segment_2/segment_2.mp4`),
extracted locally via `extract_last_frame()` (read-only - the video file
is never modified). Chosen deliberately for its existing structural
complexity (expanded platform, joists, posts) rather than a simple scene.

**Edit prompt** (image-conditioned - describes the change, not the whole
scene from scratch):

> Shift the camera position moderately - approximately 20 to 30 degrees around the site - to a nearby three-quarter viewpoint, as if a second camera had been placed a short distance away rather than in the exact same spot. Keep every element of the scene exactly as it currently appears: the same timber platform with the same proportions, the same joist spacing and layout, the same foundation posts in the same positions, the same builder (same identity, clothing, and pose intent), the same large flat grey boulder, the same cliff and coastline geometry, and the same golden-hour lighting direction. Do not add any new construction - no walls, no roof, no additional joists or boards beyond what is already present. Do not remove or alter anything already visible. This is purely a camera position change, not a redesign or rebuild of the scene.

```bash
python -m scripts.run_camera_transition_edit_test
python -m scripts.run_camera_transition_edit_test --yes
```

Exactly 1 `NANO_BANANA_PRO_EDIT` call, no video call of any kind, no
retries. $0.15 flat rate - **hard cap with zero margin**. This is a pure
mechanism test - it does not touch Segments 1A, 1B, 2, or 3, any
Validation Test #1-3 output, or FORMA Video #1 itself.

Outputs land in `data/fal_camera_transition_edit_test/` (gitignored):
`segment_2_real_last_frame.jpg` (the real source), `camera_transition_edit.jpg`
(the result), `manifest.json`.

Verified entirely offline: a mocked-transport dry run uses the repo's
real fixture clip in place of `segment_2.mp4` so `extract_last_frame()`
runs against genuine video data, confirms the `/edit` endpoint is used
(never the text-to-image `/generate` endpoint), the exact real extracted
frame's bytes are what gets uploaded, the prompt contains the 20-30
degree instruction plus every preservation clause (platform proportions,
joist spacing, post positions, builder identity, boulder, coastline,
lighting) and both prohibition clauses (no new construction, nothing
removed), cost is exactly $0.15, and the source clip's bytes/mtime are
completely unchanged throughout.

## Running the compound edit validation test (spends real money - max $0.15)

FORMA's redesigned jump-cut architecture (see "FORMA jump-cut grammar"
below) depends on a bigger ask of `NANO_BANANA_PRO_EDIT` than the
camera-transition rule above ever tested: can a single edit call both
advance an already-visible construction phase to its logical completion
AND make a modest camera nudge, while preserving everything else? The
camera-transition test proved the nudge alone, on an otherwise-unchanged
structure - it never asked the edit to also complete construction.
`scripts/run_edit_advance_completion_test.py` tests this compound
behavior in isolation, before it's relied on anywhere in FORMA Video #1.

**Source**: the real, literal last frame of the cliff-cabin Checkpoint
Chain Test's own raw output (`data/fal_checkpoint_chain_test/clip_b_raw.mp4`),
extracted locally via `extract_last_frame()` (read-only - the video file
is never modified). Chosen deliberately because it shows a partially-decked,
exposed-joist floor - a clean, already-existing example of a partially
completed but clearly recognizable construction phase that doesn't
depend on any unfinished Waterfall Cave footage.

**Edit prompt** (asks for phase completion + a small camera nudge, names
every preservation and prohibition clause explicitly):

> This is an intentional editorial jump cut - the same construction project, filmed again some time later, with the same decking phase now further along - not a different or redesigned version of the build. Keep the underlying structure exactly as it is: the same platform proportions, the same foundation posts and perimeter beams in the same positions, the same joist spacing and layout, the same builder (same identity, clothing, and pose intent), the same site, cliff, boulder, and coastline geometry, and the same lighting direction. Shift the camera only slightly - approximately 15 to 20 degrees around the site - to a nearby, modestly different viewpoint, as if a second camera had been placed a short distance away. Advance ONLY the decking: complete the remaining exposed joists with the same style and spacing of deck boards already visible, so the section of floor that was still exposed joists in the starting image now reads as fully decked, matching and continuing the boards already installed. Do not change the platform's size or shape, do not move or add any posts or beams, do not alter the site or landscape, and do not begin or imply any next construction phase - no walls, no roof, no glass, no framing beyond the existing joists. This is purely completing the current decking phase and a small camera nudge, not inventing new construction.

```bash
python -m scripts.run_edit_advance_completion_test
python -m scripts.run_edit_advance_completion_test --yes
```

Exactly 1 `NANO_BANANA_PRO_EDIT` call, no video call of any kind, no
retries. $0.15 flat rate - **hard cap with zero margin**. This is a pure
mechanism test - it does not touch any cliff-cabin segment, Validation
Test #1-3, the Checkpoint Chain Test's own output, or FORMA Video #1
itself.

Outputs land in `data/fal_edit_advance_completion_test/` (gitignored):
`checkpoint_chain_real_last_frame.jpg` (the real source),
`advanced_completion_edit.jpg` (the result), `manifest.json`.

Verified entirely offline: a mocked-transport dry run uses the repo's
real fixture clip in place of `clip_b_raw.mp4` so `extract_last_frame()`
runs against genuine video data, confirms the `/edit` endpoint is used
(never the text-to-image `/generate` endpoint), the exact real extracted
frame's bytes are what gets uploaded, the prompt contains the 15-20
degree instruction plus every preservation clause (platform proportions,
posts/beams, joist spacing/layout, builder identity, site/cliff/boulder/
coastline, lighting) and every prohibition clause (no size/shape change,
no moved/added posts or beams, no altered site, no next-phase elements),
cost is exactly $0.15, and the source clip's bytes/mtime are completely
unchanged throughout.

## FORMA Video #1 pivot: cliffside cabin, not waterfall cave (permanent project note)

The cliffside cabin build (Segments 1A/1B/2 + the Construction Frontier
Test's decking clip) is now FORMA's first real posted video - it is
simpler, already more validated (three approved/locked real segments
plus a passed decking test), and lower-risk than the Waterfall Cave
concept, which becomes a later project. Nothing about the Waterfall Cave
planning/scripts already built is discarded - it's simply not next.

## Running the cliffside rough assembly (free - no API calls, no FAL_API_KEY needed)

Pure local FFmpeg, no spend of any kind. Before any new paid generation
for the cliffside video, this answers a simple question for free: how
much of the 30-32s Phase 1 target is already covered by footage that is
APPROVED, LOCKED, and already paid for? Accelerates and concatenates the
four existing real clips (Segment 1A, Segment 1B, Segment 2, and the
Construction Frontier Test's decking clip) into one rough preview,
covering the "existing material" ~17.5s of the final video - Framing,
Finishing, and the Reveal are new generation, not included here.

```bash
python -m scripts.run_cliffside_video_1_rough_assembly
```

Requires `segment_1a.mp4`, `segment_1b.mp4`, `segment_2.mp4`, and
`construction_frontier_raw.mp4` to already exist (from prior real runs of
their own scripts) - fails clearly listing whichever are missing. None of
the four source clips are ever modified. Output:
`data/cliffside_video_1/rough_assembly_preview.mp4`, `manifest.json`.

Verified entirely offline: a dry run using the repo's real fixture clip
as a stand-in for all four source files confirms it fails cleanly when
clips are missing and otherwise produces real, valid accelerated clips at
the documented factors (1.5x/2.0x/2.2x/2.5x) and a real combined preview
via genuine ffmpeg operations, with none of the four source clips ever
modified.

## Cliffside cabin permanent structure definition (construction spec)

The finished structure is a small modern single-story cliffside cabin,
built directly on the existing approved platform and never growing
beyond its footprint. These are visual anchors, not engineering
requirements - the actual generated platform pixels remain authoritative
if there is ever a conflict:

- overall footprint: approximately 12 feet wide by 16 feet deep, simple
  rectangular perimeter
- wall height: approximately 8 feet
- roof peak: approximately 10-11 feet
- single story only, no second floor, no balcony beyond the existing
  platform
- lightweight timber-frame construction, modern minimalist design
- ocean-facing wall carries the largest glass area (2-3 panels,
  each roughly 3-4 feet wide by 7-8 feet tall - not floor-to-ceiling)
- one primary doorway on the landward/side wall
- dark-stained timber or charcoal-toned exterior cladding, natural wood
  accents, clean modern lines - premium but restrained
- no oversized/luxury-villa proportions, no random wings or extensions,
  no extra rooms, no chimneys/solar panels/decorative clutter unless
  already planned

## Running Cliffside Video #1, Part 2 (spends real money - max $1.35 across 6 gated stages)

Part 2 (Framing -> Glass -> Reveal) continues directly from Part 1's
approved rough assembly, per the FORMA jump-cut grammar: DEMONSTRATE (a
short Wan mechanism clip, 1-3 repetitions only) -> JUMP CUT (a
`NANO_BANANA_PRO_EDIT` that advances construction to a logical completed
state, per the construction spec above, plus a modest ~15-20 degree
camera nudge) -> NEXT LOGICAL STAGE. Same hard-gate pattern as every
other stage in this project: each script stops completely after its own
paid call, and the next stage requires its own explicit upstream-approval
confirmation - not skippable by `--yes` - before its own cost
confirmation even appears.

A dedicated Final Detail shot was cut after the first pass on cost/
pacing grounds: for a ~30s Phase 1 video, a 5s/$0.25 generation for one
finishing gesture didn't earn its screen time or cost. The Reveal now
runs directly off the exterior-completion edit's own image - no
intermediate video checkpoint needed.

| # | Script | Type | Source | Output | Cost |
|---|---|---|---|---|---|
| C0 | `run_cliffside_video_1_decking_complete_edit.py` | EDIT | Construction Frontier Test's real last frame | `decking_complete_edit.jpg` | $0.15 |
| 1 | `run_cliffside_video_1_part2_framing.py` | Wan (6s) | C0's edit | `framing_raw.mp4` | $0.30 |
| 2 | `run_cliffside_video_1_part2_framing_edit.py` | EDIT | Shot 1's real last frame | `framing_complete_edit.jpg` | $0.15 |
| 3 | `run_cliffside_video_1_part2_glass.py` | Wan (5s) | Jump Cut 1's edit | `glass_raw.mp4` | $0.25 |
| 4 | `run_cliffside_video_1_part2_exterior_edit.py` | EDIT | Shot 2's real last frame | `exterior_complete_edit.jpg` | $0.15 |
| 5 | `run_cliffside_video_1_part2_reveal.py` | Wan (7s), no edit | Jump Cut 2's edit, directly | `reveal_raw.mp4` | $0.35 |

```bash
python -m scripts.run_cliffside_video_1_decking_complete_edit
python -m scripts.run_cliffside_video_1_part2_framing
python -m scripts.run_cliffside_video_1_part2_framing_edit
python -m scripts.run_cliffside_video_1_part2_glass
python -m scripts.run_cliffside_video_1_part2_exterior_edit
python -m scripts.run_cliffside_video_1_part2_reveal
```

Each accepts `--yes` to skip only its own cost-confirmation prompt - the
upstream-approval prompt always fires and is never skippable. All output
lands in `data/cliffside_video_1/` alongside Part 1's rough assembly,
sharing one `manifest.json` (each script only writes its own top-level
key). Stage C0 is a precondition for Shot 1: Part 1's rough assembly ends
on the Construction Frontier Test's decking-in-progress footage, and
Framing needs a fully-decked floor to start from - not one of the
user-numbered "6 gated steps," but load-bearing for all of them. The
Reveal (Shot 5) runs directly from `exterior_complete_edit.jpg` - no
frame extraction, no further edit - per the already-locked safest-reveal
method (the edit already happened at Jump Cut 2; this shot runs straight
off its output, the same pattern already used for FORMA Video #1's
Foundation stage running directly off Camera B's edit).

Verified entirely offline: a consolidated mocked-transport dry run
chains through all 6 stages in sequence (each stage's fake output feeding
the next, using the repo's real fixture clip wherever a later stage
extracts a real last frame), confirming for every stage that the decline
path makes zero calls, the accept path makes exactly 1 call to the
correct endpoint only (no video endpoint touched by any EDIT stage, no
image endpoint touched by any Wan stage), every prompt carries its
dimension/material/exclusion language, no audio field or language
anywhere, costs are exactly as documented ($1.35 total), and every
upstream file is completely unchanged throughout its own stage.

## Execution model (permanent project note)

Claude's sandbox for this project has no network path to fal.ai (no
`FAL_API_KEY`, no reachable `fal.run`/`queue.fal.run`) and never has, for
the life of this project. Every real generation described anywhere in
this README - every approved segment, every passed validation test, the
approved Framing clip - was produced by the user running the exact
script and command shown, on their own machine, with their own API key,
then reporting the real result back. Claude's role is to design the
production grammar, write and offline-verify every script (mocked HTTP
transport standing in for fal.ai, the repo's real fixture clip standing
in for real footage where ffmpeg needs genuine video data), and hand over
exact commands - never to execute paid calls itself. "Authorize Claude to
make the paid calls" is not something this sandbox can act on directly;
the useful equivalent is finishing every remaining script, gate, and
assembly step so the user can run the whole remaining sequence themselves
in one sitting without coming back for a new preflight after each one.

## Running the Cliffside Video #1 budget check (free - no API calls, no FAL_API_KEY needed)

Reads `data/cliffside_video_1/manifest.json` and sums every stage's real
`actual_cost_usd` against a cap (defaults to $5.00, the Part 2
completion budget) so you can check remaining budget before any paid
call without doing the arithmetic by hand:

```bash
python -m scripts.run_cliffside_video_1_budget_check
python -m scripts.run_cliffside_video_1_budget_check 3.00
```

Prints each Part 2 stage's real cost (or "not run" if it hasn't happened
yet), total spent, and remaining budget against the cap - warns if spend
already exceeds it.

## Running the Cliffside Video #1 final assembly (free - no API calls, no FAL_API_KEY needed)

Pure local FFmpeg. Combines all seven real clips (Segment 1A, 1B, 2, the
Construction Frontier decking clip, Framing, Glass, Reveal) into one
finished ~30-32s cut. The jump-cut EDIT images
(`decking_complete_edit.jpg`, `framing_complete_edit.jpg`,
`exterior_complete_edit.jpg`) are never separate visible shots - they
only ever conditioned the next Wan generation; the "jump cut" the viewer
sees is the trimmed+accelerated transition straight from one real clip
into the next.

```bash
python -m scripts.run_cliffside_video_1_final_assembly
```

Each clip gets its own trim (in/out seconds via the new `trim_video()` in
`app/services/video_assembly.py` - "don't preserve footage just because
it was paid for") and its own acceleration factor, tuned as plain
constants in `CLIP_SPECS` - free, local, instantly re-editable after
watching the real raw clips, no re-generation needed. Requires all seven
source clips to already exist; fails clearly listing whichever are
missing. Output: `data/cliffside_video_1/cliffside_video_1_final_visual.mp4`,
per-clip trimmed/accelerated intermediates under `data/cliffside_video_1/final/`,
`manifest.json["final_assembly"]` (per-clip trim/factor/finished-seconds
breakdown, final duration, target range).

Verified entirely offline: a dry run using the repo's real fixture clip
as a stand-in for all seven source files confirms it fails cleanly when
clips are missing and otherwise produces real trimmed/accelerated clips
and a real concatenated final master via genuine ffmpeg operations
(including `trim_video()`, covered by its own real, non-mocked tests in
`tests/test_video_assembly.py`), with none of the seven source clips ever
modified.

## FORMA production phases (permanent project note)

FORMA operates in two distinct phases, and the target video length is a
deliberate function of which phase the account is in - not a fixed
creative decision:

- **Phase 1 - audience growth (current phase).** TikTok's Creator Rewards
  structure only pays out meaningfully once an account qualifies for it;
  until then there is no monetization reason to pay for 61-65 second
  videos every time. Phase 1 targets **~28-35 second finished videos
  (~30-32s preferred)**, built cheaper and faster so more concepts can be
  tested and the account can grow on views, not payout-per-video. The
  standard is NOT lowered in Phase 1 - every video still needs to be a
  complete transformation (HOOK -> PREP -> STRUCTURE -> RECOGNIZABLE
  BUILD -> FINISH -> PAYOFF), still uses the same visual quality bar and
  the same FORMA identity, and still follows every locked production
  principle (Causal Labor, Construction Frontier, Checkpoint Chaining,
  the FORMA Site Prep Rule, the camera-transition rule). What changes is
  scale: fewer paid generations, fewer camera chapters, stages combined
  or compressed rather than chained into micro-steps, and less footage
  overall - the production is shortened, not the standard.
- **Phase 2 - monetization.** Once FORMA qualifies for Creator Rewards
  (or another monetization mechanism where longer runtime materially
  increases payout), the target format switches back to **~61-65 second
  finished videos**, the original full-scale production plan (~12-18 Wan
  generations, 120-160s total raw video, more camera chapters, longer
  chained construction sequences).

Switching phases is a deliberate, explicit decision - not something
inferred from a single video's constraints - and should be recorded here
when it happens.

## FORMA jump-cut grammar (permanent project note, v2 - supersedes v1)

v1 of this grammar (DEMONSTRATE 1-3 repetitions, THEN jump-cut to the
entire phase complete) was derived from reference footage and validated
in isolation, then used to build the whole of Cliffside Video #1. Having
now watched the complete 30.63s finished video, that rule is **replaced**
- it was too aggressive: showing one glass panel then cutting straight to
the entire finished exterior reads as "AI-generated before/after images,"
not as watching a house get built. The compound-edit mechanism itself
(advance a construction phase's state via `NANO_BANANA_PRO_EDIT` +
camera nudge) is retained and now considered validated by production
use; only how much of each phase Wan is asked to carry changes.

- **FORMA 90% Process Rule.** For visually important, repetitive
  construction phases (flooring, structural framing, roofing, glass,
  furnishing), the viewer should watch approximately **70-90% of that
  phase's visible progress happen on camera**. The jump cut skips only
  the repetitive *final* portion, and starts the next shot with that
  phase already finished. WRONG: first floorboard placed -> CUT -> floor
  entirely finished. RIGHT: floorboards sweep across ~80-90% of the
  floor on camera -> CUT -> next shot opens on a finished floor,
  immediately beginning the next task. This is now how the mechanism-
  clip + EDIT architecture is used: Wan carries the large majority of
  the visible transformation; the edit only closes the last stretch and
  makes the camera move.
- **Optimize for visible completion per dollar, not per API call.** Do
  not default to many short/cheap clips. A single longer raw clip,
  accelerated more aggressively, that lets a repetitive frontier sweep
  across most of a phase can be far more satisfying - and no more
  expensive - than several short clips each showing one action. Evaluate
  cost against how much real visible progress a viewer gets to watch,
  not against minimizing generation count.
- **Aggressive, readable acceleration.** Once construction begins,
  target roughly **3x-5x** (higher where the motion stays legible) for
  repetitive phases - chosen for maximum visible progress per finished
  second, not for preserving ordinary-paced human motion. Almost every
  0.5-1s of finished footage should carry new, meaningful progress.
  Minimize walking, surveying, idle movement, tool setup, and long
  fastening detail - the builder should be constantly contributing
  material to the structure.
- **Material flow stays visible.** MATERIAL ARRIVES/IS GRABBED -> BUILDER
  POSITIONS IT -> IT BECOMES PART OF THE STRUCTURE -> NEXT MATERIAL,
  repeated. Materials may enter from off-camera or an established nearby
  stack - their delivery never needs to be documented - but a piece must
  never simply appear already installed; the structure grows because
  material visibly moves into it.
- **Each major category earns real screen time.** Distinct visible
  categories (flooring, framing, roofing, glazing, furnishing, etc.)
  each get enough screen time to watch most of that specific
  transformation, not a rapid skim across all of them. Jump cuts land
  late in a task (after the 70-90% mark), never immediately after it
  starts: START TASK -> RAPID VISIBLE PROGRESSION -> ~80-90% COMPLETE ->
  CUT -> NEXT TASK.
- **Interior design/furnishing is a required phase** for any FORMA
  structure with a habitable interior - shown briefly but really watched
  (70-90% of the furnishing transformation on camera: furniture/decor
  physically brought in and placed), never one item followed by a cut to
  a fully finished room.
- **Shorter reveal, more build.** The reveal is the payoff, not the
  majority of the runtime - target roughly 3.5-4.5s of a ~30-32s video
  (Video #1's ran 6+s). The build itself is the entertainment; time
  saved from a tighter reveal goes to more construction screen time.

The compound mechanism-clip + EDIT architecture (real previous frame ->
Wan clip carrying most of a phase's visible progress -> literal last
frame -> `NANO_BANANA_PRO_EDIT` closing out the remainder + a modest
camera nudge -> next Wan clip) is unchanged in mechanics from v1 - only
the *proportion* of each phase Wan is asked to carry changed, from "just
enough to demonstrate the mechanism" to "most of the visible phase."

## Running FORMA Video #1 - Chapter A (spends real money - max $0.95 across 3 gated stages)

Chapter A (Hook + Site Prep) is FORMA Video #1's first production chapter,
built as **four completely isolated stages** rather than one auto-chaining
script. Each paid stage stops completely after generating its one clip -
nothing downstream ever runs automatically, so a failed or un-reviewed
upstream clip can never trigger further spend. Every stage after Stage A1
requires a separate, explicit "have you reviewed and approved the previous
clip?" confirmation (distinct from, and asked before, the usual cost
confirmation) - answering anything but `yes` stops immediately with zero
calls made, not even the free local frame extraction.

All Wan prompts in Chapter A are **visual-only** - Wan is run with no
audio field, and no prompt asks for waterfall/wind/footsteps/tools/birds/
dialogue/narration/music of any kind. FORMA sound is a separate
post-production layer, added later. The approved waterfall-cave reference
photo is **authoritative**: Stage A1 uses it directly as the starting
image (never regenerated, never identity-corrected), and the actual
builder appearance, cave geometry, waterfall position, and lighting
visible in it govern every subsequent prompt.

### Before you start

Place your already-approved waterfall-cave reference photo at exactly:

```
data\forma_video_1_chapter_a\canonical_reference_start_frame.jpg
```

Stage A1 fails clearly (before spending anything) if this file is missing.
The file is only ever read, never modified.

### Stage A1 - Hook (spends real money - max $0.20)

```bash
python -m scripts.run_forma_v1_chapter_a_hook
python -m scripts.run_forma_v1_chapter_a_hook --yes
```

Wan 3.0 standard, 480p, 9:16, 4s, image-to-video from the reference photo
directly. One cost-confirmation gate (no upstream-approval gate - there is
no prior chapter clip yet). Exactly 1 video call, no retries. Output:
`data/forma_video_1_chapter_a/hook_raw.mp4`, `manifest.json`. **Stop here
and review the clip before running Stage A2.**

### Stage A2 - Site Prep Clip 1 (spends real money - max $0.35)

Runnable only after `hook_raw.mp4` exists. Extracts Hook's real last frame
locally (free), then requires typing `yes` at the upstream-approval prompt
before the cost-confirmation prompt even appears:

```bash
python -m scripts.run_forma_v1_chapter_a_prep1
python -m scripts.run_forma_v1_chapter_a_prep1 --yes
```

`--yes` only skips the cost-confirmation prompt - the upstream-approval
prompt always fires and is never skippable. Wan 3.0 standard, 480p, 9:16,
7s, image-to-video from the extracted frame. Per the FORMA Site Prep
Rule, this clip shows a compact tracked mini excavator (operated by the
builder) scraping loose rock/mud/debris from one bounded section and
depositing it in a visible pile to one side - not hand-clearing. Output:
`data/forma_video_1_chapter_a/site_prep_clip1_raw.mp4`. **Stop here and
review before running Stage A3.**

### Stage A3 - Site Prep Clip 2 (spends real money - max $0.40)

Same pattern, gated on `site_prep_clip1_raw.mp4` and its own
upstream-approval confirmation:

```bash
python -m scripts.run_forma_v1_chapter_a_prep2
python -m scripts.run_forma_v1_chapter_a_prep2 --yes
```

Wan 3.0 standard, 480p, 9:16, 8s. Continues the same excavator from Prep
1's real last frame: finishes clearing the remaining rough ground, then
transitions to leveling passes, ending as a flat, mechanically-worked
construction pad. Output:
`data/forma_video_1_chapter_a/site_prep_clip2_raw.mp4`. **Stop here and
review before running Stage A4.**

### Stage A4 - Local assembly (free - no API calls, no FAL_API_KEY needed)

Runnable only after all three raw clips exist. Pure local FFmpeg:
accelerates each raw clip individually (Hook 4.0x, Prep 1 3.5x, Prep 2
4.0x -> ~5.0s finished total, retuned down from an earlier ~9.1s cut
under the FORMA Phase 1 ~31s target so the freed screen time goes to
Foundation/Decking instead - easily adjustable by editing the
`*_FACTOR` constants and re-running, a free and instant step), then
concatenates the accelerated clips into one combined preview:

```bash
python -m scripts.run_forma_v1_chapter_a_assemble
```

Output: `data/forma_video_1_chapter_a/chapter_a_combined_preview.mp4`.
Review it as one continuous piece - Hook's near-real-time establishing
beat flowing into Site Prep's accelerated progress, no visible seam.

Verified entirely offline: mocked-transport dry runs for Stages A1-A3
confirm each submits exactly 1 video call with the correct duration/
resolution/aspect ratio, no audio field and no audio-language in the
prompt, and (Stages A2-A3) that declining the upstream-approval prompt
makes zero calls and doesn't even extract a frame; a dry run for Stage A4
using the repo's real fixture clip as a stand-in for all three raw files
confirms it fails cleanly when clips are missing and otherwise produces
real, valid accelerated clips and a real combined preview via genuine
ffmpeg operations, with none of the three raw clips ever modified.

## Running FORMA Video #1 - Chapter B (spends real money - max $0.50 across 2 gated stages)

Chapter B (Foundation/Floor) is FORMA Video #1's second production
chapter, under the FORMA Phase 1 ~31s target. Same hard-gate pattern as
Chapter A: each stage stops completely after its own paid call, and the
next stage requires its own explicit "have you reviewed and approved
the previous output?" confirmation - not skippable by `--yes` - before
its own cost-confirmation prompt even appears.

### Stage B0 - Camera B transition edit (spends real money - max $0.15)

Runnable only after Chapter A's `site_prep_clip2_raw.mp4` exists.
Extracts its real last frame locally (free), then requires typing `yes`
at the upstream-approval prompt before the cost-confirmation prompt:

```bash
python -m scripts.run_forma_v1_chapter_b_camera_edit
python -m scripts.run_forma_v1_chapter_b_camera_edit --yes
```

`NANO_BANANA_PRO_EDIT`, a conservative ~20-30 degree camera nudge,
conditioned on the real extracted frame - per the locked camera-
transition rule. Preserves the cleared/leveled pad, the single debris
ridge, the skid-steer machine, and the cave/waterfall exactly; adds no
construction of any kind. Output: `data/forma_video_1_chapter_b/camera_b_edit.jpg`.
**Stop here and review before running Stage B1** - only after this edit
is approved does Foundation become eligible to run.

### Stage B1 - Foundation/Floor (spends real money - max $0.35)

Runnable only after `camera_b_edit.jpg` exists and is approved. Uses the
edit image directly as the starting image (no frame extraction needed -
it's already a still image):

```bash
python -m scripts.run_forma_v1_chapter_b_foundation
python -m scripts.run_forma_v1_chapter_b_foundation --yes
```

Wan 3.0 standard, 480p, 9:16, 7s. A single bounded causal operation per
explicit instruction: the builder installs foundation posts across the
pad one at a time, in one continuous direction - no decking, no framing,
no walls, and no glass appear in this clip; those are separate, later
stages. Output: `data/forma_video_1_chapter_b/foundation_raw.mp4`. **Stop
here and review** - Decking (Stage B2) has not been built yet.

Verified entirely offline: mocked-transport dry runs for both stages
confirm exactly 1 call each (image edit for B0, video for B1) with the
correct endpoint, no video endpoint touched by B0 and no image endpoint
touched by B1, no audio field/language anywhere, and that declining the
upstream-approval prompt makes zero calls (B0 doesn't even extract a
frame); cost is exactly $0.15 (B0) / $0.35 (B1); the upstream file
(`site_prep_clip2_raw.mp4` / `camera_b_edit.jpg`) is completely unchanged
throughout each dry run.

## Running the API server

```bash
uvicorn app.main:app --reload
```

Then, in another terminal:

```bash
# Create a project
curl -X POST http://127.0.0.1:8000/projects \
  -H "Content-Type: application/json" \
  -d '{"idea_text": "He buried a pink submarine in his backyard and turned it into an underground luxury bunker."}'

# Advance it (replace <id> with the id returned above)
curl -X POST http://127.0.0.1:8000/projects/<id>/concept
curl -X POST http://127.0.0.1:8000/projects/<id>/script
curl -X POST http://127.0.0.1:8000/projects/<id>/storyboard

# See the full project, including continuity bible, shots, and cost
curl http://127.0.0.1:8000/projects/<id>

# Generate a reference image for one shot (replace <shot_id> with a shot id from above)
# - optional, but submit_shot_video_job below will use it automatically if present
curl -X POST http://127.0.0.1:8000/projects/<id>/shots/<shot_id>/reference-image

# Submit a video generation job for one shot
curl -X POST http://127.0.0.1:8000/projects/<id>/shots/<shot_id>/generate

# Poll it until status is COMPLETED (replace <job_id> with the id returned above)
curl -X POST http://127.0.0.1:8000/projects/<id>/shots/<shot_id>/jobs/<job_id>/poll

# Regenerate a shot that ended up FAILED or QA_FAILED
curl -X POST http://127.0.0.1:8000/projects/<id>/shots/<shot_id>/regenerate
```

Interactive API docs (Swagger UI) are available at
`http://127.0.0.1:8000/docs` while the server is running.

## Running the tests

```bash
pytest
```

## Configuration

All configuration lives in environment variables (see `.env.example`).
Never commit a real `.env` file or API keys - `.env` is gitignored.

Settings enforced today:

- `FACTORY_PAUSED` - global kill switch, checked before any generation step
  (LLM or video). Set `FACTORY_PAUSED=true` to stop all generation.
- `MAX_SPEND_PER_PROJECT_USD` - enforced before every video job submission.
- `VIDEO_JOB_TIMEOUT_SECONDS` - how long a job can sit at PROCESSING before
  it's marked TIMED_OUT and the shot marked FAILED.
- `MAX_JOB_POLL_RETRIES` - how many transient (network-type) polling errors
  in a row are tolerated before a job is given up on.
- `MAX_REGENERATIONS_PER_SHOT` - caps how many times one shot can be
  resubmitted as a new job.

Not yet enforced (Milestone 9's job): `MAX_DAILY_SPEND_USD` (per-project
limits work now; a global daily cap across all projects doesn't yet), and
provider-level rate limiting.

## What's next

- **Milestone 2, complete**: the real fal.ai `VideoProvider` (Wan 2.2 A14B
  Turbo) and `ImageProvider` (FLUX schnell) adapters work end-to-end - a
  real image + video generation succeeded (`scripts/run_first_fal_test.py`,
  after fixing two queue-routing bugs the live call surfaced - see "Cost
  model" above).
- **Continuity probe, complete**: `scripts/run_continuity_test.py` tested
  whether last-frame propagation holds a construction project visually
  consistent (same worker, same location, same developing structure)
  across 3 sequential Wan Turbo generations. Run for real by the user;
  successful enough to proceed to model selection.
- **Creative specification, current**: the full product direction (recurring
  builder character, compact one-person projects in beautiful natural
  settings, ~14-18 stage chronological progression, loosened continuity
  philosophy, retention-driven pacing, documentary camera style, sound as a
  future core requirement, per-shot model/budget flexibility) is now the
  standing spec governing engineering decisions - see the project's own
  notes/history for the full text. Model selection now weighs realistic
  human/tool motion and reference/continuity adherence well above cost.
- **Quality bake-off, complete**: `scripts/run_bakeoff_test.py` compared
  Wan Turbo 480p against Kling 2.6 Pro and Veo 3.1 Fast from the same
  reference image and a compound action prompt. Run for real by the user
  and reviewed against reference TikToks; the main finding was rigid-object/
  tool morphing in the timber across all three, worst where the prompt
  asked for several physical state changes in one generation (pick up saw
  -> cut -> lift board -> carry -> position -> fasten). This directly
  reshaped the production format - see "Format specification" below.
- **Format specification, current**: the bake-off review produced a
  definitive, more specific product spec on top of the earlier creative
  spec - the finished video is an edited assembly of many short, atomic,
  single-action clips (one dominant verb each: cut, drill, hammer, sand,
  paint, install...) stitched into a chronological build via editing, not
  one continuously simulated construction; continuity is defined as
  forward-only believable build state, not pixel-perfect frame matching;
  model selection and continuity strategy can vary per clip; sound and
  editing/trimming are represented as metadata now, built later. Full
  architecture direction (not yet implemented): split today's `Shot` into
  `ConstructionStage` (a build phase, holding structured `BUILD_STATE`)
  and `Shot`-as-atomic-clip (one dominant action each, with its own
  continuity strategy and model tier).
- **Atomic-action experiment V1, complete**: `scripts/run_atomic_cut_test.py`
  tested whether restricting a clip to one dominant action (continuous
  saw-cutting only) reduces the morphing seen in the bake-off's compound
  prompt. Run for real and reviewed: it simplified the scene but did not
  solve the core problem - hand placement, saw orientation, and blade/wood
  contact still looked AI-generated across all 3 models. Conclusion: prompt
  complexity was a real but secondary lever; the bottleneck is upstream of
  prompting (model choice, or what the model is conditioned on).
  Model-selection research since V1 (not yet spent on): Kling 3.0 Pro
  supersedes Kling 2.6 Pro on fal.ai with a "physics-first" tradeoff
  profile; first/last-frame-conditioned models (Kling O1, Wan 2.1 FLF2V)
  let a video model interpolate between two already-correct frames instead
  of inventing one from scratch; motion-transfer models (Kling 3.0 Motion
  Control, Wan Motion) can retarget a real driving video's motion onto our
  character, though research found Kling's Element Binding only locks face
  identity, not props/tools - so tool-geometry consistency isn't solved by
  motion transfer alone. Sora 2/Pro ruled out (fal.ai/OpenAI API sunsets
  September 24, 2026, no successor announced).
- **V2A keyframe experiment, complete (rejected on composition)**:
  `scripts/run_v2a_keyframes_test.py` tested whether a circular-saw
  start/end frame pair could be edited into mechanical correctness. Run
  for real: the mechanical edit largely worked, but both frames exposed a
  different, more fundamental problem - the builder read as centered,
  front-facing, and posed for the camera, like a portrait rather than
  candid footage. Traced to the source: the bake-off's original reference
  image had no camera-angle instruction, defaulted to a "hero shot," and
  V2A's edit pass preserved that framing (edit models make small local
  corrections; full pose/camera reorientation is a global change actively
  suppressed by "change as little else as possible"). Produced the
  "Permanent visual rules" above (BUILDER ATTENTION / OBSERVATIONAL CAMERA
  / COMPOSITIONAL HIERARCHY) as standing prompting rules, not a one-off fix.
- **Composition test, complete and PASSED**: `scripts/run_composition_test.py`
  tested whether a *freshly generated* (not edited) base action image could
  get the camera/attention relationship right when the permanent visual
  rules are written into the prompt from the start. Run for real and
  approved: `action_base_frame.jpg` is now the target visual language for
  construction-action shots (side/three-quarter-rear angle, zero eye
  contact, natural working posture, cabin reading as an active project).
  Subsequent stages must preserve this composition, not regenerate or
  reangle it.
- **Mechanical still-image test, complete and PASSED**:
  `scripts/run_mechanical_start_frame_test.py` tested whether
  `NANO_BANANA_PRO_EDIT` could correct the saw's mechanics on the approved
  `action_base_frame.jpg` without regressing the composition. Run for real
  and approved: `mechanical_start_frame.jpg` preserved every composition
  quality (no eye contact, downward gaze, observational angle, posture,
  cabin/landscape/framing) while making the saw/body interaction materially
  more believable - confirming the local-edit approach works when the
  source composition is already correct.
- **Mechanical end-frame test, run for real (result pending review)**:
  `scripts/run_mechanical_end_frame_test.py` asked the narrowest possible
  next question - can a second frame (the same cut progressed ~40-60%
  further along the same cut line) be produced from the approved start
  frame while staying visually consistent with it? Board stays
  rigid/supported/unchanged in size - no separation or sagging (that stays
  a separate, later atomic-action test). Exactly 1 edit call ($0.15), no
  video call. Success requires progression, board rigidity, AND the full
  composition preserve-list to all hold together. If both frames are
  approved together, the first/last-frame video-interpolation test (Wan
  2.1 FLF2V or Kling O1) becomes its own separate, later, explicitly gated
  experiment.
- **Seedance 2.0 benchmark, complete and PASSED**: `scripts/run_seedance_benchmark_test.py`
  established the quality ceiling this project is now benchmarking cheaper
  models against. Run for real: strong pass on accelerated construction
  progression, builder engagement, the ocean-cliff environment, natural
  environmental motion (waves), and reading as a genuine construction
  timelapse rather than a cinematic AI demo. Not a production-model
  decision - a one-time ceiling-setting benchmark.
- **Wan Turbo cost-down timelapse test, run for real (result pending
  review)**: `scripts/run_wan_turbo_timelapse_test.py` asked how much of
  the Seedance benchmark's feel survives at ~1/40th the cost on the
  existing $0.05 production-candidate baseline. Re-verification
  (explicitly requested, not assumed) found the Turbo endpoint's actual
  duration behavior differs from this project's original research:
  `num_frames` 81-100, default 81 (~5.06s), >81 billing at 1.25x - 15
  seconds is not achievable on this endpoint at any price, so the
  experiment targeted ~5s (81 frames, pinned explicitly in `WAN_TURBO`'s
  config) as the closest valid alternative at exactly $0.05. Prompt
  optimized for Wan Turbo's strengths (broad progression) rather than
  fine tool mechanics.
- **Wan Turbo 2-clip 480p timelapse test, run for real (result pending
  review)**: `scripts/run_wan_turbo_2clip_timelapse_test.py` extended the
  single-clip test to ~10s while staying strictly on the $0.05 flat-rate
  tier - two clips instead of one longer (more expensive) clip. Clip 2 is
  generated from clip 1's own last frame (extracted locally via
  `app/services/frame_extraction`, no image-generation call), so it
  continues clip 1's actual visual state rather than restarting
  independently; both clips share identical camera/attention/identity
  language, with clip 2's prompt targeting a visibly later structural
  stage than clip 1 and explicitly forbidding any reset. A new
  `app/services/video_assembly.concatenate_videos()` utility (ffmpeg
  concat filter) produces one review file from the two clips - a small,
  reusable piece of the eventual real assembly system, not the whole
  thing.
- **Wan Turbo 2-clip 720p timelapse test, run for real (result pending
  review)**: `scripts/run_wan_turbo_2clip_timelapse_720p_test.py` was a
  deliberately controlled, single-variable comparison against the 480p
  test - only resolution changed (480p->720p, $0.05->$0.10/clip) - to
  answer whether paying double per clip buys enough visible improvement
  to make 720p the high-volume production tier.
- **Wan Turbo verdict**: both Wan Turbo tests (slow, continuous,
  glitch-prone) were judged the wrong creative format entirely - not a
  resolution problem, a format problem. The successful Seedance 2.0 Fast
  benchmark (accelerated montage, natural jump/cut-like progression) is
  now the explicit creative template for all subsequent cost-down
  candidates, not either Wan Turbo test.
- **Wan 3.0 15s timelapse test V1, run for real - technical PASS, creative
  FAIL**: `scripts/run_wan3_15s_timelapse_test.py` tested whether a single
  continuous ~15s generation on a cheaper model (`alibaba/wan-3.0/image-to-video`,
  480p, $0.75 total) could reproduce the Seedance benchmark's accelerated-
  montage feel at roughly 1/5th its cost. First real submission hit
  exactly the kind of gap this project's "verify before spending"
  discipline is built to catch safely: rejected with fal.ai's own HTTP
  422 (`start_image_url` required, not the `image_url` the payload sent) -
  no charge occurred, fixed via the existing `image_param_name` mechanism.
  The corrected resubmission succeeded and visual quality was good enough,
  but the construction read as continuous and too slow - not the extreme,
  hard-cut timelapse feel that made the Seedance benchmark work. Root
  cause suspected: the imported Seedance prompt's own continuous-motion
  phrasing.
- **Wan 3.0 15s timelapse test V2, run for real - VALIDATED as the core
  generation approach**: `scripts/run_wan3_15s_timelapse_v2_test.py` kept
  every technical parameter from V1 identical and changed only the prompt -
  rewritten from scratch (not appended to V1's Seedance-derived prompt)
  around ~6 explicit "HARD TIME JUMP" transitions across the 15s, each
  showing a meaningfully more advanced construction state, with only brief
  activity bursts between jumps rather than continuous work. This fixed
  the pacing problem: the user confirmed Wan 3.0 standard 480p, prompted
  with an explicit hard-time-jump structure, is now the validated core
  generation method for the production video (superseding Wan Turbo
  entirely, and matching the Seedance benchmark's creative feel at roughly
  1/5th its cost).
- **Cross-angle continuity test, run for real - PASSED**:
  `scripts/run_cross_angle_continuity_test.py` isolated the single biggest
  unproven risk in the full-video plan (whether independently generated
  reference images for different camera angles can convincingly depict the
  same builder, cabin, and location) from every other variable, by
  generating exactly two still images - a wide three-quarter-rear view and
  an opposite-side three-quarter view - from one fixed "continuity bible"
  text block with only a camera-angle clause differing between the two
  prompts. User verdict: both images convincingly read as the same
  builder, same construction project, and same coastal location; cross-
  angle continuity is not geometrically perfect but is more than
  sufficient for this rapid-timelapse format. This validated the
  "shared bible + swapped clause" mechanism now used by every segment's
  reference image in Full Video #1 (see below). It also produced one new
  standing production rule: **synchronize every camera-angle change with
  a major temporal/construction-state jump** (never cut to a new angle at
  the same moment in time) - minor cross-angle geometric drift is far
  easier to miss when it coincides with an obvious story jump than when
  the viewer can compare "the same instant" from two angles.
- **Full Video #1, production spec finalized (current)**: with Wan 3.0 V2
  and cross-angle continuity both validated, the first full ~68s
  production video is now specified as **7 generated video segments**
  (Segment 1 was split into 1A and 1B so no single Wan 3.0 call has to
  perform the entire untouched-site -> floor-joist transformation):
  1A raw site->cleared (6s), 1B cleared->early foundation/floor (8s),
  2 floor deck & wall framing (12s), 3 wall framing advances - reuses the
  cross-angle test's own validated two-walls-framed state (11s), 4 roof &
  enclosure (11s), 5 exterior details (11s), 6 final reveal (9s, premium
  model). Every segment's shot SCALE varies, not just direction (wide
  environmental / medium construction / opposite-side three-quarter /
  closer work-action / elevated-environment-heavy / final hero-reveal),
  and every angle/scale change is synchronized with a construction-state
  jump per the rule above. One fixed "site bible" (builder identity, site
  geometry, ocean orientation, landmarks, lighting - see "Running the full
  video segment 1A test" below) is shared verbatim across all 7 segments'
  reference-image prompts; only a per-segment build-state clause (S0
  through S6, each one textually identical to the previous segment's own
  end-state, so hand-offs are byte-identical rather than re-described)
  and the camera clause change. **7 re-anchor images + 7 video generations
  = 14 total calls.** Cost: 7 x $0.15 images = $1.05; Wan 3.0 480p across
  segments 1A/1B/2/3/4/5 (6+8+12+11+11+11 = 59s) = $2.95; Seedance 2.0
  Fast 720p for segment 6 (9s, **no native audio requested** - the
  finished video's sound design is a separate later pass across the whole
  assembly, so paying for audio on one segment only to discard it would
  be pointless) = $2.18. **Total production cost: ~$6.18.** Segments are
  each their own independently-built, offline-verified, and separately
  approved script - never one monolithic run - so a problem in any one
  segment never risks the spend on segments after it. Assembly will use
  `app/services/video_assembly.concatenate_videos()`, extended with a
  normalization pass (scale all clips to a common 720x1280 canvas before
  concatenation, since segment 6's resolution differs from segments
  1A-5's) and with audio stripped from every clip pre-concatenation.
- **Segment 1A start frame V1, run for real - REJECTED**: the first
  `segment_1a_start_frame.jpg` had the right builder, site, and identity,
  but the camera was pitched too far downward - foreground ground/
  vegetation dominated the vertical frame while the ocean/cliff
  environment was compressed into the upper background. This mattered
  more than a typical composition nit: FORMA's visual identity requires
  the dramatic environment to be a major retention element alongside the
  transformation, not background scenery. The mandatory review gate (see
  "Running the full video segment 1A test" below) caught this before any
  video spend - the $0.30 video call was never made from the rejected
  image.
- **Segment 1A start frame V2, run for real - APPROVED and LOCKED**:
  `scripts/run_full_video_segment_1a_image_v2_test.py` changed ONLY the
  camera/composition clause - builder identity, site geometry, lighting,
  and the S0 untouched-construction-state text were imported directly from
  the V1 script, byte-identical, not retyped. New composition: camera at
  ~chest/eye height with a near-horizontal axis (not elevated/downward),
  horizon clearly visible, ~40-50% of the frame showing ocean/horizon/
  coastline, the builder occupying noticeably less of the frame, and
  explicit front-to-back depth (foreground worksite -> builder ->
  cliff/coast -> ocean/horizon). `segment_1a_start_frame_v2_candidate.jpg`
  is now the **canonical, locked** starting image for Segment 1A - not to
  be regenerated or modified. The rejected V1 image and the original
  `manifest.json` were both left untouched throughout.
- **Segment 1A, run for real - APPROVED and LOCKED**:
  `scripts/run_full_video_segment_1a_resume_video_test.py` completed the
  remaining Wan 3.0 video call from the locked V2 image; the user's
  verdict was that the generated video "looks excellent." Segment 1A is
  finished and must not be regenerated or modified.
- **Segment 1B, built and offline-verified (result pending review)**:
  `scripts/run_full_video_segment_1b_test.py` picks up exactly where
  Segment 1A ended (`SEGMENT_1A_END_STATE_S0_5`, imported byte-identical,
  not retyped) and advances to build state S1: a measured footprint,
  foundation piers, staged materials, and most of the floor joist system
  installed - still zero walls/roof/windows/doors. Carries forward
  Segment 1A's approved V2 visual language (chest/eye height,
  near-horizontal axis) at a somewhat closer scale, with ocean/horizon
  still occupying ~30-40% of the frame - a deliberately smaller share than
  1A's 40-50% only because the shot is tighter, never because the
  environment matters less. The hard-time-jump sequence was written so
  each of its 4 beats reads as a visually distinct stage (footprint marked
  -> foundations/materials staged -> first joists appear -> most joists
  installed) rather than several similar "more joists" shots, with varied,
  non-lingering builder activity (hammering, carrying, positioning,
  fastening) between jumps. Same mandatory image-review gate as 1A (not
  skippable by `--yes`) - the exact mechanism that caught 1A's V1
  composition problem before any video spend. See "Running the full video
  segment 1B test" below.
- **Segment 1B start frame, APPROVED and LOCKED; video resume script
  built and offline-verified (result pending review)**: the user exited
  at the review gate after the $0.15 image call, then approved that image
  (`segment_1b_start_frame.jpg`) separately.
  `scripts/run_full_video_segment_1b_resume_video_test.py` makes ONLY the
  remaining $0.40 Wan 3.0 video call, reusing that exact locked image (no
  Nano Banana Pro call) and importing the segment's already-approved
  video prompt completely unchanged (unlike segment 1A's resume, no
  emphasis sentence was added this time - the prompt was approved as-is).
  Validates against the segment's own `manifest.json` (image already
  recorded, video not yet) before submitting, then updates it in place.
- **Visual-truth-outranks-prompt-text rule, new standing rule**: Segment
  1B's real generated video was reviewed, and its actual appearance reads
  as a much smaller starter platform (~3m x 3m relative to the builder)
  than `SEGMENT_1B_END_STATE_S1`'s own prompt text implied - no exact
  footprint dimension was ever specified in that text, but the visual
  result still read smaller than intended. New standing rule: the
  ACTUAL generated output always outranks a prior segment's intended
  prompt text when establishing continuity for the next segment - a
  deliberate, one-time exception to the "always import the previous
  segment's end state byte-identical" pattern, applied in Segment 2 below.
- **New canonical footprint scale (~10m x 6m), locked from Segment 2's
  completed state onward**: the cabin is now a substantial modern
  structure, not the small shed-scale platform Segment 1B's real footage
  showed. Segment 1B's structure is understood as the *core/initial
  module* of this larger platform - nothing about 1B's locked video is
  redone; Segment 2 shows the expansion happening on-camera, via its own
  hard-time-jumps, with the original small platform staying visually
  recognizable throughout (never magically swapped for a larger one
  between cuts).
- **New standing FORMA rules**: **camera variation** (change
  observational angle at every hard-time-jump/build-state transition
  between segments, cycling through wide environmental / opposite
  three-quarter / occasional slightly-elevated angles to keep revealing
  new coastline); **landscape equity** (ocean/cliffs/horizon/golden-hour
  light must share real compositional weight with the structure in every
  segment, never just background scenery); **scale contrast**
  (deliberately dwarf the builder against both the structure and the
  landscape in some shots, to reinforce the project's and the location's
  scale).
- **Segment 2, built and offline-verified (result pending review)**:
  `scripts/run_full_video_segment_2_test.py` is entirely one
  transformation - the small ~3x3m starter platform expands, on-camera,
  into a substantially larger ~10m x 6m floor structure, several times
  its original size, with the original platform remaining visually
  recognizable throughout. No wall framing begins here - the completed
  large floor platform, held clean for the final ~1.5-2s, is this
  segment's own payoff (decking + walls rising is segment 3's payoff).
  First real implementation of the camera-variation rule: a substantially
  different angle from 1A/1B (opposite side of the site, a naturally
  elevated vantage point, but the camera axis kept near-horizontal rather
  than tilted down), revealing a fresh, compositionally major sweep of
  coastline. The builder is used aggressively as a scale reference - by
  the segment's end he reads as noticeably small against the completed
  platform. Same mandatory image-review gate as 1A/1B. See "Running the
  full video segment 2 test" below.
- **Segment 2 start frame, APPROVED and LOCKED; video resume script with
  a REVISED prompt, built and offline-verified (result pending review)**:
  the user exited at the review gate after the $0.15 image call, then
  approved that image (`segment_2_start_frame.jpg`) separately, along
  with a scale correction: rather than depending on absolute meter
  dimensions, the visible platform in the approved image is now the
  visual source of truth, and the target is described relative to it -
  approximately 2x width and 2x depth (~4x floor area), proportionate and
  not site-consuming. `scripts/run_full_video_segment_2_resume_video_test.py`
  makes ONLY the remaining $0.60 Wan 3.0 video call, reusing that exact
  locked image (no Nano Banana Pro call), with a **revised**
  `VIDEO_PROMPT_RESUME` - unlike segment 1B's resume (prompt reused
  unchanged), every absolute meter callout from the original script's
  prompt is replaced with framing relative to the actual image, while the
  camera clause, opening/closing holds, 4-beat hard-time-jump structure,
  and S2 end-state constraint (no decking/walls/roof/doors) are all
  otherwise unchanged. The manifest's standing `build_state_end` (still
  recording the project's ~10m x 6m canonical footprint fact) is left
  untouched - only the actual generation prompt for this call changed.
- **Segment 2, run for real - APPROVED and LOCKED**: `segment_2.mp4`
  came out excellent per user review. Segment 2's start image and video
  must not be regenerated or modified.
- **Segment 3, built and offline-verified (result pending review)**:
  `scripts/run_full_video_segment_3_test.py` is the moment the project
  transitions from a large open platform into an actual building: floor
  decking goes down, then wall framing begins and becomes substantial -
  deliberately NOT complete. The near-side wall ends up completely framed
  at full height end to end; an adjacent side wall gets only a
  substantial *horizontal portion* framed (at the same full stud height,
  never partial height) - progress on that second wall is represented
  purely by how much of its length is built. The ocean-facing side of the
  platform stays predominantly open throughout. No roof framing/
  sheathing, no siding, no installed windows/doors, no interior finishes
  yet. New three-quarter diagonal camera angle - looking down the
  platform's long axis toward the ocean, so the rising wall reads along
  one side of the frame rather than blocking the coastline - carries an
  explicit scale-preservation instruction (the platform must not appear
  smaller just because the camera angle changed, a direct safeguard
  against the same kind of scale-drift Segment 2 itself had to correct).
  Start state re-describes Segment 2's actual approved appearance using
  relative-scale language, not a byte-identical import of Segment 2's own
  original absolute-meter text - same one-time-deviation pattern used
  going into Segment 2. Same mandatory image-review gate as every earlier
  segment. Segments 1A, 1B, and 2 are untouched by this script. See
  "Running the full video segment 3 test" below.
- **Segment 3, STOPPED after generation - two fundamental pipeline
  failures identified**: reviewing the real Segment 3 output surfaced
  problems more important than any single segment. **Failure 1
  (continuity)**: the approved end of Segment 2 and the generated start of
  Segment 3 were materially different structures, not the same structure
  from a new angle - because every segment's start frame, all the way
  back to 1A, was generated by `NANO_BANANA_PRO_GENERATE`, which has no
  image-input parameter at all (confirmed directly in
  `app/providers/image/fal.py`'s `generate_image()` - the payload never
  includes an `image_url`). `SITE_BIBLE` + a build-state paragraph was
  never actual visual conditioning, only a description the model was free
  to reinterpret geometrically - fine for early, simple states, not
  sufficient once the structure gained real geometric specificity.
  **Failure 2 (causality)**: every segment's video prompt packed 3-5
  "HARD TIME JUMP" beats into one clip, each asserting a large state
  change with no per-frame link to the builder's actual motion - giving
  Wan every incentive to advance the structure independently of what the
  builder was depicted doing.
- **FORMA Continuity + Physical-Action Pipeline V2, proposed**: replaces
  text-conditioned re-anchors + multi-stage montage clips with a
  **checkpoint chain** - each checkpoint after the first is a REAL frame
  extracted from an approved video (`extract_last_frame()`, already
  proven in the Wan Turbo 2-clip tests), not a re-description; each
  generation covers ONE causally specific builder action, not a
  construction phase; time compression moves from in-model prompting to a
  local, free FFmpeg acceleration pass afterward. Camera-angle changes
  become rarer, deliberate events, ideally via small `NANO_BANANA_PRO_EDIT`
  nudges on a real checkpoint frame rather than large free re-generations
  (large swings remain higher-risk, per the same lesson V2A already
  taught about edit models: good at local changes, not global
  reorientation). Automated QA between checkpoints is proposed for later,
  not built yet - the manual review gate stays authoritative.
- **Validation Test #1 (causal action + FFmpeg timelapse), built and
  offline-verified (result pending review)**: before building the rest of
  Pipeline V2, `scripts/run_causal_action_test.py` isolates the single
  most important open question - can Wan 3.0 generate ONE believable,
  causally-grounded action (not a time-jump montage) that FFmpeg can then
  accelerate into a genuine timelapse feel? Starting image is the REAL
  last frame of the actual approved `segment_2.mp4`, extracted locally
  via `extract_last_frame()` (Segment 2's video file is only ever read,
  never modified) - no Nano Banana Pro call, no camera-angle change (the
  video prompt reuses Segment 2's own camera clause verbatim). The prompt
  contains zero "HARD TIME JUMP" or time-compression language - just one
  continuous, causally specific action (the builder installing several
  deck boards, each appearing only where and when his hands are actually
  working) at a believable pace. A new `app/services/video_assembly.
  accelerate_video()` function (ffmpeg `setpts` filter, real tests against
  the repo's fixture clip) then produces 2x/3x/4x accelerated versions
  locally from the same raw clip, without ever overwriting it, so the raw
  causal footage and all three accelerated versions can be compared side
  by side. See "Running the causal action test" below.
- **Validation Test #1, run for real - partially successful**: individual
  board handling was convincing (correct tool use, believable physical
  placement) - but ORDERED PROGRESSION failed: after ~2 correctly-installed
  boards, additional decking spontaneously appeared elsewhere on the
  platform, still breaking the construction illusion even though each
  individual action looked real.
- **CONSTRUCTION FRONTIER, new permanent FORMA principle**: every
  repetitive construction operation gets a single, strict spatial
  direction of progress, with exactly one active boundary at all times
  between completed work, the builder's current position, and untouched
  work still to come (decking: side-to-side; studs: end-to-end; siding:
  side-to-side or bottom-to-top; roof sheathing: edge-to-edge; glazing:
  sequential across the facade). Nothing may leapfrog the builder's
  position, and only one location is ever under construction at once.
  Longer repetitive phases are expected to eventually be built as chained
  clips (Clip A boards 1-3 -> extract last frame -> Clip B boards 4-6 ->
  ...), each continuing the same frontier from the previous clip's real
  final frame, then accelerated and concatenated - but that chaining
  itself is not yet validated; Test #2 below tests the frontier concept
  in a single clip first.
- **Validation Test #2 (construction frontier), built and offline-
  verified (result pending review)**: `scripts/run_construction_frontier_test.py`
  reuses Test #1's exact mechanism (same real Segment 2 last frame,
  freshly re-extracted; same camera; same no-Nano-Banana, no-time-jump-
  language, FFmpeg-deferred-acceleration approach) with a prompt rewritten
  around an explicit priority order matching the user's own: (1) ordered
  right-to-left progression, (2) the builder visibly causing it, (3)
  believable board handling, (4) fine tool detail - last, and the first
  thing to sacrifice if the model has to trade something off. The prompt
  states the frontier concept first and most emphatically ("the single
  most important visual behavior"), explicitly forbids any board
  "leapfrogging" the builder, and frames the target as a progress bar
  filling in behind him - deliberately de-emphasizing the fastening-detail
  language that got equal weight in Test #1's prompt. Board count is
  explicitly not a pass/fail factor. Same $0.50 hard cap, same 2x/3x/4x
  FFmpeg comparison. See "Running the construction frontier test" below.
- **Validation Test #2, run for real - PASSED**: ordered construction-
  frontier progression was substantially better than Test #1, and 4x
  acceleration was close to the target FORMA timelapse aesthetic. Four
  permanent principles locked in: **Construction Frontier** (one spatial
  direction, single active boundary), **Causal Labor** (builder stays
  physically attached to the boundary and visibly causes progress),
  **Sequential Progress** (new construction appears adjacent to existing
  work, never randomly), **Post-Production Timelapse** (believable motion
  first, FFmpeg creates the aggressive feel afterward - **~4x is now the
  baseline speed**, tunable per shot).
- **Validation Test #3 (checkpoint chaining), built and offline-verified
  (result pending review)**: `scripts/run_checkpoint_chain_test.py` tests
  whether a second Wan generation can continue the same construction
  frontier from a first clip's own real final frame, so two separately
  generated clips read as one continuous timelapse when accelerated and
  concatenated - the basis for eventually completing larger construction
  phases through checkpoint chains instead of one AI generation
  simulating an entire phase. Starting image ("Clip B") is the REAL last
  frame of Test #2's own RAW output (not the 4x file - propagation must
  always come from the unaccelerated generation, never a re-timed one),
  extracted freshly; Test #2's raw file is only ever read. Per explicit
  priority: **continuity across the Clip A -> Clip B seam is the #1
  success criterion**, ranked above how much additional decking Clip B
  completes - the video prompt opens by naming every element that must
  stay visually identical to the starting frame (existing decking,
  exposed joists, frontier position, camera/framing, structure geometry,
  builder appearance, site/background, lighting) before any construction-
  continuation instruction, and explicitly states that even one or two
  correctly placed boards is a good outcome if everything else stays
  continuous. Only the 4x version of Clip B is generated (the speed
  question was already settled by Test #2) and is then concatenated with
  Test #2's own real 4x file into `combined_preview_4x.mp4` - the primary
  output, meant to be judged as one continuous timelapse the way a viewer
  would. Same $0.50 hard cap. See "Running the checkpoint chain test"
  below.
- **FORMA Video #1, planning ("Waterfall Cave -> Glass Hideaway")**: the
  first genuinely publishable FORMA video, applying every principle
  validated on the cliff-cabin project (Construction Frontier, Causal
  Labor, Sequential Progress, Checkpoint Chaining, Post-Production
  Timelapse, Camera Chapters) to a new location. Locked production
  targets: 61-65s finished (~63s preferred), 120-160s total paid raw
  video (170s hard ceiling), 12-18 Wan generations, Wan 3.0 480p
  throughout (no premium model), variable per-shot acceleration in the
  ~2x-4x range chosen for finished-seconds-per-generation efficiency
  rather than a fixed factor. Camera-chapter transitions between the
  planned Foundation/Decking, Framing, and Glass/Exterior chapters will
  use `NANO_BANANA_PRO_EDIT` image-conditioned on each chapter's own real
  final frame (a conservative ~20-30 degree nudge) instead of a fresh
  text-to-image re-anchor - directly answering the Segment 3 continuity
  failure, since large-swing fresh regeneration was never reliable once a
  structure has real geometric complexity. This mechanism is unproven for
  camera changes specifically (only tested before for local corrections
  and, separately, large-swing full regeneration) - see the validation
  test below. Full production plan (chapter timeline, per-clip raw/accel/
  finished breakdown, cost estimate, sound design layer, risk analysis)
  is conversational/planning-stage only, not yet committed to any script.
- **Camera-transition edit validation test, PASSED**: before committing
  FORMA Video #1's architecture to the `NANO_BANANA_PRO_EDIT`-based
  transition mechanism, `scripts/run_camera_transition_edit_test.py`
  tested it in isolation against real, already-existing footage: the real
  last frame of the approved cliff-cabin Segment 2 video (chosen
  specifically for its existing structural complexity - platform, joists,
  posts), asking for ONE conservative ~20-30 degree camera nudge while
  preserving structure, landmarks, lighting, and builder identity. Real
  result: not pixel-perfect, but convincingly reads as the same physical
  structure from a nearby camera position - sufficient for the intended
  fast timelapse use. See "Running the camera transition edit test" below.
  **The camera-transition rule is now permanently locked**: conservative
  transitions may use `NANO_BANANA_PRO_EDIT`, always conditioned on the
  literal real final frame of the previous chapter, ~20-30 degrees maximum
  (no large rotations), every EDIT transition requires manual review
  before any downstream generation, and continuity always outranks camera
  variety. The cliff-cabin R&D phase is complete.
- **FORMA Video #1, Chapter A (Hook + Site Prep) implementation**: the
  first production chapter of FORMA Video #1, built as four completely
  isolated, hard-gated stages so a failed or unreviewed upstream clip can
  never automatically trigger downstream paid generation - `scripts/
  run_forma_v1_chapter_a_hook.py` (Stage A1: Hook, ~4s raw, uses the
  user's own already-approved waterfall-cave reference photo directly as
  the canonical starting image - never regenerated), `scripts/
  run_forma_v1_chapter_a_prep1.py` (Stage A2: Site Prep Clip 1, ~7s raw,
  runnable only after a separate "have you reviewed and approved
  hook_raw.mp4?" confirmation, distinct from and prior to the cost
  confirmation), `scripts/run_forma_v1_chapter_a_prep2.py` (Stage A3: Site
  Prep Clip 2, ~8s raw, same upstream-approval gate against Prep 1), and
  `scripts/run_forma_v1_chapter_a_assemble.py` (Stage A4: local-only
  FFmpeg acceleration + concatenation into `chapter_a_combined_preview.mp4`
  - no API calls, no spend). Two policies apply project-wide from here on:
  the approved reference photo (and, by extension, each chapter's real
  generated frames) is authoritative - no identity-correction edits unless
  there is a genuine severe problem, and the actual builder appearance,
  cave geometry, waterfall, and lighting visible in the footage govern
  future prompts, not an older textual description; and all Wan prompts
  are visual-only - no audio-generation language of any kind (Wan is run
  with no audio field; FORMA sound is a separate post-production layer).
  See "Running FORMA Video #1 - Chapter A" below.
- **Stage A2 (Site Prep Clip 1), real result: REJECTED**: visual quality
  was good, but the action didn't read as meaningful site preparation -
  the builder breaking/pulling at one rock was too small and symbolic a
  gesture to justify calling the site "prepared." This exposed a gap the
  Construction Frontier/Causal Labor principles alone didn't cover: they
  guarantee a progression reads as spatially coherent and causally
  connected, but not that the action itself is *substantial* enough to
  register as real transformation.
- **FORMA SITE PREP RULE, new permanent principle**: every prep stage must
  show (1) a clear physical obstacle, (2) a clear tool/machine designed to
  deal with it, (3) visible removal/transformation of that obstacle, and
  (4) a clearly more buildable site by the end. Vague hand-clearing or
  symbolic actions that leave too much to the model's imagination are no
  longer sufficient - the obstacle and the machinery addressing it must
  both be explicit in the prompt. For Waterfall Cave, Prep 1 and Prep 2
  were redesigned around a compact tracked mini excavator (operated by the
  builder, who can hand off manual clearing to the machine) that scoops
  loose rock/mud/debris into a visible pile, then levels the pad -
  ending with rough natural ground -> mechanically cleared, flattened
  construction pad. Redesigned prompts for `scripts/run_forma_v1_chapter_a_prep1.py`
  and `_prep2.py` re-verified offline (same mocked-transport dry runs,
  updated assertions for the new machine/obstacle/pile language); full
  suite still 88 passed. Not yet re-generated for real.
- **Prep 1 (mechanical excavator), real result: still rejected as the
  permanent formula**: visual quality was fine, but repeated scoop/swing/
  dump cycles into a static pile were judged weaker than a single
  continuous sweeping action. Prep 1 was redesigned again around a
  compact tracked skid-steer with a wide grading blade - PUSH -> CLEAR ->
  ADVANCE -> COMPLETE, a single sweeping frontier (cleared pad | machine/
  blade | rough site) rather than scoop cycles - generated for real and
  **APPROVED**. Prep 2 was then rewritten to continue the same approved
  blade machine from Prep 1's actual real last frame (ADVANCE ->
  PUSH/LEVEL -> SHIFT -> COMPLETE) and also approved. **Chapter A (Hook +
  Site Prep) is now fully approved** - Hook, Prep 1, and Prep 2 all keep
  their real generated footage; the blade-based prep formula replaces the
  excavator formula as the permanent FORMA site-prep approach going
  forward, whenever terrain allows a single sweeping machine action.
- **FORMA PHASE 1 STRATEGY PIVOT**: before continuing FORMA Video #1
  past Chapter A, adopted a permanent two-phase production strategy (see
  "FORMA production phases" above) - Phase 1 (audience growth, current)
  targets ~28-35s finished videos (~30-32s preferred) at lower cost and
  generation count, while the account builds toward TikTok Creator
  Rewards qualification; Phase 2 (monetization) returns to the original
  ~61-65s full-scale format once longer runtime materially matters for
  payout. This is a scale decision, not a quality one - every locked
  principle (Causal Labor, Construction Frontier, Checkpoint Chaining,
  FORMA Site Prep Rule, camera-transition rule) still applies.
- **FORMA Video #1, revised remaining production plan (Phase 1 scale)**:
  rebuilt the rest of Waterfall Cave -> Glass Hideaway around a ~31s
  total finished runtime instead of ~63s, keeping all approved Chapter A
  raw footage unchanged (no regeneration) and compressing the remaining
  chapters (Foundation, Decking, Framing, Glass Facade, Reveal) to one
  clip each instead of multi-clip chains, with "minimal finishing" folded
  into the tail of the Glass Facade clip rather than its own generation.
  Chapter A's own finished-seconds budget was then retuned down further,
  from ~9.1s to **~5.0s** (Stage A4's Hook/Prep1/Prep2 factors retuned to
  4.0x/3.5x/4.0x, a free local change - no regeneration, no cost change),
  specifically to free screen time for Foundation and Decking rather than
  the Hook/Prep setup - "don't compromise on the timelapse" means keeping
  the actual build stages unhurried, not the establishing chapter. Freed
  time went to Foundation (7s raw / 1.27x -> 5.5s finished) and Decking
  (7s raw / 1.27x -> 5.5s finished, checkpoint-chained from Foundation's
  real last frame), both intentionally close to real-time so the causal
  build reads clearly rather than rushed; Framing (8s raw/2.0x -> 4.0s),
  Glass Facade (8s raw/2.0x -> 4.0s), and Reveal (8s raw/~1.14x -> 7.0s)
  are unchanged from the original revised plan. 5 remaining Wan video
  generations + 3 camera-transition `NANO_BANANA_PRO_EDIT` calls, ~38s
  remaining raw video, ~$2.35
  remaining estimated cost (~$3.30 total for the whole video including
  the $0.95 already spent on Chapter A). Planning only - not yet
  implemented as scripts, no paid calls made.
- **FORMA Video #1, Chapter B (Foundation/Floor) preflight and
  implementation**: Chapter B's Camera B transition and Foundation clip,
  built with the same hard-gate architecture as Chapter A - `scripts/
  run_forma_v1_chapter_b_camera_edit.py` (Stage B0: `NANO_BANANA_PRO_EDIT`
  camera nudge conditioned on the real extracted last frame of Chapter
  A's approved `site_prep_clip2_raw.mp4`, per the locked camera-transition
  rule) and `scripts/run_forma_v1_chapter_b_foundation.py` (Stage B1:
  Foundation, a single bounded causal operation - foundation posts one at
  a time, in one direction - explicitly excluding decking, framing,
  walls, and glass, which are separate later stages). Foundation is only
  eligible to run after Stage B0's edit is explicitly approved via its
  own upstream-approval gate, distinct from the cost-confirmation gate.
  See "Running FORMA Video #1 - Chapter B" below. Framing was flagged as
  the highest-risk compressed stage in the shorter Phase 1 plan and will
  need its own constrained, single-frontier design when reached - not yet
  built.
- **Stage B1 (Foundation, vertical posts), real result: REJECTED as a
  design, not a quality problem**: after studying real reference TikTok
  construction-timelapse footage, the vertical-post foundation concept
  was judged visually inappropriate for Waterfall Cave -> Glass Hideaway,
  and continuous-phase generation in general was judged too slow/costly
  compared to how the reference actually paces a build (see "FORMA
  jump-cut grammar" above). The generated clip is discarded and must not
  be used downstream; its $0.35 spend is sunk. Camera B0's edit
  (`camera_b_edit.jpg`) is unaffected and remains valid - it becomes the
  starting image for the redesigned floor-structure mechanism shot below
  instead of the rejected vertical-post clip.
- **FORMA Video #1, remaining shots redesigned around the jump-cut
  grammar (planning only)**: replaces the vertical-post Foundation/
  Decking/Framing/Glass/Reveal plan with a horizontal structural sequence
  (cleared pad -> perimeter/floor frame -> wall framing -> glass ->
  final detail -> reveal), each phase demonstrated in one short Wan
  mechanism clip and then jump-cut to completed via
  `NANO_BANANA_PRO_EDIT`, per the mechanism-clip + EDIT architecture
  above. 5 remaining Wan generations (29s raw, ~$1.45) + 3
  advance-and-nudge edits (~$0.45) = **~$1.90 remaining**, targeting
  ~23.5s finished across the 5 clips (~28.5s total video with Chapter
  A's ~5s). Not yet implemented as scripts, no paid calls made - the
  advance-and-nudge edit mechanism itself is flagged as unvalidated and
  a small real test is recommended before committing to it at scale.
- **Compound edit validation test, built and offline-verified (result
  pending review)**: before committing FORMA Video #1's jump-cut
  architecture to the advance-and-nudge edit mechanism,
  `scripts/run_edit_advance_completion_test.py` tests it in isolation
  against real, already-existing cliff-cabin footage: the real last frame
  of the Checkpoint Chain Test's own raw output (chosen for its
  partially-decked, exposed-joist floor), asking for ONE compound edit
  that both completes the visible decking phase and applies a
  conservative ~15-20 degree camera nudge, while preserving structure,
  landmarks, lighting, and builder identity and introducing no next-phase
  elements. Exactly 1 image-edit call, no video call, no other file
  touched. See "Running the compound edit validation test" above.
- **FORMA Video #1 pivot: cliffside cabin becomes the first real posted
  video**: after studying the reference TikTok footage, the cliffside
  build (Segments 1A/1B/2, plus the passed Construction Frontier decking
  test) was judged simpler, more validated, and lower-risk than Waterfall
  Cave, which becomes a later project. See "FORMA Video #1 pivot" above.
- **Cliffside Video #1, revised ~30-32s production plan (planning only)**:
  reuses four already-approved, already-paid-for real clips as the
  existing-material portion of the video (literal cuts/concatenation, no
  new continuity mechanism needed - each is independently approved
  footage): Segment 1A (6s raw/1.5x->4.0s, coastal establishing beat),
  Segment 1B (8s raw/2.0x->4.0s, foundation/joists), Segment 2 (12s
  raw/2.2x->5.5s, platform expansion - the strongest visual beat, given
  more finished screen time), Construction Frontier Test's decking clip
  (10s raw/2.5x->4.0s, right-to-left decking, ends with joists still
  partially exposed) - ~17.5s total, free to assemble via `scripts/
  run_cliffside_video_1_rough_assembly.py` (see above). Three NEW jump
  cuts complete the story per the FORMA jump-cut grammar: (1) EDIT -
  decking-completion + modest camera nudge, conditioned on the
  Construction Frontier Test's own real last frame (the same mechanism
  the compound edit validation test proved, redirected to this real,
  confirmed-existing source rather than the unconfirmed Checkpoint Chain
  Test output); (2) a new Framing mechanism clip (6s raw/1.5x->4.0s,
  demonstrates 1-3 studs only, the highest-risk compressed stage,
  constrained to one frontier) followed by an EDIT - framing-completion +
  modest camera nudge; (3) a new Finishing mechanism clip (5s raw/
  1.3x->3.8s, demonstrates one window/door installation) followed by an
  EDIT - finishing-completion (full windows/door/roof done). The Reveal
  (7s raw/1.1x->6.4s, in-generation camera pull-back, no edit - per the
  already-locked safest-reveal method) runs directly from the finishing-
  completion edit's own image. Total: ~31.7s finished, 3 new Wan
  generations (18s raw, ~$0.90) + 3 new edits (~$0.45) = **~$1.35
  remaining generation cost**. Not yet implemented as scripts beyond the
  free rough assembly above - no paid calls made.
- **Cliffside Video #1, Part 2 (Framing -> Glass -> Reveal) built and
  offline-verified (result pending review)**: a construction-spec-driven
  rewrite of the remaining ~14s, with exact dimensions (12x16ft footprint,
  8ft walls, 10-11ft roof peak, 3-4ft x 7-8ft glass panels) so nothing
  important is left to the model's imagination - see "Cliffside cabin
  permanent structure definition" and "Running Cliffside Video #1, Part 2"
  above. Originally 7 hard-gated stages including a dedicated Final Detail
  shot ($1.60 total); the Final Detail shot was then cut on cost/pacing
  grounds (a 5s/$0.25 generation for one finishing gesture didn't earn
  its screen time in a ~30s video) - the Reveal now runs directly off the
  exterior-completion edit's own image, no intermediate video checkpoint.
  6 hard-gated stages (1 precondition edit + 2 DEMONSTRATE/JUMP-CUT pairs
  + a no-edit Reveal sourced straight from the last edit), **$1.35
  total**. Not yet run for real - no paid calls made.
- **Cliffside Video #1, complete (30.63s) - reviewed as a finished piece,
  jump-cut grammar corrected to v2**: the finished proof-of-concept
  surfaced that v1's grammar (demonstrate 1-3 repetitions, then jump-cut
  to the whole phase complete) reads as "before/after images," not
  watching a house get built - clearest in the glass phase (one panel ->
  cut -> entire exterior finished). Replaced with the FORMA 90% Process
  Rule and related corrections - see "FORMA jump-cut grammar (permanent
  project note, v2 - supersedes v1)" above. Also locks: optimize for
  visible completion per dollar rather than API-call count (fewer,
  longer, more aggressively accelerated clips over many short ones),
  3x-5x+ acceleration once construction begins, a required interior-
  design/furnishing phase for any habitable structure, and a shorter
  reveal (~3.5-4.5s of a ~30-32s video, down from Video #1's 6+s).
- **FORMA Video #2 concept planned: Turquoise Alpine Lake -> Modern Glass
  A-Frame Hideaway (planning only, no paid calls)**: applies the v2
  grammar to a new location (dramatic peninsula/lakeshore, glacial-blue
  water, snowcapped mountains, evergreen shoreline) and a compact A-frame
  structure (~10-12ft wide x 14-16ft long, ~12-14ft peak, steep
  symmetrical roof, dark cladding, large lake-facing glass). 8 Wan
  generations + 6 Nano Banana Pro calls (1 initial site-reference image +
  5 phase-completion/camera-transition edits), ~87s raw video, targeting
  ~29.6s finished (opening/prep, base/floor, floorboards, A-frame rib
  framing as the hero moment, roof/cladding, glass facade, interior
  furnishing, then an interior-to-exterior pull-back reveal). Baseline
  cost ~$5.25 against a $6.50 hard ceiling, leaving a ~$1.25 retry
  reserve. Not yet implemented as scripts - no paid calls made.
- **Milestone 3+**: once the physical-interaction and composition problems
  are solved well enough and a production model is chosen, implement the
  Stage/Clip architecture, the hybrid continuity system (structured build
  state + reference frames + occasional re-anchoring), sound/ASMR
  metadata, per-shot model/budget tiers, voiceover, FFmpeg assembly with
  aggressive trimming, captions, AI QA (frame-sampled morphing/continuity/
  composition checks against the flags above), a review dashboard, and
  eventually publishing - see the project plan for the full list. None of
  this is implemented yet.
