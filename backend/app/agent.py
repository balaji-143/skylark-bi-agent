"""
The conversational BI agent: interprets a founder-level question, calls
monday.com-backed tools as needed, and synthesizes an answer that includes
data-quality caveats rather than presenting numbers as clean ground truth.
"""

from datetime import date

from . import llm, tools

SYSTEM_PROMPT = f"""Today's date is {date.today().isoformat()}.

You are Skylark Drones' internal Business Intelligence agent.
You answer founder- and executive-level questions by querying two live
monday.com boards: "Deals" (sales pipeline) and "Work Orders" (project
execution). You never have this data memorized — always call a tool to get
current numbers. Never fabricate figures.

When a user confirms a specific quarter/date range (e.g. "calendar
quarter"), use today's date above to convert it to explicit
created_after/created_before or invoiced_after/invoiced_before ISO dates
(YYYY-MM-DD) yourself before calling a tool — tools only accept exact
dates, not phrases like "this quarter".

If you've made 2+ tool calls without being able to fully answer (e.g. a
filter genuinely isn't supported by any tool), STOP calling tools and give
the best answer you can with what you've already retrieved, explicitly
stating what couldn't be filtered rather than retrying indefinitely.

Rules:
1. If a question is ambiguous (e.g. "this quarter" without a stated
   fiscal year start, "pipeline" without specifying open vs. all deals),
   ask ONE short clarifying question before calling tools — unless a
   reasonable default is obvious, in which case state the assumption you're
   making and proceed.
2. Always surface data-quality caveats returned by tools (missing values,
   dropped malformed rows) in your final answer — briefly, not as a wall of
   disclaimers.
3. Prefer calling `pipeline_summary` or `sector_performance` for aggregate
   questions; use `query_deals` / `query_work_orders` when the user wants
   specific records.
4. Give a direct, founder-readable answer first (a number and a takeaway),
   then supporting detail. Don't just dump raw tool output.
5. If asked to "prepare something for a leadership update," produce a
   short structured summary (headline numbers, notable risks/callouts,
   sector breakdown) suitable for pasting into a doc or slide — not a
   database dump.
"""

TOOL_SCHEMAS = [
    {
        "name": "query_deals",
        "description": "Look up individual deals from the sales pipeline board, optionally filtered.",
        "parameters": {
            "type": "object",
            "properties": {
                "sector": {"type": "string", "description": "e.g. Mining, Powerline, Renewables"},
                "status": {"type": "string", "description": "Open, Won, Dead, On Hold"},
                "stage": {"type": "string", "description": "Exact deal stage label, e.g. 'F. Negotiations'"},
                "min_stage_rank": {"type": "integer", "description": "Only deals at or beyond this stage rank (1-11)"},
                "created_after": {"type": "string", "description": "ISO date YYYY-MM-DD, filters on Created Date"},
                "created_before": {"type": "string", "description": "ISO date YYYY-MM-DD, filters on Created Date"},
                "limit": {"type": "integer"},
            },
        },
    },
    {
        "name": "query_work_orders",
        "description": "Look up individual work orders from the project execution board, optionally filtered.",
        "parameters": {
            "type": "object",
            "properties": {
                "sector": {"type": "string"},
                "execution_status": {"type": "string", "description": "e.g. Completed, Not Started, Executed until current month"},
                "invoiced_after": {"type": "string", "description": "ISO date YYYY-MM-DD, filters on Last invoice date"},
                "invoiced_before": {"type": "string", "description": "ISO date YYYY-MM-DD, filters on Last invoice date"},
                "limit": {"type": "integer"},
            },
        },
    },
    {
        "name": "pipeline_summary",
        "description": "Aggregate pipeline health: deal counts and known-value totals grouped by stage, with missing-value caveats.",
        "parameters": {
            "type": "object",
            "properties": {"sector": {"type": "string"}},
        },
    },
    {
        "name": "sector_performance",
        "description": "Cross-board breakdown by sector: deal counts, win counts, pipeline value, work order counts, collected amounts.",
        "parameters": {"type": "object", "properties": {}},
    },
    {
        "name": "data_quality_report",
        "description": "Summary of data quality issues (nulls, malformed rows) across both boards.",
        "parameters": {"type": "object", "properties": {}},
    },
]


def _to_gemini_history(chat_history: list[dict]) -> list[dict]:
    out = []
    for m in chat_history:
        role = "model" if m["role"] == "assistant" else "user"
        out.append({"role": role, "parts": [m["content"]]})
    return out


def answer_question(chat_history: list[dict], max_tool_hops: int = 4) -> str:
    """
    chat_history: [{"role": "user"|"assistant", "content": str}, ...]
    ending in the latest user message. Returns the assistant's reply text.
    """
    messages = _to_gemini_history(chat_history)

    for _ in range(max_tool_hops):
        response = llm.call_llm(SYSTEM_PROMPT, messages, TOOL_SCHEMAS)

        if not response.tool_calls:
            return response.text or "I wasn't able to generate a response — please try rephrasing."

        # Record the model's tool-call turn, then execute each tool and
        # feed results back before asking the model to continue.
        messages.append({"role": "model", "parts": [f"[calling tools: {[c.name for c in response.tool_calls]}]"]})

        for call in response.tool_calls:
            fn = tools.TOOL_FUNCTIONS.get(call.name)
            if not fn:
                result = {"error": f"Unknown tool {call.name}"}
            else:
                try:
                    result = fn(**call.arguments)
                except Exception as e:  # noqa: BLE001 — surface to the model, don't crash the request
                    result = {"error": str(e)}
            messages.append({"role": "user", "parts": [f"[tool result for {call.name}]: {result}"]})

    return "I gathered the data but ran out of reasoning steps — try narrowing the question."
