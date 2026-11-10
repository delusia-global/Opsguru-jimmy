# Spec 1 — Cleaned schema and transformation rules

Status: **approved, drives the build.** If code and this spec disagree, the code is wrong.
Change the spec first, in its own commit, then change the code.

Source of the business rules: `data/BUSINESS_CONTEXT.md`.
Source of the evidence quoted below: `docs/data-profile.md` (profile of all 5,125 raw rows).

## 1. Input

`data/cloudnova_invoices.csv` — 19 columns, every column read as text. One row = one invoice.
No column is trusted to be typed, trimmed or consistently cased.

## 2. Output

A local DuckDB file (path from config, default `build/cloudnova.duckdb`) containing:

| Object | Kind | Purpose |
|---|---|---|
| `invoices` | table | One row per `invoice_id`, typed and normalised (section 3) |
| `quarantine` | table | Raw rows that could not be cleaned, with a `reason` |
| `dq_report` | table | One row per data-quality check: `check_name`, `value` |
| `v_recognized_revenue` | view | `invoices` where `status IN ('paid','refunded')` |
| `v_open_exposure` | view | `invoices` where `status IN ('pending','failed')` |
| `v_accounts` | view | One row per `account_id`, taken from its latest invoice (section 6) |

The views are the semantic layer. The question interface (Spec 3) queries the views so that
business rules live in one place and are not re-derived per question.

## 3. `invoices` columns

| Column | Type | Null? | Rule |
|---|---|---|---|
| `invoice_id` | VARCHAR | no | Primary key. Must match `INV-` + 6 digits |
| `account_id` | VARCHAR | no | Must match `ACC-` + 4 digits |
| `account_name` | VARCHAR | no | Trimmed |
| `contact_email` | VARCHAR | yes | Trim, lower-case, replace `_at_` with `@`. Blank → NULL |
| `email_was_repaired` | BOOLEAN | no | True when `_at_` was replaced |
| `region` | VARCHAR | no | One of `NA`, `EMEA`, `APAC`, `LATAM` |
| `industry` | VARCHAR | yes | Trimmed. Blank → NULL (never "Unknown") |
| `plan` | VARCHAR | no | `Starter` / `Pro` / `Enterprise` (mapping 4.1) |
| `billing_cycle` | VARCHAR | no | `monthly` / `annual` (mapping 4.2) |
| `seats` | INTEGER | no | > 0 |
| `currency` | VARCHAR | no | `USD` / `EUR` / `GBP` |
| `amount_local` | DECIMAL(14,2) | no | Parsed per 4.5. Signed: negative only for refunds |
| `amount_usd` | DECIMAL(18,4) | no | `amount_local × fx[currency]`, exact, never rounded per row (section 5) |
| `discount_pct` | DECIMAL(5,2) | no | 0–100 |
| `status` | VARCHAR | no | `paid` / `pending` / `failed` / `refunded` / `void` (mapping 4.3) |
| `payment_method` | VARCHAR | yes | `credit_card` / `ach` / `wire` / `invoice` (mapping 4.4). Blank → NULL |
| `signup_date` | DATE | no | Parsed per 4.6 |
| `invoice_date` | DATE | no | Parsed per 4.6 |
| `churned` | BOOLEAN | no | Mapping 4.7 |
| `csat_score` | INTEGER | yes | 1–5. Blank → NULL |
| `support_tickets` | INTEGER | no | ≥ 0 |
| `mrr_usd` | DECIMAL(14,2) | no | `list_price[plan] × seats × (1 − discount_pct/100)` |
| `status_conflict` | BOOLEAN | no | True when source systems disagreed on status (section 7) |
| `is_future_dated` | BOOLEAN | no | `invoice_date > AS_OF_DATE` (config) |
| `amount_matches_formula` | BOOLEAN | no | Sanity flag, see 5.3 |
| `source_row` | INTEGER | no | 1-based line number of the surviving row in the raw CSV, for citation |

Any raw value that does not fit a mapping or constraint sends the whole row to `quarantine`
with a reason. **Never guess, never coerce silently.** On the provided file the expected
quarantine count is 0; the eval harness asserts it.

## 4. Normalisation rules

All mappings are applied after `strip()` and `lower()`. They live in one config module, not
scattered through the code.

### 4.1 plan
| Canonical | Raw variants |
|---|---|
| Starter | `starter`, `start`, `tier 1` |
| Pro | `pro`, `professional`, `tier 2` |
| Enterprise | `enterprise`, `ent`, `tier 3` |

`Start`, `ENT` and `Tier 1/3` are not in the business briefing; they were found by profiling.

### 4.2 billing_cycle
`monthly` ← `monthly`. `annual` ← `annual`, `annually`, `yearly`.

### 4.3 status
| Canonical | Raw variants | Revenue? |
|---|---|---|
| paid | `paid`, `complete`, `completed`, `success` | yes |
| pending | `pending`, `in_review`, `awaiting` | no |
| failed | `failed`, `declined`, `error` | no |
| refunded | `refunded`, `refund`, `charged_back` | negative, nets out |
| void | `void`, `cancelled`, `canceled` | no |

### 4.4 payment_method
`credit_card` ← `credit_card`, `credit card`. `ach` ← `ach`. `wire` ← `wire`, `wire transfer`.
`invoice` ← `invoice`.

### 4.5 amount
Accepted raw shapes: `52920.00`, `31432` (no cents), `$4,900.00`, `$-4,900.00`, `£28,003.50`,
`€1,200.00`, `4,165.00 USD`. Strip currency symbol, currency code, thousands commas and
spaces; keep the sign.

- If the symbol or code in the amount string disagrees with the `currency` column → quarantine.
- Sign must agree with status: negative ⇔ `refunded`. Checked **after** dedup → quarantine on mismatch.

### 4.6 dates
| Raw shape | Read as | Evidence |
|---|---|---|
| `2024-01-05` | ISO, YYYY-MM-DD | unambiguous |
| `2024/01/05` | YYYY/MM/DD | unambiguous |
| `Jan 5 2024` | month name | unambiguous |
| `01/05/2024` | **MM/DD/YYYY** | first part never exceeds 12 in 2,579 slash dates |
| `05-01-2024` | **DD-MM-YYYY** | second part never exceeds 12 in 532 dash dates; first part exceeds 12 in 313 |

Decision: the separator carries the convention (slash = US month-first, dash = day-first).
This is an inference from the data, not a fact confirmed by CloudNova. It affects the month
of 81 invoices and the year of none. Anything that parses under no format → quarantine.

### 4.7 churned
True ← `true`, `yes`, `1`, `y`. False ← `false`, `no`, `0`, `n`. Anything else → quarantine.

### 4.8 other typed columns
`seats`, `support_tickets` and `csat_score` parse as strict integers (digits only, optional
sign) after `strip()`; `discount_pct` as a strict decimal. `region` and `currency` are
stripped and upper-cased and must be in their allowed sets (section 3). Anything else →
quarantine. No other coercion.

## 5. Money

### 5.1 FX (fixed reference rates, from config)
`USD = 1.00`, `EUR = 1.08`, `GBP = 1.27`. `amount_usd = amount_local × rate`, as the briefing states.

`amount_usd` is stored as the exact product (2 dp × 2 dp is exact at 4 dp) and is never
rounded per row. Rounding to 2 dp happens only in the final `SELECT` of a query, after any
`SUM`. The eval expected values were derived the same way: unrounded products, rounded once
at the end. `mrr_usd` stays DECIMAL(14,2); it is exact at 2 dp.

### 5.2 Known issue with 5.1 — flagged, not fixed
Every EUR/GBP amount in the file already equals *USD list price × rate*. Multiplying by the
rate again reports a $747,500 list-price invoice billed in GBP as $1,205,642.75. We follow the
briefing as written because it is the customer's stated rule, and we surface the discrepancy
in the README as an open question for finance. Size of the question: 2024 net revenue is
$30,755,088.25 under the briefing's rule and $27,823,962.37 if amounts were divided instead.

### 5.3 Amount sanity flag
`amount_matches_formula` is true when
`|amount_local| ≈ list_price × seats × (10 if annual else 1) × (1 − discount_pct/100) × rate`
within 1.00. This holds for all 5,125 raw rows, which tells us two things:
- **`amount` is already net of discount.** Never apply `discount_pct` to `amount` again.
- Annual invoices bill 10 months, as the briefing says.

A false flag does not quarantine the row; it is reported in `dq_report`.

### 5.4 Recognised revenue
Recognised revenue = `SUM(amount_usd)` over `v_recognized_revenue`, i.e. paid invoices plus
refunded invoices (negative). "Revenue" in any answer means this **net** figure; answers also
show the paid and refund components separately. A refund is attributed to the period of the
refund row's `invoice_date`.

### 5.5 MRR
`mrr_usd = list_price[plan] × seats × (1 − discount_pct/100)`, list prices Starter 49, Pro 99,
Enterprise 299, already in USD. It is derived from the subscription terms, never from
`amount`, so annual invoices are not double-counted and FX does not apply.

## 6. Accounts (`v_accounts`)

One row per `account_id`. Attributes (`account_name`, `region`, `industry`, `plan`, `seats`,
`discount_pct`, `churned`, `csat_score`, `support_tickets`, `mrr_usd`) come from that account's
**latest invoice**: highest `invoice_date`, ties broken by highest `invoice_id`. Any status
counts when choosing the latest invoice.

- `latest_status`, `latest_invoice_date`, `latest_invoice_id`: from that invoice. The ID is
  there for citation.
- `is_active` = `latest_status = 'paid' AND NOT churned`. "MRR per account" questions use
  active accounts only.
- Churn rate for a group = churned accounts ÷ all accounts in the group.

### Known limitation — `account_id` is not a stable key
Of 980 account IDs with more than one invoice, 976 carry more than one account name, and most
also change region and signup date. We treat `account_id` as the key because the data
dictionary defines it as the account, and we take attributes from the latest invoice so that
each account has exactly one value per attribute. Per-account answers are therefore only as
good as this key. This is stated in the README and is the reason for the expected-fail eval.

## 7. Deduplication (in this order)

1. **Exact duplicates.** Rows identical in all 19 raw columns → keep the first by file order.
   Expected: 82 rows dropped.
2. **Near-duplicates.** Rows sharing an `invoice_id` after step 1. Expected: 43 invoice IDs,
   two rows each, differing only in `status`.
   - Same canonical status after 4.3 (27 IDs) → keep the first by file order. Not a conflict.
   - Different canonical status (16 IDs) → the latest lifecycle state wins:
     `refunded > void > paid > failed > pending`. Set `status_conflict = true`.
   - Differing in any column other than `status` → quarantine every row for that ID
     (expected 0).
3. Result: exactly 5,000 rows, `invoice_id` unique.

Why lifecycle order: there is no timestamp saying which system is newer and file order carries
no signal, so we assume the more final state is the more recent one. Sensitivity is small and
is reported: all-time net revenue is $111,211,582.69 under this rule, $111,221,964.43 if
"paid wins", $111,053,522.89 if paid loses every conflict.

## 8. Future-dated invoices

Invoice dates run to 2027-07-23. Rows are kept and flagged with `is_future_dated` against
`AS_OF_DATE` from config (default: the run date). All-time totals include them; the README
says so.

## 9. Configuration (no hardcoding)

Read from environment / `.env`, with defaults in one config module: `RAW_CSV_PATH`, `DB_PATH`,
`AS_OF_DATE`, `ANTHROPIC_API_KEY`, `ANTHROPIC_MODEL`. FX rates, list prices and the category
mappings live in that same module as named constants.

- Default `ANTHROPIC_MODEL` is the ID in `.env.example`, confirmed against the Anthropic docs
  before use.
- Query timeout for the question interface is 30 seconds, a named constant in the same module.

## 10. `dq_report` — expected values on the provided file

| check_name | value |
|---|---|
| raw_rows | 5125 |
| exact_duplicates_dropped | 82 |
| near_duplicate_invoice_ids | 43 |
| status_conflict_invoice_ids | 16 |
| quarantined_rows | 0 |
| clean_invoices | 5000 |
| accounts | 3815 |
| emails_repaired | (count) |
| null_contact_email / null_industry / null_csat_score / null_payment_method | (counts) |
| future_dated_invoices | (count, depends on AS_OF_DATE) |
| amount_formula_mismatches | 0 |
