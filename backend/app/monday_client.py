"""
Thin wrapper around the monday.com GraphQL API (v2).

Design notes (see DECISION_LOG.md):
- We use the raw GraphQL endpoint rather than the Platform MCP server so the
  agent can be hosted as a single standalone service with no extra
  infrastructure. The MCP server (all_monday_api tool) was considered and
  would be a drop-in alternative for this same read-only workload.
- All board reads use monday's cursor-based `items_page` pagination since
  boards can exceed the single-request item limit.
"""

import json
import time
from typing import Any, Optional

import requests

from . import config


class MondayAPIError(Exception):
    pass


def _post(query: str, variables: Optional[dict] = None, retries: int = 3) -> dict:
    if not config.MONDAY_API_TOKEN:
        raise MondayAPIError(
            "MONDAY_API_TOKEN is not set. Export it as an environment variable."
        )

    headers = {
        "Authorization": config.MONDAY_API_TOKEN,
        "Content-Type": "application/json",
        "API-Version": config.MONDAY_API_VERSION,
    }
    payload = {"query": query}
    if variables:
        payload["variables"] = variables

    last_err = None
    for attempt in range(retries):
        try:
            resp = requests.post(
                config.MONDAY_API_URL, headers=headers, json=payload, timeout=30
            )
            data = resp.json()
        except (requests.RequestException, json.JSONDecodeError) as e:
            last_err = e
            time.sleep(1.5 * (attempt + 1))
            continue

        if "errors" in data:
            # monday.com returns 200 with an "errors" array on GraphQL-level
            # failures (bad field, complexity limit, rate limit, etc).
            msg = json.dumps(data["errors"])
            if "ComplexityException" in msg or "rate limit" in msg.lower():
                last_err = MondayAPIError(msg)
                time.sleep(2 * (attempt + 1))
                continue
            raise MondayAPIError(msg)

        return data.get("data", {})

    raise MondayAPIError(f"monday.com API request failed after {retries} retries: {last_err}")


def get_boards() -> list[dict]:
    query = """
    query {
      boards (limit: 50) {
        id
        name
        state
      }
    }
    """
    return _post(query).get("boards", [])


def find_board_id_by_name(name: str) -> Optional[str]:
    for b in get_boards():
        if b["name"].strip().lower() == name.strip().lower():
            return b["id"]
    return None


def get_board_columns(board_id: str) -> list[dict]:
    query = """
    query ($boardId: [ID!]) {
      boards (ids: $boardId) {
        columns { id title type }
      }
    }
    """
    data = _post(query, {"boardId": [board_id]})
    boards = data.get("boards", [])
    return boards[0]["columns"] if boards else []


def get_all_board_items(board_id: str, page_size: int = 100) -> list[dict]:
    """
    Reads every item on a board, following monday's cursor pagination.
    Returns a list of dicts: {id, name, <column_title>: <text_value>, ...}
    with column_values flattened into a friendly key/value shape so the
    normalization layer and LLM tools don't have to know monday's column
    schema.
    """
    columns = {c["id"]: c["title"] for c in get_board_columns(board_id)}

    query = """
    query ($boardId: ID!, $cursor: String, $limit: Int!) {
      boards (ids: [$boardId]) {
        items_page (limit: $limit, cursor: $cursor) {
          cursor
          items {
            id
            name
            column_values {
              id
              text
              value
            }
          }
        }
      }
    }
    """

    items: list[dict] = []
    cursor = None
    while True:
        variables = {"boardId": board_id, "cursor": cursor, "limit": page_size}
        data = _post(query, variables)
        boards = data.get("boards", [])
        if not boards:
            break
        page = boards[0]["items_page"]
        for raw_item in page["items"]:
            row = {"id": raw_item["id"], "name": raw_item["name"]}
            for cv in raw_item["column_values"]:
                col_title = columns.get(cv["id"], cv["id"])
                row[col_title] = cv["text"]
            items.append(row)
        cursor = page.get("cursor")
        if not cursor:
            break
    return items


# ---------------------------------------------------------------------------
# Board/column/item creation — used only by import_csv_to_monday.py to set
# up the two boards from the source CSVs. The runtime agent is read-only.
# ---------------------------------------------------------------------------

def create_board(name: str, kind: str = "public") -> str:
    query = """
    mutation ($name: String!, $kind: BoardKind!) {
      create_board (board_name: $name, board_kind: $kind) { id }
    }
    """
    return _post(query, {"name": name, "kind": kind})["create_board"]["id"]


def create_column(board_id: str, title: str, column_type: str) -> str:
    query = """
    mutation ($boardId: ID!, $title: String!, $type: ColumnType!) {
      create_column (board_id: $boardId, title: $title, column_type: $type) { id }
    }
    """
    return _post(
        query, {"boardId": board_id, "title": title, "type": column_type}
    )["create_column"]["id"]


def create_item(board_id: str, item_name: str, column_values: dict) -> str:
    query = """
    mutation ($boardId: ID!, $itemName: String!, $columnValues: JSON!) {
      create_item (
        board_id: $boardId,
        item_name: $itemName,
        column_values: $columnValues
      ) { id }
    }
    """
    variables = {
        "boardId": board_id,
        "itemName": item_name,
        "columnValues": json.dumps(column_values),
    }
    return _post(query, variables)["create_item"]["id"]
