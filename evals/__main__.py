"""Eval harness: `python -m evals` (Tier 1 and 3a) and `python -m evals --nl` (adds 2 and 3b).

Implements specs/evals.md. Rebuilds the database first so it always tests current code
(query contract, Commands). Exit code is non-zero if any case expected to pass fails.
"""
from __future__ import annotations

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
        print("error: Tier 2 and 3b are not built yet", file=sys.stderr)
        return 1

    for o in outcomes:
        print(f"{o.status:<5} {o.id:<4} {o.detail}")
    counts = {s: sum(1 for o in outcomes if o.status == s) for s in ("PASS", "FAIL", "XFAIL", "XPASS")}
    print(f"\npassed {counts['PASS']}, failed {counts['FAIL']}, xfail {counts['XFAIL']}, xpass {counts['XPASS']}"
          f" ({len(outcomes)} cases)")
    return 1 if counts["FAIL"] else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
