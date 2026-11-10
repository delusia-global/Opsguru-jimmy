"""CLI entry point: `python -m app build`, `python -m app ask "<question>"`, `python -m app`."""
from __future__ import annotations

import sys

from app import config


def _fail(message: str, code: int = 1) -> int:
    print(f"error: {message}", file=sys.stderr)
    return code


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


def main(argv: list[str]) -> int:
    if not argv:
        return _fail("the demo (question layer) is not built yet; run `python -m app build`", 2)
    command, args = argv[0], argv[1:]
    if command == "build":
        return cmd_build()
    if command == "ask":
        return _fail("the question layer is not built yet; run `python -m app build`", 2)
    return _fail(f"unknown command {command!r}; use build or ask", 2)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
