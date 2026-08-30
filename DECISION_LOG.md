# Decision Log

## Key assumptions

- **"This quarter" / date ranges are ambiguous in the source data.** There's
  no explicit fiscal-year field. The agent is instructed to ask a clarifying
  question when a date range materially changes the answer, and to state an
  assumption (calendar quarter) otherwise rather than blocking.
- **Deal value and work-order amounts with a blank cell are treated as
  "unknown," never as zero.** 181/346 deal rows (52%) have no recorded
  value. Silently summing with blanks-as-zero would understate pipeline size
  without saying so; every aggregate tool returns a `deals_missing_value` /
  caveat field, and the agent is instructed to always surface it.
- **A literal duplicate-header row found mid-data in the Deal CSV** (row 50 —
  every cell equals its own column name, an xlsx→csv export artifact from a
  second table) is detected and excluded at query time (`normalize.is_leaked_header_row`),
  not silently kept as a garbage record.
- **Sector spelling was already fairly consistent** in the source data, so
  `SECTOR_CANONICAL` is a light lowercase-match map rather than fuzzy
  matching — kept simple, but structured so a fuzzy-match step could be
  dropped in later without touching callers.

## Trade-offs chosen and why

| Trade-off | Chosen | Alternative considered | Why |
|---|---|---|---|
| monday.com access | Direct GraphQL API | Platform MCP server (`all_monday_api`) | Simpler single-service deploy; MCP would be the better choice if this agent needed to live *inside* monday.com as a first-class agent rather than as a standalone hosted app |
| LLM provider | Gemini free tier, behind a provider-agnostic interface | Anthropic Claude API | No Claude API key was available during the build window. `llm.py` isolates all provider-specific code so switching to Claude's Messages API is a single-file change — the tool schemas and agent loop are already provider-neutral |
| Board column types on import | Generic `date` / `numbers` / `text` | monday's semantic `status`/`dropdown` columns with pre-declared labels | Declaring status/dropdown labels requires an extra API call per label per column; skipped to fit the 6-hour budget. Doesn't affect the agent's query correctness since cleaning happens on the *text* value regardless of column type — only affects how the board looks to a human opening it in monday.com's UI |
| Cleaning location | At query time (`normalize.py`), boards kept close to raw | Clean once during import | Keeps the "handle messy data gracefully" requirement genuinely exercised on every request instead of solved once and forgotten; also means re-running the import is idempotent/lossless |
| Caching | 120s in-memory TTL cache per board | No cache / full cache with invalidation webhook | A BI agent answering several questions in one session shouldn't re-fetch ~500 items per tool call; 120s balances freshness against monday.com API load without needing webhook infrastructure |

## "Prepare data for leadership updates" — my interpretation

I implemented this as a **prompted behavior**, not a separate feature: when
a user asks the agent to prepare a leadership/exec update, the system
prompt instructs it to produce a short structured summary (headline
pipeline number with its caveat, sector breakdown, notable risks like
stalled deals or high-null fields) formatted for pasting into a doc or
slide, rather than dumping raw query results. This reuses the existing
`pipeline_summary` / `sector_performance` tools rather than adding new
infrastructure, which fit the time budget better than building a
separate export/report pipeline.

## What I'd do differently with more time

1. **Real fuzzy matching / entity resolution** for client and owner codes
   across the two boards (currently joined only implicitly by sector — a
   `Client Code` ↔ deal ↔ work order linkage would let the agent answer
   "which clients have open deals but no active work order," a genuinely
   founder-shaped question this version can't answer well).
2. **Swap in Claude via the Anthropic API** once a key is available —
   the abstraction is ready, just untested end-to-end against it.
3. **Webhook-based cache invalidation** instead of a flat TTL, so the agent
   reflects monday.com edits immediately without over-polling.
4. **Automated tests** against a fixture monday.com board (or recorded
   GraphQL responses) — everything here was validated manually against the
   real imported boards, not covered by an automated suite.
5. **Proper status/dropdown columns on import** with pre-declared labels,
   so the boards look native to a monday.com user, not just to the agent.
