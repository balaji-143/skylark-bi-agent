"""
Cleans data AFTER it's fetched from monday.com (not before it's imported).
Keeping the boards themselves close to raw and doing cleanup at query time
is deliberate — see DECISION_LOG.md: it means the agent's resilience is
visible/testable, and re-import of the source CSVs never silently loses
the mess we're supposed to be handling.
"""

import re
from datetime import datetime
from typing import Any, Optional

DATE_FORMATS = [
    "%Y-%m-%d",
    "%d-%m-%Y",
    "%m/%d/%Y",
    "%d/%m/%Y",
    "%b %Y",
    "%B %Y",
    "%d %b %Y",
    "%d-%b-%y",
]

# monday.com "text" for an empty cell can be None, "", or a bare dash.
NULL_TOKENS = {"", "-", "--", "n/a", "na", "null", "none", "nan"}

# The deal-stage column is ordinal (A → K/L/N/O). Mapping it lets the agent
# reason about "how far along" a deal is instead of treating stage as a
# flat category.
DEAL_STAGE_ORDER = {
    "A. Lead Generated": 1,
    "B. Sales Qualified Leads": 2,
    "C. Demo Done": 3,
    "D. Feasibility": 4,
    "E. Proposal/Commercials Sent": 5,
    "F. Negotiations": 6,
    "G. Project Won": 7,
    "H. Work Order Received": 8,
    "I. POC": 8,
    "J. Invoice sent": 9,
    "K. Amount Accrued": 10,
    "Project Completed": 11,
    "L. Project Lost": -1,
    "M. Projects On Hold": 0,
    "N. Not relevant at the moment": 0,
    "O. Not Relevant at all": 0,
}

# Observed sector spellings from the raw CSVs are already fairly consistent,
# but this map is where any future casing/typo drift gets absorbed so the
# rest of the code can trust `sector` is canonical.
SECTOR_CANONICAL = {
    "mining": "Mining",
    "powerline": "Powerline",
    "renewables": "Renewables",
    "renewable": "Renewables",
    "tender": "Tender",
    "dsp": "DSP",
    "others": "Others",
    "security and surveillance": "Security and Surveillance",
    "construction": "Construction",
    "manufacturing": "Manufacturing",
    "railways": "Railways",
    "railway": "Railways",
    "aviation": "Aviation",
}


def is_null(value: Any) -> bool:
    if value is None:
        return True
    s = str(value).strip().lower()
    return s in NULL_TOKENS


def clean_text(value: Any) -> Optional[str]:
    if is_null(value):
        return None
    return re.sub(r"\s+", " ", str(value)).strip()


def normalize_sector(value: Any) -> Optional[str]:
    text = clean_text(value)
    if text is None:
        return None
    return SECTOR_CANONICAL.get(text.lower(), text)


def parse_date(value: Any) -> Optional[datetime]:
    text = clean_text(value)
    if text is None:
        return None
    for fmt in DATE_FORMATS:
        try:
            return datetime.strptime(text, fmt)
        except ValueError:
            continue
    # Last resort: monday often stores dates as ISO with time.
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None


def parse_number(value: Any) -> Optional[float]:
    text = clean_text(value)
    if text is None:
        return None
    # Strip currency symbols, commas, "HA"/unit suffixes some rows carry.
    cleaned = re.sub(r"[^\d.\-]", "", text)
    if cleaned in ("", "-", "."):
        return None
    try:
        return float(cleaned)
    except ValueError:
        return None


def is_leaked_header_row(row: dict, header_keys: list[str]) -> bool:
    """
    Detects the specific data-quality issue found in the deal CSV: a row
    where cell values equal their own column names (an artifact of a
    second table's header getting appended into the data on xlsx export).
    """
    matches = sum(1 for k in header_keys if clean_text(row.get(k)) == k)
    return matches >= max(2, len(header_keys) // 3)


def clean_deal_row(row: dict) -> dict:
    return {
        "id": row.get("id"),
        "deal_name": clean_text(row.get("name")),
        "owner_code": clean_text(row.get("Owner code")),
        "client_code": clean_text(row.get("Client Code")),
        "status": clean_text(row.get("Deal Status")),
        "close_date_actual": parse_date(row.get("Close Date (A)")),
        "closure_probability": clean_text(row.get("Closure Probability")),
        "deal_value": parse_number(row.get("Masked Deal value")),
        "deal_value_is_missing": is_null(row.get("Masked Deal value")),
        "tentative_close_date": parse_date(row.get("Tentative Close Date")),
        "stage": clean_text(row.get("Deal Stage")),
        "stage_rank": DEAL_STAGE_ORDER.get(clean_text(row.get("Deal Stage")) or "", None),
        "product": clean_text(row.get("Product deal")),
        "sector": normalize_sector(row.get("Sector/service")),
        "created_date": parse_date(row.get("Created Date")),
    }


def clean_work_order_row(row: dict) -> dict:
    return {
        "id": row.get("id"),
        "deal_name": clean_text(row.get("name")),
        "customer_code": clean_text(row.get("Customer Name Code")),
        "serial": clean_text(row.get("Serial #")),
        "nature_of_work": clean_text(row.get("Nature of Work")),
        "execution_status": clean_text(row.get("Execution Status")),
        "sector": normalize_sector(row.get("Sector")),
        "type_of_work": clean_text(row.get("Type of Work")),
        "po_date": parse_date(row.get("Date of PO/LOI")),
        "probable_start_date": parse_date(row.get("Probable Start Date")),
        "probable_end_date": parse_date(row.get("Probable End Date")),
        "last_invoice_date": parse_date(row.get("Last invoice date")),
        "amount_excl_gst": parse_number(row.get("Amount in Rupees (Excl of GST) (Masked)")),
        "amount_incl_gst": parse_number(row.get("Amount in Rupees (Incl of GST) (Masked)")),
        "billed_excl_gst": parse_number(row.get("Billed Value in Rupees (Excl of GST.) (Masked)")),
        "collected_amount": parse_number(row.get("Collected Amount in Rupees (Incl of GST.) (Masked)")),
        "amount_receivable": parse_number(row.get("Amount Receivable (Masked)")),
        "wo_status": clean_text(row.get("WO Status (billed)")),
        "collection_status": clean_text(row.get("Collection status")),
        "billing_status": clean_text(row.get("Billing Status")),
    }


def clean_dataset(raw_rows: list[dict], row_cleaner, header_keys: list[str]) -> dict:
    """
    Returns {"rows": [...], "data_quality": {...}} so the agent can both
    use the cleaned rows AND tell the user what was wrong with the source.
    """
    dropped_leaked_headers = 0
    kept_raw = []
    for row in raw_rows:
        if is_leaked_header_row(row, header_keys):
            dropped_leaked_headers += 1
            continue
        kept_raw.append(row)

    cleaned = [row_cleaner(r) for r in kept_raw]

    field_null_counts: dict[str, int] = {}
    for row in cleaned:
        for k, v in row.items():
            if v is None:
                field_null_counts[k] = field_null_counts.get(k, 0) + 1

    return {
        "rows": cleaned,
        "data_quality": {
            "total_rows": len(cleaned),
            "dropped_malformed_rows": dropped_leaked_headers,
            "null_counts_by_field": {
                k: v for k, v in field_null_counts.items() if v > 0
            },
        },
    }
