# Skylark Drones — monday.com Business Intelligence Agent

A conversational agent that answers founder-level BI questions ("How's our
pipeline looking for the Mining sector?") by querying two live monday.com
boards — **Deals** (sales pipeline) and **Work Orders** (project execution) —
cleaning the notoriously messy underlying data on the fly.

**Live demo:** https://skylark-bi-agent-p02p.onrender.com
(hosted on Render's free tier — the first request after a period of
inactivity may take ~30-60s to wake the instance)

## Architecture

```
┌────────────┐      ┌──────────────────────────────┐      ┌──────────────┐
│  Browser    │─────▶│  FastAPI (app/main.py)       │─────▶│  Gemini LLM   │
│  chat UI    │◀─────│  agent.py: tool-calling loop │◀─────│  (free tier)  │
└────────────┘      └───────────────┬───────────────┘      └──────────────┘
                                     │ tool calls
                                     ▼
                     tools.py (query/aggregate functions)
                                     │
                                     ▼
                     normalize.py (dates, nulls, sectors,
                                    leaked-header detection)
                                     │
                                     ▼
                     monday_client.py (GraphQL, paginated reads)
                                     │
                                     ▼
                          monday.com boards (live)
```

**Key design choice:** the boards are imported close to the raw CSVs (see
`import_csv_to_monday.py`) and *all* cleaning happens at query time in
`normalize.py`. This means the agent's data-resilience claims are actually
exercised on every request, not baked away during a one-time import.

## Setup

### 1. Import the data into monday.com

```bash
cd backend
pip install -r requirements.txt
export MONDAY_API_TOKEN=your_token_here      # Windows PowerShell: $env:MONDAY_API_TOKEN="your_token_here"
python import_csv_to_monday.py
```

This creates two boards ("Deals", "Work Orders"), infers a column type
(`date` / `numbers` / `text`) per source column, and imports every row. It
prints the two board IDs at the end — copy them into your `.env`.

### 2. Get a free LLM key

Go to https://aistudio.google.com/app/apikey, create a free API key (no
billing required), and set it as `GEMINI_API_KEY`.

### 3. Run locally

```bash
cp .env.example .env   # fill in MONDAY_API_TOKEN, GEMINI_API_KEY, DEALS_BOARD_ID, WORK_ORDERS_BOARD_ID
docker build -t skylark-agent .
docker run --env-file .env -p 8000:8000 skylark-agent
```

Open http://localhost:8000.

### 4. Deploy

Push to any container host that builds from a Dockerfile (this project is
deployed on **Render**'s free tier). Set the same environment variables in
the host's dashboard — nothing else is required. `GEMINI_MODEL` is optional
(defaults to `gemini-2.0-flash`); set it explicitly if that model is ever
deprecated, e.g. `GEMINI_MODEL=gemini-3.6-flash`.

## Approach

I inspected the two source CSVs directly before writing any code, found two
concrete data-quality issues (52% of deals missing a value; a literal
duplicate header row embedded mid-data in the deal CSV), and designed the
cleaning logic around problems that actually existed rather than generic
null-handling. The system is a standard tool-calling LLM agent: the model
never sees raw monday.com data, only the output of purpose-built query/
aggregate functions that return cleaned data plus explicit data-quality
caveats — so the agent can't accidentally present a clean number built on
messy input.

## AI tools used

- **Claude (Anthropic)** was used throughout the build for architecture
  planning, writing all backend code (FastAPI app, monday.com GraphQL
  client, normalization logic, agent/tool-calling loop), debugging
  deployment issues, and drafting this documentation.
- **Google Gemini** (free tier, `gemini-3.6-flash`) is the LLM actually
  powering the deployed agent's conversational responses at runtime — used
  instead of the Anthropic API because no Claude API key was available
  during the build window. See `backend/app/llm.py` — the provider is
  isolated behind a neutral interface so swapping to Claude is a one-file
  change.
- No AI-generated code was used unreviewed — every file was read, tested
  against the real imported monday.com boards, and iterated on based on
  actual error output, not assumed to work.

## Assumptions & trade-offs (summary — full detail in DECISION_LOG.md)

- Missing deal/work-order values are treated as **unknown**, never as zero;
  every aggregate response states how many records had no value.
- monday.com access uses the direct GraphQL API rather than the Platform
  MCP server, prioritizing a simple single-container deploy over living
  inside monday.com as a first-class connected agent.
- Cleaning happens at **query time**, not at import time, so the "handle
  messy data" requirement is exercised on every real request.
- Board columns were imported as generic text/date/numbers rather than
  monday's semantic status/dropdown types, trading a more native-looking
  board for faster setup within the time budget.

## Challenges faced

Beyond the expected data-cleaning work, deployment surfaced several real
issues (see the Troubleshooting section below for the technical detail on
each): a Docker/WSL2 startup failure on Windows, a stray whitespace
character in an environment variable that produced a misleading "invalid
API key" error, a wrong *type* of Google API key that passed every
surface-level validation check, a FastAPI route-ordering bug that made a
working endpoint return 404, and — most seriously — a credential that was
briefly hardcoded into a source file during live debugging. That last one
was caught by grepping the full git history for key-prefix patterns before
it reached GitHub; the fix was to wipe local git history and start clean
rather than surgically rewrite commits, and both credentials were
regenerated afterward regardless of whether the push had gone through.

## Potential improvements

See `DECISION_LOG.md` → "What I'd do differently with more time" for the
full list, including entity resolution across the two boards (e.g.
"which clients have an open deal but no active work order"), webhook-based
cache invalidation instead of a flat TTL, and automated tests against
recorded GraphQL fixtures.

## Troubleshooting

Issues actually hit while deploying this project, in case they recur:

- **`No API_KEY or ADC found`** — the Gemini SDK received an empty or
  malformed key. Double-check the env var value in your host's dashboard
  has no leading/trailing whitespace (easy to introduce via copy-paste),
  and that it's a genuine **Gemini Developer API key** from
  [aistudio.google.com/app/apikey](https://aistudio.google.com/app/apikey) —
  it should start with `AIzaSy...`. Other Google token types (OAuth access
  tokens, etc.) look superficially similar but will fail the same way.
- **`404 ... model is no longer available`** — Google occasionally
  deprecates model names. Set `GEMINI_MODEL` to whatever replacement the
  error message suggests.
- **Env var changes not taking effect** — most hosts (Render included)
  redeploy automatically on a git push or on saving new environment
  variables, but it's worth explicitly waiting for the deploy to show
  "Live" (check the platform's build logs for `Uvicorn running on...`)
  before retesting — testing against an in-progress deploy will hit the
  stale, previous container.

## What each file does

| File | Responsibility |
|---|---|
| `backend/import_csv_to_monday.py` | One-time: creates boards + columns, imports CSV rows |
| `backend/app/monday_client.py` | GraphQL wrapper, paginated reads, retries on rate limits |
| `backend/app/normalize.py` | Date/number/text cleaning, sector canonicalization, leaked-header-row detection |
| `backend/app/tools.py` | Query/aggregate functions exposed to the LLM, each returning data + caveats |
| `backend/app/llm.py` | Provider-agnostic LLM interface (Gemini implementation) |
| `backend/app/agent.py` | System prompt + tool-calling loop |
| `backend/app/main.py` | FastAPI `/api/chat` endpoint + static frontend |
| `frontend/index.html` | Chat UI |

See `DECISION_LOG.md` for assumptions, trade-offs, and what I'd change with
more time.
