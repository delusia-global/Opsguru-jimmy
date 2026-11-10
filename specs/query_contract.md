# Spec 3 — Question interface contract

A finance user types a question in plain English and gets back a number they can check.

## Principle: the model writes SQL, never numbers

The model's only job is to translate the question into one SQL query over the cleaned data.
Every number shown to the user comes from executing that query. The model does not see the
result and does not restate figures, so it cannot misquote them. The generated SQL is always
shown, so the answer is auditable.

## Commands

| Command | Does |
|---|---|
| `python -m app` | **The demo.** Builds the database if missing, then answers the six stakeholder questions from `data/BUSINESS_CONTEXT.md` |
| `python -m app build` | Runs the pipeline (Spec 1) and prints the data-quality report |
| `python -m app ask "<question>"` | Answers one question |
| `python -m app ask "<question>" --json` | Same, as one JSON object on stdout |
| `python -m evals` | Tier 1 and 3a evals (no API key) |
| `python -m evals --nl` | Adds Tier 2 and 3b (needs API key) |

`ask` and the demo need `ANTHROPIC_API_KEY`. If it is missing, exit with a one-line message
that names the variable and points to `.env.example`. `build` and `python -m evals` must work
without it.

## Flow for one question

1. Validate input: non-empty, at most 500 characters.
2. Call the model once with: the schema of the allowed relations, the business glossary
   (below), and the question. Request structured output:
   `{"sql": string, "explanation": string}` or `{"refusal": string}`.
3. Pass the SQL through the guard (below). On rejection, do not execute; report the reason.
4. Execute on a **read-only** DuckDB connection with a row cap and a timeout.
5. If execution raises a SQL error, send the error back to the model once for a corrected
   query, guard it again, and execute. One retry only.
6. Print: the question, the model's one-sentence explanation of what the query computes, the
   SQL, the result table, and any caveats (below).

## Output (`--json`)

```json
{
  "question": "...",
  "status": "ok | refused | rejected | error",
  "explanation": "what the query computes, written before execution",
  "sql": "SELECT ...",
  "columns": ["..."],
  "rows": [["..."]],
  "row_count": 4,
  "truncated": false,
  "caveats": ["..."],
  "model": "...",
  "latency_ms": 0,
  "retried": false
}
```

## SQL guard

Reject unless all of these hold. Parse the SQL; do not use string matching alone.

- Exactly one statement, and it is a `SELECT` (CTEs allowed).
- Every relation referenced is in the allow-list: `invoices`, `v_recognized_revenue`,
  `v_open_exposure`, `v_accounts`. `quarantine` and `dq_report` are not exposed.
- No table functions or file/network access (`read_csv`, `read_parquet`, `glob`, `ATTACH`,
  `COPY`, `INSTALL`, `LOAD`, `PRAGMA`, …).
- Results are capped at 200 rows; set `truncated` when the cap applies.

The read-only connection is the second line of defence, not the first.

## What the model is told (the glossary)

Generated from Spec 1 at prompt-build time where possible, so the two cannot drift:

- Use `v_recognized_revenue` for anything called revenue. Revenue is net: paid plus refunds
  (refund amounts are negative). Show the paid and refund components.
- Use `amount_usd` for money. Never sum `amount_local` across currencies.
- `amount_usd` is already net of discount. Never apply `discount_pct` to it.
- Use `mrr_usd` for MRR. Never derive MRR from invoice amounts.
- Use `v_accounts` for anything "per account", for churn, and for account attributes such as
  CSAT. One row per account. "MRR per account" means `WHERE is_active`.
- Use `v_open_exposure` for pending or failed invoices.
- Dates: `invoice_date` decides the period of an invoice or refund.
- If the question asks for a change to data, a forecast, or something the ledger does not
  contain, return a refusal that says why.

## Caveats (rule-based, appended by code, not by the model)

| Trigger in the SQL | Caveat |
|---|---|
| references `v_accounts` or groups by `account_id` | Account IDs are not a stable key in this export; per-account figures are approximate. |
| uses `amount_usd` | Non-USD amounts are converted at fixed rates as briefed; the source data suggests they may already be rate-adjusted. |
| filters or groups by month or quarter | 81 invoices have dates whose day/month order was inferred from the separator. |
| result includes rows with `status_conflict` or no date filter | 16 invoices had conflicting statuses across source systems; the latest lifecycle state was used. |

## Not in scope

Multi-turn conversation, charts, forecasting, write access, authentication, multi-user
serving. See "Next steps" in the README.
