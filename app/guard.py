"""SQL guard: parse the model's SQL and reject anything that is not a read of the allowed views.

Implements specs/query_contract.md "SQL guard". The read-only connection is the second line
of defence; this is the first.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

import sqlglot
from sqlglot import exp
from sqlglot.errors import ParseError

from app import config


@dataclass(frozen=True)
class GuardResult:
    ok: bool
    reason: str = ""
    relations: frozenset[str] = frozenset()


def _reject(reason: str) -> GuardResult:
    return GuardResult(ok=False, reason=reason)


def check_sql(sql: str) -> GuardResult:
    """Return ok=True with the set of referenced relations, or ok=False with the reason."""
    if not sql or not sql.strip():
        return _reject("empty SQL")
    try:
        statements = [s for s in sqlglot.parse(sql, read="duckdb") if s is not None]
    except ParseError as e:
        return _reject(f"could not parse SQL: {str(e).splitlines()[0]}")

    if len(statements) != 1:
        return _reject(f"exactly one statement is allowed, got {len(statements)}")
    stmt = statements[0]
    if not isinstance(stmt, (exp.Select, exp.SetOperation)):
        return _reject(f"only SELECT statements are allowed, got {type(stmt).__name__.upper()}")

    # Table functions and file/network access anywhere in the tree.
    for func in stmt.find_all(exp.Func):
        name = (func.sql_name() if not isinstance(func, exp.Anonymous) else func.name).lower()
        if name in config.BLOCKED_FUNCTIONS or isinstance(func, exp.ReadCSV):
            return _reject(f"function {name!r} is not allowed")

    cte_names = {cte.alias_or_name.lower() for cte in stmt.find_all(exp.CTE)}
    relations: set[str] = set()
    for table in stmt.find_all(exp.Table):
        if not isinstance(table.this, exp.Identifier):
            return _reject(f"table functions are not allowed: {table.sql(dialect='duckdb')}")
        if table.db or table.catalog:
            return _reject(f"qualified relation {table.sql(dialect='duckdb')!r} is not allowed")
        name = table.name.lower()
        if name in cte_names:
            continue  # CTE bodies are walked by find_all, so their relations are still checked
        if name not in config.ALLOWED_RELATIONS:
            return _reject(f"relation {table.name!r} is not in the allow-list {list(config.ALLOWED_RELATIONS)}")
        relations.add(name)

    return GuardResult(ok=True, relations=frozenset(relations))


_PERIOD_RE = re.compile(r"\bmonth\b|\bquarter\b|%m", re.IGNORECASE)


def caveats(sql: str, relations: frozenset[str]) -> list[str]:
    """Rule-based caveats from the query contract, decided from the parsed SQL, never by the model."""
    stmt = sqlglot.parse_one(sql, read="duckdb")
    columns = {c.name.lower() for c in stmt.find_all(exp.Column)}
    out: list[str] = []

    groups_by_account = any(
        any(c.name.lower() == "account_id" for c in g.find_all(exp.Column)) for g in stmt.find_all(exp.Group)
    )
    if "v_accounts" in relations or groups_by_account:
        out.append(config.CAVEATS["accounts"])

    if "amount_usd" in columns:
        out.append(config.CAVEATS["fx"])

    # Month/quarter functions render as MONTH(...), DATE_TRUNC('MONTH', ...), EXTRACT(MONTH FROM ...),
    # STRFTIME(..., '%m'), DATE_PART('quarter', ...). sqlglot's internal names differ, so match the
    # rendered DuckDB text of each function call.
    if any(_PERIOD_RE.search(func.sql(dialect="duckdb")) for func in stmt.find_all(exp.Func)):
        out.append(config.CAVEATS["dates"])

    has_date_predicate = any(
        any(c.name.lower() == "invoice_date" for c in w.find_all(exp.Column)) for w in stmt.find_all(exp.Where)
    )
    if not has_date_predicate or "status_conflict" in columns:
        out.append(config.CAVEATS["status_conflict"])
    return out
