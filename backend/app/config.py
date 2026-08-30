import os

MONDAY_API_TOKEN = os.environ.get("MONDAY_API_TOKEN", "")
MONDAY_API_URL = "https://api.monday.com/v2"
MONDAY_API_VERSION = "2026-07"

GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "")
GEMINI_MODEL = os.environ.get("GEMINI_MODEL", "gemini-2.0-flash")

WORK_ORDERS_BOARD_ID = os.environ.get("WORK_ORDERS_BOARD_ID", "")
DEALS_BOARD_ID = os.environ.get("DEALS_BOARD_ID", "")

WORK_ORDERS_BOARD_NAME = "Work Orders"
DEALS_BOARD_NAME = "Deals"
