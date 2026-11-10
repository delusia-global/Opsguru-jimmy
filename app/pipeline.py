"""Cleaning pipeline: raw CSV -> typed invoices, quarantine and data-quality report.

Implements specs/schema.md sections 1, 3, 4, 5.1-5.3, 5.5, 7, 8 and 10. Writing the DuckDB
file and the views is app/db.py (sections 2, 5.4, 6).
"""
from __future__ import annotations

import datetime as dt
import re
from dataclasses import dataclass, field
from decimal import Decimal

import pandas as pd

from app import config

_INT_RE = re.compile(r"^[-+]?\d+$")
_DECIMAL_RE = re.compile(r"^[-+]?\d+(\.\d+)?$")
_AMOUNT_RE = re.compile(
    r"^(?P<sign1>[-+])?(?P<symbol>[$€£])?(?P<sign2>[-+])?"
    r"(?P<number>(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d+)?)"
    r"(?:\s*(?P<code>[A-Za-z]{3}))?$"
)
_DATE_FORMATS = [(re.compile(rx), fmt) for rx, fmt in config.DATE_FORMATS]
_TWO_DP = Decimal("0.01")


class RowError(ValueError):
    """A raw value that does not fit a rule. The message is the quarantine reason."""


@dataclass
class PipelineResult:
    invoices: pd.DataFrame
    quarantine: pd.DataFrame
    dq_report: list[tuple[str, int]] = field(default_factory=list)


# --- Section 1: input ------------------------------------------------------------------------

def read_raw(csv_path=config.RAW_CSV_PATH) -> pd.DataFrame:
    """Every column as text. The literal string 'NA' is a region, not a null."""
    df = pd.read_csv(csv_path, dtype=str, keep_default_na=False, na_filter=False)
    missing = [c for c in config.RAW_COLUMNS if c not in df.columns]
    if missing or len(df.columns) != len(config.RAW_COLUMNS):
        raise RowError(f"unexpected columns in {csv_path}: missing {missing}, got {list(df.columns)}")
    df = df[list(config.RAW_COLUMNS)].copy()
    df["source_row"] = range(2, len(df) + 2)  # header is line 1
    return df


# --- Sections 3 and 4: per-row normalisation -------------------------------------------------

def _mapped(raw: str, mapping: dict, column: str):
    key = raw.strip().lower()
    if key not in mapping:
        raise RowError(f"{column}: unrecognised value {raw!r}")
    return mapping[key]


def _strict_int(raw: str, column: str) -> int:
    s = raw.strip()
    if not _INT_RE.match(s):
        raise RowError(f"{column}: not an integer {raw!r}")
    return int(s)


def _strict_decimal(raw: str, column: str, places: Decimal) -> Decimal:
    s = raw.strip()
    if not _DECIMAL_RE.match(s):
        raise RowError(f"{column}: not a decimal {raw!r}")
    value = Decimal(s)
    if value != value.quantize(places):
        raise RowError(f"{column}: more precision than allowed {raw!r}")
    return value.quantize(places)


def parse_amount(raw: str, currency: str) -> Decimal:
    """Schema 4.5. Strip symbol, code, thousands commas and spaces; keep the sign."""
    s = raw.strip().replace(" ", "")
    m = _AMOUNT_RE.match(s)
    if not m:
        raise RowError(f"amount: unparseable {raw!r}")
    if m.group("sign1") and m.group("sign2"):
        raise RowError(f"amount: two signs {raw!r}")
    symbol, code = m.group("symbol"), m.group("code")
    if symbol and config.CURRENCY_SYMBOLS[symbol] != currency:
        raise RowError(f"amount: symbol {symbol!r} disagrees with currency {currency}")
    if code and code.upper() != currency:
        raise RowError(f"amount: code {code!r} disagrees with currency {currency}")
    if symbol and code:
        raise RowError(f"amount: both symbol and code {raw!r}")
    number = Decimal(m.group("number").replace(",", ""))
    if number != number.quantize(_TWO_DP):
        raise RowError(f"amount: more than 2 decimal places {raw!r}")
    sign = -1 if (m.group("sign1") or m.group("sign2")) == "-" else 1
    return (number * sign).quantize(_TWO_DP)


def parse_date(raw: str, column: str) -> dt.date:
    """Schema 4.6. The separator decides: slash is month-first, dash is day-first."""
    s = raw.strip()
    for rx, fmt in _DATE_FORMATS:
        if rx.match(s):
            try:
                return dt.datetime.strptime(s, fmt).date()
            except ValueError:
                raise RowError(f"{column}: invalid date {raw!r} under {fmt}") from None
    raise RowError(f"{column}: unrecognised date format {raw!r}")


def clean_row(raw: dict) -> dict:
    """Apply sections 3, 4, 5.1, 5.3, 5.5 and 8 to one raw row. Raises RowError on any rule."""
    out: dict = {}

    invoice_id = raw["invoice_id"].strip()
    if not re.match(config.INVOICE_ID_PATTERN, invoice_id):
        raise RowError(f"invoice_id: malformed {raw['invoice_id']!r}")
    account_id = raw["account_id"].strip()
    if not re.match(config.ACCOUNT_ID_PATTERN, account_id):
        raise RowError(f"account_id: malformed {raw['account_id']!r}")
    out["invoice_id"], out["account_id"] = invoice_id, account_id

    out["account_name"] = raw["account_name"].strip()
    if not out["account_name"]:
        raise RowError("account_name: blank")

    email = raw["contact_email"].strip().lower()
    out["email_was_repaired"] = "_at_" in email
    out["contact_email"] = email.replace("_at_", "@") if email else None

    region = raw["region"].strip().upper()
    if region not in config.REGIONS:
        raise RowError(f"region: unrecognised value {raw['region']!r}")
    out["region"] = region

    out["industry"] = raw["industry"].strip() or None
    out["plan"] = _mapped(raw["plan"], config.PLAN_MAP, "plan")
    out["billing_cycle"] = _mapped(raw["billing_cycle"], config.BILLING_CYCLE_MAP, "billing_cycle")

    out["seats"] = _strict_int(raw["seats"], "seats")
    if out["seats"] <= 0:
        raise RowError(f"seats: must be > 0, got {out['seats']}")

    currency = raw["currency"].strip().upper()
    if currency not in config.CURRENCIES:
        raise RowError(f"currency: unrecognised value {raw['currency']!r}")
    out["currency"] = currency

    out["amount_local"] = parse_amount(raw["amount"], currency)
    out["amount_usd"] = out["amount_local"] * config.FX_RATES[currency]  # exact, 4 dp

    out["discount_pct"] = _strict_decimal(raw["discount_pct"], "discount_pct", _TWO_DP)
    if not (0 <= out["discount_pct"] <= 100):
        raise RowError(f"discount_pct: out of range {out['discount_pct']}")

    out["status"] = _mapped(raw["status"], config.STATUS_MAP, "status")
    pm = raw["payment_method"].strip()
    out["payment_method"] = _mapped(pm, config.PAYMENT_METHOD_MAP, "payment_method") if pm else None

    out["signup_date"] = parse_date(raw["signup_date"], "signup_date")
    out["invoice_date"] = parse_date(raw["invoice_date"], "invoice_date")
    out["churned"] = _mapped(raw["churned"], config.CHURNED_MAP, "churned")

    csat = raw["csat_score"].strip()
    if csat:
        value = _strict_int(csat, "csat_score")
        lo, hi = config.CSAT_RANGE
        if not (lo <= value <= hi):
            raise RowError(f"csat_score: out of range {value}")
        out["csat_score"] = value
    else:
        out["csat_score"] = None

    out["support_tickets"] = _strict_int(raw["support_tickets"], "support_tickets")
    if out["support_tickets"] < 0:
        raise RowError(f"support_tickets: negative {out['support_tickets']}")

    # 5.5 MRR from subscription terms, never from amount
    discount_factor = 1 - out["discount_pct"] / 100
    list_price = config.LIST_PRICE_USD[out["plan"]]
    out["mrr_usd"] = (list_price * out["seats"] * discount_factor).quantize(_TWO_DP)

    # 5.3 sanity flag: amount is already net of discount and already rate-adjusted
    months = config.ANNUAL_MONTHS_BILLED if out["billing_cycle"] == "annual" else 1
    expected = list_price * out["seats"] * months * discount_factor * config.FX_RATES[currency]
    out["amount_matches_formula"] = abs(abs(out["amount_local"]) - expected) <= config.AMOUNT_FORMULA_TOLERANCE

    out["status_conflict"] = False  # set by dedup (section 7)
    out["is_future_dated"] = out["invoice_date"] > config.AS_OF_DATE  # section 8
    out["source_row"] = int(raw["source_row"])
    return out


# --- Section 7: deduplication ----------------------------------------------------------------

def run(csv_path=config.RAW_CSV_PATH) -> PipelineResult:
    raw = read_raw(csv_path)
    report: list[tuple[str, int]] = [("raw_rows", len(raw))]
    quarantine: list[dict] = []

    def send_to_quarantine(raw_row: dict, reason: str) -> None:
        quarantine.append({**{c: raw_row[c] for c in config.RAW_COLUMNS},
                           "source_row": int(raw_row["source_row"]), "reason": reason})

    # 7.1 exact duplicates: identical in all 19 raw columns, keep the first by file order
    exact_dupes = raw.duplicated(subset=list(config.RAW_COLUMNS), keep="first")
    report.append(("exact_duplicates_dropped", int(exact_dupes.sum())))
    raw = raw[~exact_dupes]

    # Sections 3-5, 8: clean every surviving raw row
    cleaned: list[tuple[dict, dict]] = []  # (raw_row, clean_row)
    for raw_row in raw.to_dict("records"):
        try:
            cleaned.append((raw_row, clean_row(raw_row)))
        except RowError as e:
            send_to_quarantine(raw_row, str(e))

    # 7.2 near-duplicates: rows sharing an invoice_id
    groups: dict[str, list[tuple[dict, dict]]] = {}
    for raw_row, row in cleaned:
        groups.setdefault(row["invoice_id"], []).append((raw_row, row))
    near_dupe_ids = [k for k, g in groups.items() if len(g) > 1]
    report.append(("near_duplicate_invoice_ids", len(near_dupe_ids)))

    survivors: list[dict] = []
    conflict_ids = 0
    non_status_columns = [c for c in config.RAW_COLUMNS if c != "status"]
    for invoice_id, group in groups.items():
        if len(group) == 1:
            survivors.append(group[0][1])
            continue
        first_raw = group[0][0]
        if any(any(r[c] != first_raw[c] for c in non_status_columns) for r, _ in group[1:]):
            for r, _ in group:
                send_to_quarantine(r, f"near-duplicate of {invoice_id} differs in a column other than status")
            continue
        statuses = {row["status"] for _, row in group}
        if len(statuses) == 1:
            survivors.append(group[0][1])  # same canonical status: first by file order
        else:
            winner = max((row for _, row in group), key=lambda r: config.STATUS_LIFECYCLE_RANK[r["status"]])
            winner["status_conflict"] = True
            conflict_ids += 1
            survivors.append(winner)
    report.append(("status_conflict_invoice_ids", conflict_ids))

    # 4.5 sign check, after dedup: negative <=> refunded
    final: list[dict] = []
    raw_by_source = {int(r["source_row"]): r for r, _ in cleaned}
    for row in survivors:
        negative = row["amount_local"] < 0
        if negative != (row["status"] == "refunded"):
            send_to_quarantine(raw_by_source[row["source_row"]],
                               f"amount sign {'negative' if negative else 'non-negative'} disagrees with status {row['status']}")
        else:
            final.append(row)

    invoices = pd.DataFrame(final, columns=INVOICE_COLUMNS).sort_values("source_row").reset_index(drop=True)
    quarantine_df = pd.DataFrame(quarantine, columns=[*config.RAW_COLUMNS, "source_row", "reason"])

    # Section 10 report
    report += [
        ("quarantined_rows", len(quarantine_df)),
        ("clean_invoices", len(invoices)),
        ("accounts", int(invoices["account_id"].nunique()) if len(invoices) else 0),
        ("emails_repaired", int(invoices["email_was_repaired"].sum()) if len(invoices) else 0),
        ("null_contact_email", int(invoices["contact_email"].isna().sum())),
        ("null_industry", int(invoices["industry"].isna().sum())),
        ("null_csat_score", int(invoices["csat_score"].isna().sum())),
        ("null_payment_method", int(invoices["payment_method"].isna().sum())),
        ("future_dated_invoices", int(invoices["is_future_dated"].sum()) if len(invoices) else 0),
        ("amount_formula_mismatches", int((~invoices["amount_matches_formula"]).sum()) if len(invoices) else 0),
    ]
    return PipelineResult(invoices=invoices, quarantine=quarantine_df, dq_report=report)


INVOICE_COLUMNS = (
    "invoice_id", "account_id", "account_name", "contact_email", "email_was_repaired", "region",
    "industry", "plan", "billing_cycle", "seats", "currency", "amount_local", "amount_usd",
    "discount_pct", "status", "payment_method", "signup_date", "invoice_date", "churned",
    "csat_score", "support_tickets", "mrr_usd", "status_conflict", "is_future_dated",
    "amount_matches_formula", "source_row",
)
