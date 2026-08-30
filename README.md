# Skylark Drones — monday.com Business Intelligence Agent

A conversational agent that answers founder-level BI questions ("How's our
pipeline looking for the Mining sector?") by querying two live monday.com
boards — **Deals** (sales pipeline) and **Work Orders** (project execution) —
cleaning the notoriously messy underlying data on the fly.

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
export MONDAY_API_TOKEN=your_token_here
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
cp .env.example .env   # fill in the four values
docker build -t skylark-agent .
docker run --env-file .env -p 8000:8000 skylark-agent
```

Open http://localhost:8000.

### 4. Deploy

Push to any container host that builds from a Dockerfile (Render, Railway,
Fly.io). Set the same four environment variables in the host's dashboard —
nothing else is required.

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
