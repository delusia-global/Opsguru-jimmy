"""Configuration: environment variables, business constants and category mappings.

Implements specs/schema.md section 9. Every path, rate, price, mapping, model name and limit
lives here and nowhere else.
"""
from __future__ import annotations

import datetime as dt
import os
from decimal import Decimal
from pathlib import Path

from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parent.parent
load_dotenv(PROJECT_ROOT / ".env")


def _env(name: str, default: str) -> str:
    value = os.environ.get(name, "")
    return value.strip() if value and value.strip() else default


# --- Paths and run settings (schema section 9) ---------------------------------------------
RAW_CSV_PATH = Path(_env("RAW_CSV_PATH", "data/cloudnova_invoices.csv"))
DB_PATH = Path(_env("DB_PATH", "build/cloudnova.duckdb"))
AS_OF_DATE: dt.date = (
    dt.date.fromisoformat(_env("AS_OF_DATE", "")) if _env("AS_OF_DATE", "") else dt.date.today()
)

# --- Question layer (schema section 9, query contract) -------------------------------------
ANTHROPIC_API_KEY_VAR = "ANTHROPIC_API_KEY"
ANTHROPIC_API_KEY = _env(ANTHROPIC_API_KEY_VAR, "")
# Default is the ID in .env.example; confirmed against the Anthropic docs before use.
ANTHROPIC_MODEL = _env("ANTHROPIC_MODEL", "claude-sonnet-5-5")
QUERY_TIMEOUT_SECONDS = 30
QUERY_ROW_CAP = 200
QUESTION_MAX_CHARS = 500
ALLOWED_RELATIONS = ("invoices", "v_recognized_revenue", "v_open_exposure", "v_accounts")
# Functions that read files, the network or the catalogue. Table-position functions are
# rejected wholesale by the guard; this list catches the scalar ones too.
BLOCKED_FUNCTIONS = frozenset({
    "read_csv", "read_csv_auto", "read_parquet", "read_json", "read_json_auto", "read_json_objects",
    "read_text", "read_blob", "read_ndjson", "read_ndjson_auto", "glob", "sniff_csv", "parquet_scan",
    "parquet_metadata", "parquet_schema", "getenv", "current_setting", "duckdb_tables",
    "duckdb_views", "duckdb_columns", "duckdb_settings", "duckdb_extensions", "duckdb_databases",
    "duckdb_functions", "duckdb_secrets", "query", "query_table", "sql", "json_each", "pragma_version",
})

# --- Money (schema sections 5.1, 5.5) ------------------------------------------------------
FX_RATES: dict[str, Decimal] = {
    "USD": Decimal("1.00"),
    "EUR": Decimal("1.08"),
    "GBP": Decimal("1.27"),
}
LIST_PRICE_USD: dict[str, Decimal] = {
    "Starter": Decimal("49"),
    "Pro": Decimal("99"),
    "Enterprise": Decimal("299"),
}
ANNUAL_MONTHS_BILLED = 10          # annual invoices bill 10 months (briefing)
AMOUNT_FORMULA_TOLERANCE = Decimal("1.00")   # schema 5.3

# --- Allowed sets (schema section 3) -------------------------------------------------------
REGIONS = ("NA", "EMEA", "APAC", "LATAM")
CURRENCIES = tuple(FX_RATES)
CSAT_RANGE = (1, 5)
INVOICE_ID_PATTERN = r"^INV-\d{6}$"
ACCOUNT_ID_PATTERN = r"^ACC-\d{4}$"
CURRENCY_SYMBOLS: dict[str, str] = {"$": "USD", "€": "EUR", "£": "GBP"}

# --- Category mappings, applied after strip() and lower() (schema section 4) ---------------
PLAN_MAP: dict[str, str] = {
    "starter": "Starter", "start": "Starter", "tier 1": "Starter",
    "pro": "Pro", "professional": "Pro", "tier 2": "Pro",
    "enterprise": "Enterprise", "ent": "Enterprise", "tier 3": "Enterprise",
}
BILLING_CYCLE_MAP: dict[str, str] = {
    "monthly": "monthly",
    "annual": "annual", "annually": "annual", "yearly": "annual",
}
STATUS_MAP: dict[str, str] = {
    "paid": "paid", "complete": "paid", "completed": "paid", "success": "paid",
    "pending": "pending", "in_review": "pending", "awaiting": "pending",
    "failed": "failed", "declined": "failed", "error": "failed",
    "refunded": "refunded", "refund": "refunded", "charged_back": "refunded",
    "void": "void", "cancelled": "void", "canceled": "void",
}
PAYMENT_METHOD_MAP: dict[str, str] = {
    "credit_card": "credit_card", "credit card": "credit_card",
    "ach": "ach",
    "wire": "wire", "wire transfer": "wire",
    "invoice": "invoice",
}
CHURNED_MAP: dict[str, bool] = {
    "true": True, "yes": True, "1": True, "y": True,
    "false": False, "no": False, "0": False, "n": False,
}
REVENUE_STATUSES = ("paid", "refunded")      # schema 5.4
OPEN_EXPOSURE_STATUSES = ("pending", "failed")

# Near-duplicate resolution: the latest lifecycle state wins (schema section 7).
STATUS_LIFECYCLE_RANK: dict[str, int] = {
    "refunded": 5, "void": 4, "paid": 3, "failed": 2, "pending": 1,
}

# --- Dates (schema 4.6): separator decides the convention ----------------------------------
# (regex on the raw string, strptime format)
DATE_FORMATS: tuple[tuple[str, str], ...] = (
    (r"^\d{4}-\d{2}-\d{2}$", "%Y-%m-%d"),      # ISO
    (r"^\d{4}/\d{2}/\d{2}$", "%Y/%m/%d"),      # YYYY/MM/DD
    (r"^\d{1,2}/\d{1,2}/\d{4}$", "%m/%d/%Y"),  # slash = US month-first
    (r"^\d{1,2}-\d{1,2}-\d{4}$", "%d-%m-%Y"),  # dash = day-first
    (r"^[A-Za-z]{3} \d{1,2} \d{4}$", "%b %d %Y"),  # month name
)

RAW_COLUMNS = (
    "invoice_id", "account_id", "account_name", "contact_email", "region", "industry",
    "plan", "billing_cycle", "seats", "currency", "amount", "discount_pct", "status",
    "payment_method", "signup_date", "invoice_date", "churned", "csat_score",
    "support_tickets",
)
