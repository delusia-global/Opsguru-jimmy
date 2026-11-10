"""Flow for one question: validate, model, guard, execute, retry once, print.

Implements specs/query_contract.md "Flow for one question", "Output (--json)" and the caveat
rules. Numbers come only from the query result.
"""
from __future__ import annotations

import datetime as dt
import json
import time
from decimal import Decimal

import anthropic
import duckdb

from app import config, db, guard, llm


class UserError(Exception):
    """An error the user can fix; printed as one line with a non-zero exit."""


def validate_question(question: str) -> str:
    q = (question or "").strip()
    if not q:
        raise UserError("question is empty")
    if len(q) > config.QUESTION_MAX_CHARS:
        raise UserError(f"question is longer than {config.QUESTION_MAX_CHARS} characters")
    return q


def _plain(value):
    """Result cells as JSON-friendly values: Decimal -> float, dates -> ISO strings."""
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, (dt.date, dt.datetime)):
        return value.isoformat()
    return value


def answer(question: str) -> dict:
    """Run the whole flow and return the `--json` object (contract, Output)."""
    started = time.perf_counter()
    question = validate_question(question)
    result = {
        "question": question, "status": "error", "explanation": None, "sql": None,
        "columns": [], "rows": [], "row_count": 0, "truncated": False, "caveats": [],
        "model": config.ANTHROPIC_MODEL, "latency_ms": 0, "retried": False, "error": None,
    }

    def finish(status: str, error: str | None = None) -> dict:
        result["status"], result["error"] = status, error
        result["latency_ms"] = int((time.perf_counter() - started) * 1000)
        return result

    db.ensure_built()
    con = db.connect(read_only=True)
    try:
        schema = db.describe_relations(con)
        previous_sql, error = None, None
        for attempt in (1, 2):                      # one retry only (step 5)
            try:
                reply = llm.generate_sql(question, schema, previous_sql, error)
            except anthropic.APIError as e:
                return finish("error", f"model call failed: {type(e).__name__}: {str(e).splitlines()[0]}")
            except (json.JSONDecodeError, ValueError, AttributeError) as e:
                return finish("error", f"model reply was not the expected JSON: {str(e).splitlines()[0]}")
            result["model"], result["retried"] = reply.model, attempt == 2
            if reply.refusal or not reply.sql:
                result["explanation"] = reply.refusal or reply.explanation
                return finish("refused")
            result["sql"], result["explanation"] = reply.sql, reply.explanation
            verdict = guard.check_sql(reply.sql)   # step 3: never execute rejected SQL
            if not verdict.ok:
                return finish("rejected", f"SQL rejected by guard: {verdict.reason}")
            try:
                qr = db.run_query(con, reply.sql)   # step 4
            except (duckdb.Error, db.QueryTimeout) as e:
                previous_sql, error = reply.sql, str(e).splitlines()[0]
                if attempt == 2 or isinstance(e, db.QueryTimeout):
                    return finish("error", f"query failed: {error}")
                continue
            result.update(columns=qr.columns, rows=[[_plain(v) for v in r] for r in qr.rows],
                          row_count=len(qr.rows), truncated=qr.truncated,
                          caveats=guard.caveats(reply.sql, verdict.relations))
            return finish("ok")
    finally:
        con.close()
    return finish("error", "unreachable")  # pragma: no cover


def format_table(columns: list[str], rows: list[list]) -> str:
    if not columns:
        return "(no columns)"
    cells = [[("NULL" if v is None else str(v)) for v in r] for r in rows]
    widths = [max(len(c), *(len(r[i]) for r in cells)) if cells else len(c) for i, c in enumerate(columns)]
    line = lambda vals: "  ".join(v.ljust(widths[i]) for i, v in enumerate(vals))
    out = [line(columns), line(["-" * w for w in widths])]
    out += [line(r) for r in cells] or ["(no rows)"]
    return "\n".join(out)


def render(result: dict) -> str:
    """Step 6: question, explanation, SQL, result table, caveats."""
    parts = [f"Question: {result['question']}", f"Status: {result['status']}"]
    if result["explanation"]:
        parts.append(f"Explanation: {result['explanation']}")
    if result["sql"]:
        parts.append(f"SQL:\n{result['sql']}")
    if result["status"] == "ok":
        parts.append(format_table(result["columns"], result["rows"]))
        if result["truncated"]:
            parts.append(f"(truncated to {config.QUERY_ROW_CAP} rows)")
    if result["error"]:
        parts.append(f"Error: {result['error']}")
    if result["caveats"]:
        parts.append("Caveats:\n" + "\n".join(f"- {c}" for c in result["caveats"]))
    parts.append(f"[{result['model']}, {result['latency_ms']} ms" + (", retried" if result["retried"] else "") + "]")
    return "\n".join(parts)


def to_json(result: dict) -> str:
    return json.dumps(result, ensure_ascii=False)
