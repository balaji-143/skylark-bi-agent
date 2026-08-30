"""
One-time setup script: creates the "Deals" and "Work Orders" boards on
monday.com and imports the two source CSVs into them.

This is the ONLY place raw CSV data touches the code — the runtime agent
never reads these files, it only ever queries monday.com live, per the
assignment's "do not hardcode CSV data" requirement.

Usage:
    export MONDAY_API_TOKEN=...
    python import_csv_to_monday.py

Column-type choice: we map every source column to either `date`, `numeric`,
or `text` on monday.com rather than trying to recreate monday's `status`/
`dropdown` label sets (which requires pre-declaring every label via a
separate API call per column). This is a deliberate scope trade-off for a
6-hour build — see DECISION_LOG.md. The agent's normalization layer treats
these as plain text/number/date regardless of the monday.com column type,
so this choice doesn't affect query correctness, only how the board looks
if a human opens it in the monday.com UI.
"""

import csv
import sys
import time

from app import monday_client

DEALS_CSV = "Deal_funnel_Data_xlsx_-_Deal_tracker.csv"
WORK_ORDERS_CSV = "Work_Order_Tracker_Data_xlsx_-_work_order_tracker.csv"

DATE_COLUMNS = {
    "Close Date (A)", "Tentative Close Date", "Created Date",
    "Data Delivery Date", "Date of PO/LOI", "Probable Start Date",
    "Probable End Date", "Last invoice date", "Collection Date",
}
NUMERIC_COLUMNS = {
    "Masked Deal value",
    "Amount in Rupees (Excl of GST) (Masked)", "Amount in Rupees (Incl of GST) (Masked)",
    "Billed Value in Rupees (Excl of GST.) (Masked)", "Billed Value in Rupees (Incl of GST.) (Masked)",
    "Collected Amount in Rupees (Incl of GST.) (Masked)",
    "Amount to be billed in Rs. (Exl. of GST) (Masked)", "Amount to be billed in Rs. (Incl. of GST) (Masked)",
    "Amount Receivable (Masked)",
}


def read_csv_rows(path: str, skip_leading_blank_line: bool = False) -> tuple[list[str], list[dict]]:
    with open(path, newline="", encoding="utf-8") as f:
        lines = f.readlines()
    if skip_leading_blank_line and lines and lines[0].strip(",") .strip() == "":
        lines = lines[1:]
    reader = csv.DictReader(lines)
    fieldnames = reader.fieldnames or []
    return fieldnames, list(reader)


def column_type_for(field: str) -> str:
    if field in DATE_COLUMNS:
        return "date"
    if field in NUMERIC_COLUMNS:
        return "numbers"
    return "text"


def build_column_value(column_type: str, raw_value: str):
    raw_value = (raw_value or "").strip()
    if raw_value == "":
        return None
    if column_type == "date":
        # Best-effort ISO normalization; anything unparseable is skipped
        # (it still exists in `name`/raw text if ever needed — we keep the
        # import intentionally lossy-safe rather than crashing a batch job
        # on one bad cell).
        for fmt_in, fmt_out in [("%Y-%m-%d", "%Y-%m-%d"), ("%d-%m-%Y", "%Y-%m-%d"), ("%m/%d/%Y", "%Y-%m-%d")]:
            try:
                import datetime
                d = datetime.datetime.strptime(raw_value, fmt_in)
                return {"date": d.strftime(fmt_out)}
            except ValueError:
                continue
        return None
    if column_type == "numbers":
        try:
            return str(float(raw_value.replace(",", "")))
        except ValueError:
            return None
    return raw_value


def import_board(csv_path: str, board_name: str, name_field: str, skip_leading_blank: bool = False):
    print(f"--- Importing {board_name} from {csv_path} ---")
    fieldnames, rows = read_csv_rows(csv_path, skip_leading_blank)
    other_fields = [f for f in fieldnames if f != name_field]

    board_id = monday_client.find_board_id_by_name(board_name)
    if board_id:
        print(f"Board '{board_name}' already exists (id={board_id}), reusing it.")
    else:
        board_id = monday_client.create_board(board_name)
        print(f"Created board '{board_name}' (id={board_id})")

    existing_columns = {c["title"]: c["id"] for c in monday_client.get_board_columns(board_id)}
    col_ids = {}
    for field in other_fields:
        if field in existing_columns:
            col_ids[field] = existing_columns[field]
            continue
        ctype = column_type_for(field)
        col_id = monday_client.create_column(board_id, field, ctype)
        col_ids[field] = col_id
        print(f"  created column: {field} ({ctype})")
        time.sleep(0.3)  # gentle pacing against complexity limits

    created, skipped = 0, 0
    for i, row in enumerate(rows):
        item_name = (row.get(name_field) or "").strip()
        if not item_name:
            skipped += 1
            continue
        column_values = {}
        for field in other_fields:
            ctype = column_type_for(field)
            val = build_column_value(ctype, row.get(field, ""))
            if val is not None:
                column_values[col_ids[field]] = val
        try:
            monday_client.create_item(board_id, item_name, column_values)
            created += 1
            print(f"  [{i+1}/{len(rows)}] created: {item_name}")
        except Exception as e:  # noqa: BLE001
            print(f"  WARN: failed to create item '{item_name}': {e}")
        time.sleep(0.25)  # pacing: monday.com enforces per-minute complexity budgets

    print(f"Done: {created} items created, {skipped} skipped (blank name). Board id={board_id}\n")
    return board_id


if __name__ == "__main__":
    deals_board_id = import_board(DEALS_CSV, "Deals", name_field="Deal Name")
    wo_board_id = import_board(
        WORK_ORDERS_CSV, "Work Orders", name_field="Deal name masked",
        skip_leading_blank=True,
    )
    print("Set these as environment variables for the agent:")
    print(f"  DEALS_BOARD_ID={deals_board_id}")
    print(f"  WORK_ORDERS_BOARD_ID={wo_board_id}")
