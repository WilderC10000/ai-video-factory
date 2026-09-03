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

One real difference from the standard model: **Turbo's output is a fixed
~4 seconds (65 frames), not the ~5 seconds we'd been assuming** - duration
isn't a parameter you can set on this endpoint, only resolution is. That's
a minor pacing change (a 12-shot video becomes ~48s instead of ~60s) and no
architectural problem - `Shot.target_duration_seconds` stays a planning
value; what a provider actually delivered is on the `VideoJob` row. No
technical reason not to use Turbo.

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
FalVideoProvider(WAN_TURBO)      # default - $0.05/video flat @480p
FalVideoProvider(WAN_STANDARD)   # per-second alternative, e.g. for one important shot
FalImageProvider(FLUX_SCHNELL)   # default
```

Adding a future fal.ai model (or upgrading one shot to Kling/Veo later)
means adding one more named config, not touching `video_job_service.py`,
the routers, or anything else that calls `VideoProvider`.

**These real adapters are written and locally tested (10 tests, using
`httpx.MockTransport` to simulate fal.ai's documented request/response
shapes with zero network calls and zero cost) but are NOT wired in as the
active provider anywhere in the app** - `routers/projects.py` still uses
the mocks. They have never been executed against the live API: outbound
access to fal.ai is blocked from this development environment, so their
first real invocation will be the approved test itself.

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
  see "Running the continuity test" below) or to regenerate the mock
  providers' placeholder fixtures. Not required for anything else -
  the mock/API/demo flows don't need it. Install from
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
- **Continuity probe (current)**: `scripts/run_continuity_test.py` tests
  whether last-frame propagation holds a construction project visually
  consistent (same worker, same location, same developing structure)
  across 3 sequential Wan Turbo generations, and how much drift shows up.
  Not yet run for real - built and verified offline only. Next is running
  it locally and reviewing the 3 clips for continuity/drift.
- **Milestone 3+**: once continuity is validated at 3 shots, scale to the
  full ~60-75s / 13-16 shot architecture, add voiceover, FFmpeg assembly,
  captions, AI QA, ChatGPT+Claude collaboration, a review dashboard, and
  eventually publishing - see the project plan for the full list.
  Upgrading specific important shots to a premium provider (Kling/Veo/etc.)
  later is a config change, not a rewrite, thanks to the provider interface.
