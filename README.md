# AI Video Factory

A system for producing realistic, AI-generated short-form "transformation" videos
(e.g. "he buried a private jet and turned it into an underground bunker") for
TikTok/YouTube Shorts/Reels, with persistent per-project state, a continuity
bible to keep every shot visually consistent, swappable AI providers, and
built-in cost tracking.

This repo is being built incrementally, milestone by milestone. **We are
currently on Milestone 1**: a local application that can create a project,
run it through concept -> script -> storyboard using a free mock AI provider,
and store everything in SQLite. No paid API calls happen anywhere in this
milestone.

## How it's organized

```
app/
  main.py              FastAPI application entrypoint
  config.py            All settings, loaded from environment variables / .env
  db.py                SQLAlchemy engine/session setup
  models/project.py    Database tables: Project, Shot, CostRecord
  schemas/project.py   API request/response shapes (Pydantic)
  providers/           Swappable AI provider interfaces
    base.py              Abstract LLM/Video/Image/Voice provider classes
    llm/mock.py           Free, deterministic mock LLM (used until Milestone 8)
  services/
    project_service.py  All business logic: state transitions, continuity
                         inheritance, cost recording. The API and CLI scripts
                         are thin wrappers around this.
  routers/projects.py  HTTP endpoints
scripts/
  seed_demo_project.py Runs one project end-to-end from the terminal, no server needed
tests/                 pytest suite (service layer + HTTP API)
data/                  SQLite database + per-project files (gitignored)
```

**Why it's split this way:** `services` is where every decision actually
happens (create a project, advance it to the next stage, record what it
cost). `models` is what gets saved to the database. `providers` is the
"who actually generates the content" layer - swapping the mock LLM for a
real OpenAI/Anthropic provider later means adding one new file, not
rewriting the app. `routers` just exposes `services` over HTTP so a future
dashboard (or ChatGPT/Claude collaboration, or a queue worker) can call it.

## Project state machine

Each project moves through: `IDEA -> CONCEPT_APPROVED -> SCRIPT_READY ->
STORYBOARD_READY -> ...` (later milestones add `KEYFRAMES_READY`,
`VIDEO_RENDERING`, `VIDEO_QA`, `VOICE_READY`, `EDITING`, `FINAL_QA`,
`READY_FOR_REVIEW`, `APPROVED`, `PUBLISHED`, `FAILED`). Each transition is
its own function in `project_service.py` and its own API endpoint, so any
step can be re-run without restarting the whole project. Individual shots
have their own status too (`PENDING -> PROMPT_READY -> GENERATING ->
GENERATED -> QA_PASSED/QA_FAILED`), so a single bad shot can be
regenerated on its own once real video generation exists (Milestone 2+).

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
type, cost in USD), even though it's always `$0.00` right now since only
the mock provider exists. `Project.total_cost_usd` sums these. This means
the moment a real paid provider is added, cost tracking already works -
no schema changes needed.

## Requirements

- Python 3.11+
- No paid API keys needed for Milestone 1.

## Setup

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env   # defaults are fine as-is for Milestone 1
```

## Running the demo (no server needed)

This runs one project through the entire Milestone 1 pipeline from the
terminal, using the free mock AI provider:

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

Notable settings already wired into the data model (not yet enforced -
that's Milestone 9's job):

- `FACTORY_PAUSED` - a global kill switch checked before any generation step.
- `MAX_SPEND_PER_PROJECT_USD`, `MAX_DAILY_SPEND_USD`,
  `MAX_REGENERATIONS_PER_SHOT` - spending/retry guardrails.

## What's next

- **Milestone 2**: implement a real `VideoProvider` and generate one actual
  AI video clip for a single shot. This is the first point where any money
  gets spent - it will not happen without your explicit go-ahead, and
  we'll pick a specific provider together first based on price/quality.
- **Milestone 3+**: multi-shot async generation/polling, voiceover, FFmpeg
  assembly, captions, AI QA, ChatGPT+Claude collaboration, a review
  dashboard, and eventually publishing - see the project plan for the full
  list.
