"""CLI entry point: `python -m app` (demo), `python -m app build`, `python -m app ask "<question>" [--json]`.

Implements specs/query_contract.md "Commands".
"""
from __future__ import annotations

import sys

from app import config


def _fail(message: str, code: int = 1) -> int:
    print(f"error: {message}", file=sys.stderr)
    return code


def _require_key() -> str | None:
    if not config.ANTHROPIC_API_KEY:
        return f"{config.ANTHROPIC_API_KEY_VAR} is not set; copy .env.example to .env and add your key"
    return None


def cmd_build() -> int:
    from app import db

    if not config.RAW_CSV_PATH.exists():
        return _fail(f"raw CSV not found at {config.RAW_CSV_PATH} (set RAW_CSV_PATH in .env)")
    result = db.build()
    print(f"Built {config.DB_PATH} (as of {config.AS_OF_DATE})")
    print("\nData-quality report")
    for name, value in result.dq_report:
        print(f"  {name:<30} {value:>8}")
    if len(result.quarantine):
        print("\nQuarantine reasons")
        for reason, n in result.quarantine["reason"].value_counts().items():
            print(f"  {n:>5}  {reason}")
    return 0


def cmd_ask(args: list[str]) -> int:
    from app import ask

    if problem := _require_key():
        return _fail(problem)
    as_json = "--json" in args
    words = [a for a in args if a != "--json"]
    if not words:
        return _fail('usage: python -m app ask "<question>" [--json]', 2)
    try:
        result = ask.answer(" ".join(words))
    except ask.UserError as e:
        return _fail(str(e))
    except FileNotFoundError as e:
        return _fail(str(e))
    print(ask.to_json(result) if as_json else ask.render(result))
    return 0 if result["status"] in ("ok", "refused") else 1


def cmd_demo() -> int:
    from app import ask

    if problem := _require_key():
        return _fail(problem)
    if not config.RAW_CSV_PATH.exists() and not config.DB_PATH.exists():
        return _fail(f"raw CSV not found at {config.RAW_CSV_PATH} (set RAW_CSV_PATH in .env)")
    worst = 0
    for i, question in enumerate(config.DEMO_QUESTIONS, 1):
        print(f"\n=== {i}/{len(config.DEMO_QUESTIONS)} " + "=" * 60)
        result = ask.answer(question)
        print(ask.render(result))
        worst = max(worst, 0 if result["status"] in ("ok", "refused") else 1)
    return worst


def main(argv: list[str]) -> int:
    if not argv:
        return cmd_demo()
    command, args = argv[0], argv[1:]
    if command == "build":
        return cmd_build()
    if command == "ask":
        return cmd_ask(args)
    return _fail(f"unknown command {command!r}; use build or ask, or no command for the demo", 2)


if __name__ == "__main__":
    # Questions and results may contain non-ASCII (e.g. "≤", "€"); Windows consoles default to cp1252.
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")
    sys.exit(main(sys.argv[1:]))
