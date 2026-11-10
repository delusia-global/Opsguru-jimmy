# CloudNova revenue Q&A — project instructions

A take-home build: clean a dirty invoice ledger and answer finance questions in plain English
with the SQL shown. Timebox is about one hour, so prefer the smallest thing that satisfies the
spec.

## The specs are the source of truth

- `specs/schema.md` — cleaned schema, normalisation, dedup, FX, MRR, accounts
- `specs/query_contract.md` — CLI, question flow, SQL guard, caveats
- `specs/evals.md` — eval cases and expected values
- `data/BUSINESS_CONTEXT.md` — the customer's briefing the specs were written from

Rules for working with them:

1. Read the relevant spec before writing or changing code. Cite the section you are
   implementing in your summary.
2. If the spec is ambiguous, silent, or looks wrong, **stop and ask me**. Do not pick an
   interpretation and continue.
3. Never change a business rule in code. If a rule must change, I change the spec first.
4. Never edit expected values in `specs/evals.md` or the eval harness to make a case pass.
   A failing eval means the code or the spec is wrong; tell me which you think it is.
5. `scripts/derive_expected.py` is the independent oracle for the evals. Do not import it,
   copy from it, or read it while implementing the pipeline.

## Stack and layout

Python 3.11+, pandas for cleaning, DuckDB for storage and querying, the Anthropic Python SDK
for the question layer, sqlglot for the SQL guard, python-dotenv for config. No frameworks.

```
app/        config.py, pipeline.py, db.py, guard.py, llm.py, ask.py, __main__.py
evals/      __main__.py, cases.py
specs/      the three specs
data/       raw CSV and business context (read-only)
docs/       architecture diagram, data profile, session log
scripts/    profiling and the eval oracle
build/      generated database (gitignored)
```

## Commands

- `python -m app build` — run the pipeline, print the data-quality report
- `python -m app` — demo: the six stakeholder questions
- `python -m app ask "question"` — one question
- `python -m evals` — pipeline and guard evals, no API key needed
- `python -m evals --nl` — adds the question-layer evals, needs `ANTHROPIC_API_KEY`

Run `python -m evals` after every change to `app/` and report the pass/fail line.

## Conventions

- Config comes from environment variables via `app/config.py`. No paths, rates, prices, model
  names or mappings hardcoded anywhere else.
- Rows that fail a rule go to `quarantine` with a reason. No silent drops, no guessed values.
- Errors a user can cause (missing key, missing CSV, empty question) get a one-line message
  and a non-zero exit, not a traceback.
- Never read, print or commit `.env`. Never put a key in code, tests, logs or docs.
- Before using the Anthropic SDK, check the current API docs for the call shape and the model
  ID instead of relying on memory. The model ID comes from `ANTHROPIC_MODEL`.
- Small commits, one concern each. I run `git commit` and `git push` myself; propose the
  message.

## Do not

- Add a web UI, an API server, a vector store, caching, or Docker. Out of scope.
- Let the model produce or restate numbers. Numbers come only from query results.
- Modify anything in `data/`.
