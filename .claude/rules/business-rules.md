# Business rules that are easy to get wrong

Short reminders. The full rules and the evidence are in `specs/schema.md`.

- **Revenue** is net: paid invoices plus refunded invoices, and refund amounts are negative.
  Pending, failed and void are never revenue.
- **`amount` is already net of discount.** Applying `discount_pct` to it double-discounts.
- **MRR** = list price × seats × (1 − discount/100), list prices 49 / 99 / 299 USD. It comes
  from the subscription terms, not from the invoice amount. An annual invoice is 10 months of
  billing but the same MRR as a monthly one.
- **FX** follows the briefing: USD = local × rate (EUR 1.08, GBP 1.27). The data suggests the
  local amounts are already rate-adjusted. That is a documented open question, not something
  to fix in code.
- **Dates**: `01/05/2024` is month-first, `05-01-2024` is day-first. The separator decides.
- **Dedup order**: exact duplicates first, then near-duplicates by `invoice_id`, where the
  latest lifecycle state wins: refunded > void > paid > failed > pending.
- **Accounts**: `account_id` is the key, attributes come from the latest invoice, and the key
  is known to be unreliable. Say so wherever per-account numbers are shown.
- **Unknown values** go to `quarantine`. Never map an unrecognised category to the nearest
  known one.
