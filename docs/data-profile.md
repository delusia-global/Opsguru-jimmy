# Data profile — `cloudnova_invoices.csv`

Produced before any spec or code was written, by running `scripts/profile_raw.py` over the
whole file. Every decision in `specs/schema.md` traces back to a finding here.

## Shape

- 5,125 rows, 19 columns, 5,000 distinct `invoice_id`, 3,815 distinct `account_id`,
  200 distinct `account_name`.
- Invoice dates 2021-01-19 to 2027-07-23. Signup dates 2021-01-01 to 2024-11-01.
  No invoice predates its signup date.

## What the briefing warned about, quantified

| Issue | Finding |
|---|---|
| Plan spellings | 18 raw variants → 3 plans. Includes `Start`, `ENT`, `Tier 1/2/3`, and 1,023 values with stray whitespace |
| Status spellings | 25 raw variants → 5 statuses, all covered by the briefing's table |
| Billing cycle | 6 variants → 2 |
| Churned | 10 variants → boolean |
| Payment method | 7 variants → 4, plus 637 blanks |
| Amount formats | plain 2-dp float 2,832; `$` prefix 867; currency-code suffix 521; integer without cents 509; `£`/`€` prefix 396. Symbol or code never contradicts the `currency` column |
| Date formats | ISO, `YYYY/MM/DD`, `NN/NN/YYYY`, `NN-NN-YYYY`, `Mon D YYYY`, in both date columns |
| Blanks | `contact_email` 292, `industry` 422, `csat_score` 623, `payment_method` 637 |
| Malformed emails | 142 with `_at_`; no other malformation |
| Exact duplicate rows | 82 |
| Near-duplicates | 43 invoice IDs with two rows each, differing **only** in `status` |

## What the briefing did not say

### 1. The "ambiguous" dates follow a pattern
In 2,579 slash-separated dates the first part never exceeds 12, so they are month-first.
In 532 dash-separated dates the second part never exceeds 12, and the first exceeds 12 in 313,
so they are day-first. Reading the dash dates the other way would move 81 invoices to a
different month and none to a different year.

### 2. Only 16 of the 43 near-duplicates are real conflicts
27 pairs collapse to the same canonical status once spellings are normalised
(`completed` vs `paid`). The 16 real conflicts: paid vs pending 7, paid vs void 5,
failed vs paid 2, paid vs refunded 2. File order carries no signal about which is newer.
The two raw "paid" rows with negative amounts are exactly the twins of the two refunded rows.

### 3. `amount` already includes the discount and the FX rate
For all 5,125 rows, `|amount|` = list price × seats × (10 if annual, else 1) ×
(1 − discount/100) × rate, within rounding. Two consequences:

- `discount_pct` must not be applied to `amount` again.
- Non-USD amounts equal the USD list price **multiplied** by the rate. The briefing says to
  convert to USD by multiplying by the same rate, which applies it twice. A $747,500
  list-price invoice in GBP becomes $1,205,642.75. On 2024 net revenue the two readings give
  $30,755,088.25 and $27,823,962.37. 39.6% of all-time net revenue is in non-USD currencies.

### 4. `account_id` is not a stable key
980 account IDs have more than one invoice. Within those, 976 carry more than one account
name, 774 more than one region, 979 more than one signup date, 334 both churned and not
churned. The IDs look randomly assigned per invoice. Every per-account metric inherits this.

### 5. The ledger contains future-dated invoices
Invoice dates extend to July 2027. As of 2026-11-10, 110 raw rows are in the future,
73 of them paid.

## Effect of each decision on the headline number (2024 net recognised revenue)

| Variant | 2024 net USD |
|---|---|
| As specified | 30,755,088.25 |
| No deduplication at all | 31,467,333.10 |
| "Paid wins" on status conflicts | 30,755,088.25 |
| Paid loses every status conflict | 30,724,069.57 |
| Dash dates read month-first | 30,755,088.25 |
| Non-USD amounts divided by the rate instead of multiplied | 27,823,962.37 |

The FX question is two orders of magnitude larger than every cleaning decision combined.
