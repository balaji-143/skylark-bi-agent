"""
Tools the LLM agent can call. Each tool fetches live from monday.com
(never from the source CSVs) and returns cleaned data + explicit
data-quality caveats, per the assignment's "read-only, dynamic query"
requirement.

A short in-memory cache avoids re-fetching all board items on every single
tool call within one conversation turn (the agent often calls 2-3 tools per
question). TTL is intentionally short since this is a BI agent, not a
dashboard — freshness matters more than call volume here.
"""

import time
from typing import Any, Optional

from . import config, monday_client, normalize

_CACHE: dict[str, tuple[float, dict]] = {}
_CACHE_TTL_SECONDS = 120

DEAL_HEADER_KEYS = [
    "Deal Status", "Close Date (A)", "Closure Probability",
    "Tentative Close Date", "Deal Stage", "Product deal",
    "Sector/service", "Created Date",
]
WO_HEADER_KEYS = [
    "Customer Name Code", "Serial #", "Nature of Work", "Execution Status",
    "Sector", "Type of Work", "WO Status (billed)",
]


def _get_dataset(board_id_env: str, board_name: str, row_cleaner, header_keys) -> dict:
    board_id = board_id_env or monday_client.find_board_id_by_name(board_name)
    if not board_id:
        raise RuntimeError(
            f"Could not find monday.com board '{board_name}'. "
            f"Run import_csv_to_monday.py first or set the board ID env var."
        )

    cache_key = board_id
    now = time.time()
    if cache_key in _CACHE and now - _CACHE[cache_key][0] < _CACHE_TTL_SECONDS:
        return _CACHE[cache_key][1]

    raw_items = monday_client.get_all_board_items(board_id)
    dataset = normalize.clean_dataset(raw_items, row_cleaner, header_keys)
    _CACHE[cache_key] = (now, dataset)
    return dataset


def get_deals_dataset() -> dict:
    return _get_dataset(
        config.DEALS_BOARD_ID, config.DEALS_BOARD_NAME,
        normalize.clean_deal_row, DEAL_HEADER_KEYS,
    )


def get_work_orders_dataset() -> dict:
    return _get_dataset(
        config.WORK_ORDERS_BOARD_ID, config.WORK_ORDERS_BOARD_NAME,
        normalize.clean_work_order_row, WO_HEADER_KEYS,
    )


def _match(row_val: Optional[str], filter_val: Optional[str]) -> bool:
    if filter_val is None:
        return True
    if row_val is None:
        return False
    return row_val.strip().lower() == filter_val.strip().lower()


# ---------------------------------------------------------------------------
# Tool implementations (schemas for these live in llm.py / agent.py)
# ---------------------------------------------------------------------------

def _in_range(d, start, end) -> bool:
    if d is None:
        return False
    if start and d < start:
        return False
    if end and d > end:
        return False
    return True


def _parse_iso_date(s: Optional[str]):
    if not s:
        return None
    from datetime import datetime
    return datetime.strptime(s, "%Y-%m-%d")


def query_deals(sector: Optional[str] = None, status: Optional[str] = None,
                 stage: Optional[str] = None, min_stage_rank: Optional[int] = None,
                 created_after: Optional[str] = None, created_before: Optional[str] = None,
                 limit: int = 50) -> dict:
    ds = get_deals_dataset()
    rows = ds["rows"]
    start = _parse_iso_date(created_after)
    end = _parse_iso_date(created_before)
    filtered = [
        r for r in rows
        if _match(r["sector"], sector)
        and _match(r["status"], status)
        and _match(r["stage"], stage)
        and (min_stage_rank is None or (r["stage_rank"] or 0) >= min_stage_rank)
        and (start is None and end is None or _in_range(r["created_date"], start, end))
    ]
    return {
        "matched_count": len(filtered),
        "rows": filtered[:limit],
        "caveats": _deal_caveats(filtered, ds["data_quality"]),
    }


def query_work_orders(sector: Optional[str] = None, execution_status: Optional[str] = None,
                       invoiced_after: Optional[str] = None, invoiced_before: Optional[str] = None,
                       limit: int = 50) -> dict:
    ds = get_work_orders_dataset()
    rows = ds["rows"]
    start = _parse_iso_date(invoiced_after)
    end = _parse_iso_date(invoiced_before)
    filtered = [
        r for r in rows
        if _match(r["sector"], sector)
        and _match(r["execution_status"], execution_status)
        and (start is None and end is None or _in_range(r["last_invoice_date"], start, end))
    ]
    return {
        "matched_count": len(filtered),
        "rows": filtered[:limit],
        "caveats": _wo_caveats(filtered, ds["data_quality"]),
    }


def pipeline_summary(sector: Optional[str] = None) -> dict:
    """
    Aggregate view of the deal funnel: counts and known-value totals by
    stage, explicitly separating deals with a missing value instead of
    silently treating them as zero (a founder asking 'how big is our
    pipeline' needs to know the number is a floor, not the true total).
    """
    ds = get_deals_dataset()
    rows = [r for r in ds["rows"] if _match(r["sector"], sector)]

    by_stage: dict[str, dict] = {}
    missing_value_count = 0
    known_value_total = 0.0
    for r in rows:
        stage = r["stage"] or "Unknown"
        bucket = by_stage.setdefault(stage, {"count": 0, "known_value_total": 0.0, "missing_value_count": 0})
        bucket["count"] += 1
        if r["deal_value"] is None:
            bucket["missing_value_count"] += 1
            missing_value_count += 1
        else:
            bucket["known_value_total"] += r["deal_value"]
            known_value_total += r["deal_value"]

    return {
        "sector_filter": sector,
        "total_deals": len(rows),
        "known_value_total": known_value_total,
        "deals_missing_value": missing_value_count,
        "by_stage": by_stage,
        "caveat": (
            f"{missing_value_count} of {len(rows)} matching deals have no recorded value — "
            "totals below are a floor, not the true pipeline size."
            if missing_value_count else None
        ),
    }


def sector_performance() -> dict:
    ds_deals = get_deals_dataset()
    ds_wo = get_work_orders_dataset()

    by_sector: dict[str, dict] = {}
    for r in ds_deals["rows"]:
        s = r["sector"] or "Unknown"
        b = by_sector.setdefault(s, {"deal_count": 0, "won_count": 0, "known_deal_value": 0.0,
                                       "work_order_count": 0, "collected_amount": 0.0})
        b["deal_count"] += 1
        if r["stage_rank"] and r["stage_rank"] >= 7:
            b["won_count"] += 1
        if r["deal_value"] is not None:
            b["known_deal_value"] += r["deal_value"]

    for r in ds_wo["rows"]:
        s = r["sector"] or "Unknown"
        b = by_sector.setdefault(s, {"deal_count": 0, "won_count": 0, "known_deal_value": 0.0,
                                       "work_order_count": 0, "collected_amount": 0.0})
        b["work_order_count"] += 1
        if r["collected_amount"] is not None:
            b["collected_amount"] += r["collected_amount"]

    return {"by_sector": by_sector}


def data_quality_report() -> dict:
    return {
        "deals": get_deals_dataset()["data_quality"],
        "work_orders": get_work_orders_dataset()["data_quality"],
    }


def _deal_caveats(rows: list[dict], dq: dict) -> list[str]:
    caveats = []
    missing_val = sum(1 for r in rows if r["deal_value"] is None)
    if missing_val:
        caveats.append(f"{missing_val} of {len(rows)} matching deals have no recorded deal value.")
    if dq.get("dropped_malformed_rows"):
        caveats.append(
            f"{dq['dropped_malformed_rows']} malformed row(s) were excluded from the source board "
            "(detected as corrupted/duplicated header data)."
        )
    return caveats


def _wo_caveats(rows: list[dict], dq: dict) -> list[str]:
    caveats = []
    missing_amt = sum(1 for r in rows if r["amount_excl_gst"] is None)
    if missing_amt:
        caveats.append(f"{missing_amt} of {len(rows)} matching work orders have no recorded amount.")
    if dq.get("dropped_malformed_rows"):
        caveats.append(f"{dq['dropped_malformed_rows']} malformed row(s) were excluded from the source board.")
    return caveats


# Registry used by agent.py to dispatch tool calls by name.
TOOL_FUNCTIONS = {
    "query_deals": query_deals,
    "query_work_orders": query_work_orders,
    "pipeline_summary": pipeline_summary,
    "sector_performance": sector_performance,
    "data_quality_report": data_quality_report,
}
