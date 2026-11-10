"""The model call: question in, SQL (or a refusal) out. The model never sees query results.

Implements specs/query_contract.md flow steps 2 and 5 and "What the model is told".
Call shape confirmed against the Anthropic Python SDK reference (structured outputs via
`output_config.format` on `messages.create`).
"""
from __future__ import annotations

import json
from dataclasses import dataclass

import anthropic

from app import config

# {"sql", "explanation"} or {"refusal"} — the contract's structured output.
OUTPUT_SCHEMA = {
    "type": "object",
    "properties": {
        "sql": {"type": ["string", "null"], "description": "One DuckDB SELECT, or null when refusing."},
        "explanation": {"type": ["string", "null"],
                        "description": "One sentence saying what the query computes. No numbers."},
        "refusal": {"type": ["string", "null"], "description": "Why the question cannot be answered, else null."},
    },
    "required": ["sql", "explanation", "refusal"],
    "additionalProperties": False,
}


@dataclass
class ModelReply:
    sql: str | None
    explanation: str | None
    refusal: str | None
    model: str


def glossary() -> str:
    """The business glossary from the contract, with the numbers filled in from config."""
    prices = ", ".join(f"{p} {v:g}" for p, v in config.LIST_PRICE_USD.items())
    fx = ", ".join(f"{c} {r}" for c, r in config.FX_RATES.items())
    revenue = " and ".join(config.REVENUE_STATUSES)
    exposure = " or ".join(config.OPEN_EXPOSURE_STATUSES)
    return "\n".join([
        f"- Use v_recognized_revenue for anything called revenue. It holds status {revenue}. Revenue is net: "
        "paid plus refunds (refund amounts are negative). Show the paid and refund components as separate columns.",
        "- Use amount_usd for money. Never sum amount_local across currencies. "
        f"amount_usd = amount_local × fixed rate ({fx}).",
        "- amount_usd is already net of discount. Never apply discount_pct to it.",
        f"- Use mrr_usd for MRR. Never derive MRR from invoice amounts. (List prices per seat per month, USD: {prices}.)",
        "- Use v_accounts for anything \"per account\", for churn, and for account attributes such as CSAT. "
        "One row per account. \"MRR per account\" means WHERE is_active.",
        f"- Use v_open_exposure for {exposure} invoices.",
        "- Dates: invoice_date decides the period of an invoice or refund.",
        "- If the question asks for a change to data, a forecast, or something the ledger does not contain, "
        "return a refusal that says why.",
    ])


def system_prompt(schema: dict[str, list[tuple[str, str]]]) -> str:
    relations = "\n".join(
        f"- {rel}({', '.join(f'{c} {t}' for c, t in cols)})" for rel, cols in schema.items()
    )
    return (
        "You translate one finance question about a cleaned invoice ledger into one DuckDB SQL query.\n"
        "You write SQL, never numbers: you will not see the result, so do not guess or state any figure.\n\n"
        "Rules:\n"
        "- Exactly one SELECT statement (CTEs allowed). No DDL, DML, PRAGMA, file or network access.\n"
        f"- Only these relations exist: {', '.join(schema)}. Columns:\n{relations}\n"
        "- Round money to 2 decimals in the final SELECT only, after any SUM.\n"
        "- Prefer aggregates; if listing rows, add ORDER BY and LIMIT.\n\n"
        "Glossary:\n" + glossary() + "\n\n"
        "Respond with JSON: {\"sql\": ..., \"explanation\": ..., \"refusal\": null} where explanation is one "
        "sentence saying what the query computes, or {\"sql\": null, \"explanation\": null, \"refusal\": ...}."
    )


def generate_sql(question: str, schema: dict[str, list[tuple[str, str]]],
                 previous_sql: str | None = None, error: str | None = None) -> ModelReply:
    """One model call. With `previous_sql` and `error`, ask once for a corrected query (step 5)."""
    client = anthropic.Anthropic(api_key=config.ANTHROPIC_API_KEY)
    content = f"Question: {question}"
    if previous_sql and error:
        content += (f"\n\nYour previous query failed to execute.\nSQL:\n{previous_sql}\n"
                    f"Database error: {error}\nReturn a corrected query for the same question.")
    response = client.messages.create(
        model=config.ANTHROPIC_MODEL,
        max_tokens=config.LLM_MAX_TOKENS,
        system=system_prompt(schema),
        messages=[{"role": "user", "content": content}],
        output_config={"format": {"type": "json_schema", "schema": OUTPUT_SCHEMA}},
    )
    if response.stop_reason == "refusal":
        why = getattr(response.stop_details, "explanation", None) or "the model declined the request"
        return ModelReply(sql=None, explanation=None, refusal=str(why), model=response.model)
    text = next((b.text for b in response.content if b.type == "text"), "")
    data = json.loads(text)
    sql = (data.get("sql") or "").strip() or None
    return ModelReply(sql=sql, explanation=data.get("explanation"), refusal=data.get("refusal"),
                      model=response.model)
