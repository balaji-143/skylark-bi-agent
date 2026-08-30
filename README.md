# Skylark Drones — monday.com Business Intelligence Agent

A conversational agent that answers founder-level BI questions ("How's our
pipeline looking for the Mining sector?") by querying two live monday.com
boards — **Deals** (sales pipeline) and **Work Orders** (project execution) —
cleaning the notoriously messy underlying data on the fly.

**Live demo:** https://skylark-bi-agent-p02p.onrender.com
(hosted on Render's free tier — the first request after a period of
inactivity may take ~30-60s to wake the instance)

## Architecture

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

## Troubleshooting

Issues actually hit while deploying this project, in case they recur:

- **`No API_KEY or ADC found`** — the Gemini SDK received an empty or
  malformed key. Double-check the env var value in your host's dashboard
  has no leading/trailing whitespace (easy to introduce via copy-paste),
  and that it's a genuine **Gemini Developer API key** from
  aistudio.google.com/app/apikey — it should start with `AIzaSy...`.
  Other Google token types (OAuth access tokens, etc.) look superficially
  similar but will fail the same way.
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