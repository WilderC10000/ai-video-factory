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
researched the cheapest *credible* (not just cheapest possible) options.

**Caveat on the numbers below:** fal.ai's own site is blocked by this
environment's network policy, so these prices come from several
independent third-party trackers as of the research date, not fal.ai's own
pricing page directly. They're consistent across sources, but **you should
confirm the live price on fal.ai's dashboard before approving any real
spend** - AI provider pricing changes often.

### The cheapest credible pair we found

| Purpose | Model | Price | Why this one |
|---|---|---|---|
| Reference image | **FLUX.1 [schnell]** via fal.ai | $0.003/megapixel (rounds up to nearest MP; our 576x1024 default = 1MP) | Cheapest credible text-to-image on fal.ai; supports 9:16 |
| Video clip | **Wan 2.2 A14B (image-to-video, 480p)** via fal.ai | $0.04/video-second | Cheapest *image-to-video* tier that still has a real quality reputation (14B-parameter model); supports 9:16, ~5s default output |

A cheaper Wan 2.2 5B tier exists (~$0.15/video flat, so actually *more*
than A14B works out to at 480p) and even cheaper models exist (Seedance
2.0, plain Wan 2.2 at ~$0.02/sec) - those are worth trying later purely to
drive cost down further, but A14B at 480p is our starting recommendation
because it's a meaningfully better-regarded model for a similar price.

### The optimized (cost-first) pipeline

Compared to a quality-first setup, we deliberately made these choices:

1. **480p, not 720p/1080p** for video - roughly half the cost of the next
   tier up, and resolution matters less for a first "does this concept get
   views" test than for a polished final product.
2. **Image-to-video, not text-to-video** - the reference image is a very
   small fraction of the cost (~1-2%) but meaningfully helps continuity,
   which is one of your core product requirements.
3. **A reference image is generated once per shot and reused** on every
   regeneration - `regenerate_shot_video()` never re-generates the image,
   only the video, unless you explicitly ask for a new image.
4. **No native audio from the video provider** - Wan/Kling audio add-ons
   roughly double the price; we'll add voiceover separately later
   (Milestone 4) with a provider chosen the same cost-conscious way.
5. **~5 second shots** (Wan's native default) rather than paying for
   longer clips per generation.

### Estimated costs

Based on our current 12-shot storyboard template (~60 seconds of finished
video) at the rates above: **1 reference image = $0.003, one 5-second clip
= $0.20, one shot (image + video) = $0.203.**

| | Cost |
|---|---|
| 1 reference image | $0.003 |
| 1 five-second video clip | $0.20 |
| 1 finished ~60s video (12 shots, 0% regeneration) | **$2.44** |
| 10 finished videos | $24.36 |
| 100 finished videos | $243.60 |

These cover image + video generation only - the biggest cost driver.
LLM costs stay $0 (mock provider through Milestone 8), and
voiceover/assembly (Milestones 4-5) aren't built yet so aren't included.

**With regeneration.** Because a regenerated shot reuses its existing
reference image, a regeneration only costs the video portion again
($0.20), not the full $0.203 - reflecting how this architecture actually
behaves, not a worst-case guess:

| Regeneration rate | Cost / video | Cost / 10 videos | Cost / 100 videos |
|---|---|---|---|
| 0% | $2.44 | $24.36 | $243.60 |
| 20% | $2.92 | $29.16 | $291.60 |
| 50% | $3.64 | $36.36 | $363.60 |

(Even in the worst case where a regeneration re-does the image too, these
numbers barely move - the image is under 2% of a shot's cost.)

### The one real test we're proposing

To go from "estimated" to "confirmed," the smallest useful real-money test
is **one reference image + one 5-second Wan video clip**:

- Image: $0.003 (FLUX schnell, ≤1MP)
- Video: $0.04/sec x ~5s = ~$0.20, with a safety margin to ~$0.24 in case
  fal.ai bills the extra fraction of a second up to a full 6th second
  (Wan's actual default output is ~5.06s)

**Maximum dollar amount required: $0.25 total**, expected actual cost
closer to $0.20-$0.21. We will not submit this test, or any other paid
call, without your explicit go-ahead - and we'll show you fal.ai's actual
quoted price at submission time before it's charged.

## Requirements

- Python 3.11+
- `ffmpeg` (used only to pre-generate the mock providers' tiny placeholder
  files, already committed to the repo at `app/providers/video/fixtures/mock_clip.mp4`
  and `app/providers/image/fixtures/mock_reference.jpg` - you don't need
  ffmpeg installed just to run the app, only if you want to regenerate those fixtures)
- No paid API keys needed through Milestone 2.

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

- **Milestone 2, remaining**: implement the real fal.ai-backed `VideoProvider`
  (Wan 2.2 A14B) and `ImageProvider` (FLUX schnell) adapters - straightforward
  now that the interfaces are proven against mocks - and run the single
  approved test generation (see "Cost model" above). Will not happen
  without your explicit go-ahead on that specific spend.
- **Milestone 3+**: full multi-shot async generation across an entire
  project, voiceover, FFmpeg assembly, captions, AI QA, ChatGPT+Claude
  collaboration, a review dashboard, and eventually publishing - see the
  project plan for the full list. Upgrading specific important shots to a
  premium provider (Kling/Veo/etc.) later is a config change, not a
  rewrite, thanks to the provider interface.
