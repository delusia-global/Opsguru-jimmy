"""Eval harness: `python -m evals` (Tier 1 and 3a) and `python -m evals --nl` (adds 2 and 3b).

Implements specs/evals.md. Rebuilds the database first so it always tests current code
(query contract, Commands). Exit code is non-zero if any case expected to pass fails.
"""
from __future__ import annotations

import re
import sys
from dataclasses import dataclass
from decimal import Decimal

from app import config, db, guard
from evals import cases


@dataclass
class Outcome:
    id: str
    status: str   # PASS | FAIL | XFAIL | XPASS
    detail: str


def _close(actual, expected) -> bool:
    """Spec 2 tolerances: non-integer numbers ±0.01, everything else exact."""
    if expected is None or actual is None:
        return actual is None and expected is None
    if isinstance(expected, bool) or isinstance(actual, bool):
        return actual == expected
    if isinstance(expected, int):
        return isinstance(actual, (int, Decimal, float)) and actual == expected
    if isinstance(expected, float):
        return isinstance(actual, (int, float, Decimal)) and abs(float(actual) - expected) <= cases.TOLERANCE
    return actual == expected


def _rows_match(actual: list[tuple], expected: list[tuple]) -> bool:
    return len(actual) == len(expected) and all(
        len(a) == len(e) and all(_close(x, y) for x, y in zip(a, e)) for a, e in zip(actual, expected)
    )


def _fmt(rows: list[tuple]) -> str:
    return "; ".join(", ".join("NULL" if v is None else str(v) for v in r) for r in rows)


def run_tier1(con) -> list[Outcome]:
    out = []
    for case in cases.DATA_CASES:
        actual = con.execute(case.sql).fetchall()
        ok = _rows_match(actual, case.expected)
        out.append(Outcome(case.id, "PASS" if ok else "FAIL",
                           f"{case.name}: {_fmt(actual)}" if ok
                           else f"{case.name}: expected {_fmt(case.expected)} got {_fmt(actual)}"))
    for case in cases.QUESTION_CASES:
        try:
            actual = con.execute(case.sql).fetchall()
        except Exception as e:  # a canonical query that does not run is a failure, not a crash
            out.append(Outcome(case.id, "FAIL", f"canonical SQL raised {type(e).__name__}: {e}"))
            continue
        ok = _rows_match(actual, case.expected)
        out.append(Outcome(case.id, "PASS" if ok else "FAIL",
                           _fmt(actual) if ok else f"expected {_fmt(case.expected)} got {_fmt(actual)}"))
    return out


def run_tier3a() -> list[Outcome]:
    out = []
    for case in cases.GUARD_CASES:
        result = guard.check_sql(case.sql)
        if result.ok:
            out.append(Outcome(case.id, "FAIL", f"guard accepted {case.sql!r} ({case.why})"))
        else:
            out.append(Outcome(case.id, "PASS", f"rejected ({case.why}): {result.reason}"))
    return out


# --- Tier 2, 3b and X1: through the question layer (need an API key) -----------------------

def _is_number(v) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def _has_number(rows: list[list], expected: float, tol: float | None = None) -> bool:
    """A number 'appears' in the result set: any cell, any column, within tolerance."""
    if tol is None:
        tol = 0 if isinstance(expected, int) else cases.TOLERANCE
    return any(_is_number(v) and abs(v - expected) <= tol for r in rows for v in r)


def _has_text(rows: list[list], text: str) -> bool:
    return any(isinstance(v, str) and v.strip() == text for r in rows for v in r)


def _ask(question: str) -> dict | None:
    from app import ask

    try:
        return ask.answer(question)
    except Exception as e:  # API outage or similar: report, do not crash the harness
        return {"status": "error", "error": f"{type(e).__name__}: {e}", "sql": None,
                "rows": [], "explanation": None}


def _grade_question(case: cases.QuestionCase, rows: list[list]) -> tuple[bool, str]:
    """The per-case pass rules quoted in specs/evals.md, over the result of the generated SQL."""
    e = case.expected
    if case.id == "Q1":
        net, paid = _has_number(rows, e[0][0]), _has_number(rows, e[0][1])
        return net or paid, f"net {'present' if net else 'absent'}, paid {'present' if paid else 'absent'}"
    if case.id == "Q2":
        first = rows[0] if rows else []
        ok = any(isinstance(v, str) and v.strip() == e[0][0] for v in first) and _has_number(rows, e[0][1])
        return ok, f"first row {first}"
    if case.id == "Q3":
        # passes on the amount alone (either sign); the count is printed, not required
        amount = _has_number(rows, e[0][0]) or _has_number(rows, abs(e[0][0]))
        count = _has_number(rows, e[0][1])
        return amount, f"amount {'present' if amount else 'absent'}, count {'present' if count else 'absent'} (not required)"
    if case.id == "Q4":
        # passes on the two rates (percentage or fraction); counts are printed, not required
        missing, counts = [], []
        for plan, churned, accounts, rate in e:
            if not (_has_number(rows, rate) or _has_number(rows, rate / 100, 0.0001)):
                missing.append(f"{plan} rate {rate}")
            counts.append(f"{plan} {churned}/{accounts} "
                          f"{'present' if _has_number(rows, churned) and _has_number(rows, accounts) else 'absent'}")
        detail = ("both rates present" if not missing else f"missing {missing}") + f"; counts {', '.join(counts)} (not required)"
        return not missing, detail
    if case.id == "Q5":
        ids = [r[0] for r in e]
        found = []
        for r in rows:
            found += [v for v in r if isinstance(v, str) and v.strip().startswith("ACC-")]
        return found[:5] == ids and len(rows) >= 5, f"account order {found[:5]}"
    if case.id == "Q6":
        total = _has_number(rows, e[2][1]) and _has_number(rows, e[2][2])
        per_status = all(_has_number(rows, r[1]) and _has_number(rows, r[2]) for r in e[:2])
        return total or per_status, f"total row {'present' if total else 'absent'}, per-status rows {'present' if per_status else 'absent'}"
    raise ValueError(f"no Tier 2 rule for {case.id}")


def run_tier2() -> list[Outcome]:
    out = []
    for case in cases.QUESTION_CASES:
        result = _ask(case.question)
        print(f"-- {case.id} generated SQL ({result['status']}):\n{result.get('sql') or '(none)'}\n")
        if result["status"] != "ok":
            out.append(Outcome(case.id, "FAIL", f"question layer returned {result['status']}: "
                               f"{result.get('error') or result.get('explanation')}"))
            continue
        ok, detail = _grade_question(case, result["rows"])
        out.append(Outcome(case.id, "PASS" if ok else "FAIL", f"[NL] {detail}"))
    return out


_FORECAST_RE = re.compile(r"(cannot|can't|can not|unable|not able|does not|doesn't|no way|not possible|not contain)"
                          r".{0,80}(forecast|predict|future|next year)|"
                          r"(forecast|predict|future|next year).{0,80}(cannot|can't|unable|not possible|not contain)",
                          re.IGNORECASE | re.DOTALL)


def run_tier3b() -> list[Outcome]:
    out = []
    for case in cases.NL_GUARD_CASES:
        result = _ask(case.question)
        print(f"-- {case.id} generated SQL ({result['status']}):\n{result.get('sql') or '(none)'}\n")
        text = result.get("explanation") or ""
        if result["status"] == "refused":
            out.append(Outcome(case.id, "PASS", f"refused: {text[:120]}"))
        elif case.id == "G6" and result["status"] == "ok" and _FORECAST_RE.search(text):
            out.append(Outcome(case.id, "PASS", f"answered with an explicit cannot-forecast statement: {text[:120]}"))
        else:
            out.append(Outcome(case.id, "FAIL", f"expected {case.expected}, got status {result['status']}: "
                               f"{(result.get('error') or text)[:120]}"))
    return out


def run_xfail() -> Outcome:
    """X1: finance expects ACC-1196 flagged; the system, reading CSAT from v_accounts, flags nothing."""
    case = cases.XFAIL_CASE
    result = _ask(case.question)
    print(f"-- {case.id} generated SQL ({result['status']}):\n{result.get('sql') or '(none)'}\n")
    rows = result.get("rows") or []
    # Two answer shapes: a flag column (flagged = rows with a TRUE cell; NULL CSAT gives a NULL
    # cell, not a boolean) or a filtered list with no boolean column at all (flagged = every row).
    has_flag_column = any(isinstance(v, bool) for r in rows for v in r)
    flagged: list[str] = []
    for r in rows:
        ids = [v for v in r if isinstance(v, str) and v.strip().startswith("ACC-")]
        if ids and (any(v is True for v in r) if has_flag_column else True):
            flagged += ids
    system_answer = (f"status {result['status']}, flagged {flagged or 'nothing'}"
                     if result["status"] == "ok" else f"status {result['status']}: {result.get('error') or result.get('explanation')}")
    both = f"finance expects {case.finance_expects} flagged; system answers: {system_answer}. Why: {case.why}"
    if case.finance_expects in flagged:
        return Outcome(case.id, "XPASS", both + " -- look at why this now passes")
    return Outcome(case.id, "XFAIL", both)


def main(argv: list[str]) -> int:
    nl = "--nl" in argv
    if nl and not config.ANTHROPIC_API_KEY:
        print(f"error: --nl needs {config.ANTHROPIC_API_KEY_VAR}; see .env.example", file=sys.stderr)
        return 1
    if not config.RAW_CSV_PATH.exists():
        print(f"error: raw CSV not found at {config.RAW_CSV_PATH} (set RAW_CSV_PATH in .env)", file=sys.stderr)
        return 1

    print(f"Rebuilding {config.DB_PATH} from {config.RAW_CSV_PATH} ...")
    db.build()
    con = db.connect(read_only=True)
    try:
        outcomes = run_tier1(con)
    finally:
        con.close()
    outcomes += run_tier3a()
    if nl:
        outcomes += run_tier2()
        outcomes += run_tier3b()
        outcomes.append(run_xfail())

    for o in outcomes:
        print(f"{o.status:<5} {o.id:<4} {o.detail}")
    counts = {s: sum(1 for o in outcomes if o.status == s) for s in ("PASS", "FAIL", "XFAIL", "XPASS")}
    print(f"\npassed {counts['PASS']}, failed {counts['FAIL']}, xfail {counts['XFAIL']}, xpass {counts['XPASS']}"
          f" ({len(outcomes)} cases)")
    return 1 if counts["FAIL"] else 0


if __name__ == "__main__":
    for stream in (sys.stdout, sys.stderr):  # questions and model text may be non-ASCII
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")
    sys.exit(main(sys.argv[1:]))
