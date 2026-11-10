"""DuckDB storage: tables, views and connections.

Implements specs/schema.md section 2 (objects), 5.4 (v_recognized_revenue) and 6 (v_accounts).
"""
from __future__ import annotations

from pathlib import Path

import duckdb
import pandas as pd

from app import config
from app import pipeline
from app.pipeline import PipelineResult

INVOICES_DDL = """
CREATE TABLE invoices (
    invoice_id             VARCHAR PRIMARY KEY,
    account_id             VARCHAR NOT NULL,
    account_name           VARCHAR NOT NULL,
    contact_email          VARCHAR,
    email_was_repaired     BOOLEAN NOT NULL,
    region                 VARCHAR NOT NULL,
    industry               VARCHAR,
    plan                   VARCHAR NOT NULL,
    billing_cycle          VARCHAR NOT NULL,
    seats                  INTEGER NOT NULL,
    currency               VARCHAR NOT NULL,
    amount_local           DECIMAL(14,2) NOT NULL,
    amount_usd             DECIMAL(18,4) NOT NULL,
    discount_pct           DECIMAL(5,2) NOT NULL,
    status                 VARCHAR NOT NULL,
    payment_method         VARCHAR,
    signup_date            DATE NOT NULL,
    invoice_date           DATE NOT NULL,
    churned                BOOLEAN NOT NULL,
    csat_score             INTEGER,
    support_tickets        INTEGER NOT NULL,
    mrr_usd                DECIMAL(14,2) NOT NULL,
    status_conflict        BOOLEAN NOT NULL,
    is_future_dated        BOOLEAN NOT NULL,
    amount_matches_formula BOOLEAN NOT NULL,
    source_row             INTEGER NOT NULL
)
"""

QUARANTINE_DDL = "CREATE TABLE quarantine (" + ", ".join(
    f"{c} VARCHAR" for c in config.RAW_COLUMNS
) + ", source_row INTEGER NOT NULL, reason VARCHAR NOT NULL)"

DQ_REPORT_DDL = "CREATE TABLE dq_report (check_name VARCHAR PRIMARY KEY, value BIGINT NOT NULL)"


def _in_list(values) -> str:
    return ", ".join(f"'{v}'" for v in values)


def view_ddl() -> list[str]:
    """The semantic layer. Status lists come from config so the rule lives in one place."""
    return [
        f"CREATE VIEW v_recognized_revenue AS SELECT * FROM invoices "
        f"WHERE status IN ({_in_list(config.REVENUE_STATUSES)})",
        f"CREATE VIEW v_open_exposure AS SELECT * FROM invoices "
        f"WHERE status IN ({_in_list(config.OPEN_EXPOSURE_STATUSES)})",
        # Section 6: one row per account_id from its latest invoice
        # (highest invoice_date, ties broken by highest invoice_id; any status counts).
        """
        CREATE VIEW v_accounts AS
        WITH ranked AS (
            SELECT *,
                   ROW_NUMBER() OVER (PARTITION BY account_id
                                      ORDER BY invoice_date DESC, invoice_id DESC) AS rn
            FROM invoices
        )
        SELECT account_id, account_name, region, industry, plan, seats, discount_pct,
               churned, csat_score, support_tickets, mrr_usd,
               status       AS latest_status,
               invoice_date AS latest_invoice_date,
               invoice_id   AS latest_invoice_id,
               (status = 'paid' AND NOT churned) AS is_active
        FROM ranked WHERE rn = 1
        """,
    ]


def _stringify(df: pd.DataFrame) -> pd.DataFrame:
    """Decimals and dates as text so DuckDB casts them exactly; None stays NULL."""
    out = df.copy()
    for c in out.columns:
        out[c] = out[c].map(lambda v: None if v is None or (isinstance(v, float) and pd.isna(v)) else str(v))
    return out


def write_database(result: PipelineResult, db_path: Path = config.DB_PATH) -> Path:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    if db_path.exists():
        db_path.unlink()
    wal = db_path.with_suffix(db_path.suffix + ".wal")
    if wal.exists():
        wal.unlink()

    con = duckdb.connect(str(db_path))
    try:
        con.execute(INVOICES_DDL)
        con.execute(QUARANTINE_DDL)
        con.execute(DQ_REPORT_DDL)

        invoices_src = _stringify(result.invoices)  # noqa: F841 (registered by name below)
        con.register("invoices_src", invoices_src)
        cols = ", ".join(result.invoices.columns)
        con.execute(f"INSERT INTO invoices ({cols}) SELECT {cols} FROM invoices_src")

        quarantine_src = _stringify(result.quarantine)  # noqa: F841
        con.register("quarantine_src", quarantine_src)
        qcols = ", ".join(result.quarantine.columns)
        con.execute(f"INSERT INTO quarantine ({qcols}) SELECT {qcols} FROM quarantine_src")

        con.executemany("INSERT INTO dq_report VALUES (?, ?)", result.dq_report)
        for ddl in view_ddl():
            con.execute(ddl)
    finally:
        con.close()
    return db_path


def connect(db_path: Path = config.DB_PATH, read_only: bool = True) -> duckdb.DuckDBPyConnection:
    if not db_path.exists():
        raise FileNotFoundError(f"database not found at {db_path}; run `python -m app build`")
    return duckdb.connect(str(db_path), read_only=read_only)


def build(csv_path: Path = config.RAW_CSV_PATH, db_path: Path = config.DB_PATH) -> PipelineResult:
    """Run the pipeline and write the database. Returns the result for reporting."""
    result = pipeline.run(csv_path)
    write_database(result, db_path)
    return result
