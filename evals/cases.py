"""Eval cases. Every expected value is copied from specs/evals.md and nowhere else.

Tolerances (Spec 2): USD amounts and percentages ±0.01, counts exact. A non-integer expected
value gets the tolerance; an integer, string, boolean or NULL must match exactly.
"""
from __future__ import annotations

from dataclasses import dataclass

TOLERANCE = 0.01


@dataclass(frozen=True)
class DataCase:
    """Tier 1 data-quality check: `sql` must return exactly `expected` (list of row tuples)."""
    id: str
    name: str
    sql: str
    expected: list[tuple]


@dataclass(frozen=True)
class QuestionCase:
    """Stakeholder question. Tier 1 runs `sql`; Tier 2 sends `question` to the model."""
    id: str
    question: str
    sql: str
    expected: list[tuple]           # rows the canonical SQL must return, in order
    nl_pass_rule: str = ""          # how Tier 2 grades, quoted from the spec


@dataclass(frozen=True)
class GuardCase:
    """Tier 3a: the guard must reject `sql` and nothing may execute."""
    id: str
    sql: str
    why: str


# --- Tier 1: data quality (D cases) --------------------------------------------------------

def _dq(name: str) -> str:
    return f"SELECT value FROM dq_report WHERE check_name = '{name}'"


DATA_CASES: list[DataCase] = [
    DataCase("D1", "raw rows read", _dq("raw_rows"), [(5125,)]),
    DataCase("D2", "exact duplicates dropped", _dq("exact_duplicates_dropped"), [(82,)]),
    DataCase("D3", "near-duplicate invoice IDs", _dq("near_duplicate_invoice_ids"), [(43,)]),
    DataCase("D4", "status-conflict invoice IDs", _dq("status_conflict_invoice_ids"), [(16,)]),
    DataCase("D5", "rows in invoices, and invoice_id unique",
             "SELECT COUNT(*), COUNT(DISTINCT invoice_id) FROM invoices", [(5000, 5000)]),
    DataCase("D6", "rows in quarantine", "SELECT COUNT(*) FROM quarantine", [(0,)]),
    DataCase("D7", "status counts",
             "SELECT status, COUNT(*) FROM invoices GROUP BY status ORDER BY status",
             [("failed", 396), ("paid", 3426), ("pending", 498), ("refunded", 292), ("void", 388)]),
    DataCase("D8", "rows in v_accounts", "SELECT COUNT(*) FROM v_accounts", [(3815,)]),
    DataCase("D9", "negative amount_local <=> status = 'refunded'",
             "SELECT COUNT(*) FROM invoices WHERE (amount_local < 0) <> (status = 'refunded')", [(0,)]),
    DataCase("D10", "amount_matches_formula = false",
             "SELECT COUNT(*) FROM invoices WHERE NOT amount_matches_formula", [(0,)]),
]

# --- Tier 1 and 2: stakeholder questions (Q cases) -----------------------------------------

QUESTION_CASES: list[QuestionCase] = [
    QuestionCase(
        "Q1",
        "What was our total recognized revenue in USD for paid invoices in 2024?",
        """SELECT ROUND(SUM(amount_usd), 2) AS net_usd,
       ROUND(SUM(amount_usd) FILTER (WHERE status = 'paid'), 2) AS paid_usd,
       ROUND(SUM(amount_usd) FILTER (WHERE status = 'refunded'), 2) AS refunds_usd
FROM v_recognized_revenue
WHERE YEAR(invoice_date) = 2024""",
        [(30755088.25, 32686371.05, -1931282.80)],
        "result contains either the net figure or the paid figure; the harness reports which",
    ),
    QuestionCase(
        "Q2",
        "Which region has the highest average MRR per account?",
        """SELECT region, ROUND(AVG(mrr_usd), 2) AS avg_mrr_usd, COUNT(*) AS active_accounts
FROM v_accounts WHERE is_active
GROUP BY region ORDER BY avg_mrr_usd DESC""",
        [("APAC", 6272.22, 510), ("NA", 6117.20, 498), ("EMEA", 5576.38, 535), ("LATAM", 5333.81, 547)],
        "APAC as the first row and 6272.22 present",
    ),
    QuestionCase(
        "Q3",
        "How much have we given back in refunds?",
        """SELECT ROUND(SUM(amount_usd), 2) AS total_usd, COUNT(*) AS invoices
FROM invoices WHERE status = 'refunded'""",
        [(-8925163.77, 292)],
        "accepts the absolute value",
    ),
    QuestionCase(
        "Q4",
        "What's the churn rate among Enterprise accounts vs Starter?",
        """SELECT plan, SUM(churned::INT) AS churned, COUNT(*) AS accounts,
       ROUND(100.0 * AVG(churned::INT), 2) AS rate_pct
FROM v_accounts WHERE plan IN ('Enterprise', 'Starter')
GROUP BY plan ORDER BY plan""",
        [("Enterprise", 171, 780, 21.92), ("Starter", 354, 1882, 18.81)],
        "accepts the rate as a percentage or a fraction",
    ),
    QuestionCase(
        "Q5",
        "List the top 5 accounts by revenue, and flag any with CSAT ≤ 2.",
        """SELECT r.account_id, a.account_name, ROUND(SUM(r.amount_usd), 2) AS revenue_usd,
       a.csat_score, COALESCE(a.csat_score <= 2, FALSE) AS low_csat_flag
FROM v_recognized_revenue r JOIN v_accounts a USING (account_id)
GROUP BY r.account_id, a.account_name, a.csat_score
ORDER BY revenue_usd DESC LIMIT 5""",
        [
            ("ACC-7509", "Stark Inc", 1210592.75, 4, False),
            ("ACC-1420", "Tyrell Industries", 1208092.75, None, False),
            ("ACC-9946", "Initech LLC", 1205642.75, 4, False),
            ("ACC-1196", "Pied Piper Partners", 1107352.84, 3, False),
            ("ACC-5211", "Oscorp Industries", 1085078.48, 5, False),
        ],
        "the five account IDs in this order",
    ),
    QuestionCase(
        "Q6",
        "How many invoices are stuck in pending/failed and what's the exposed $?",
        """SELECT status, COUNT(*) AS invoices, ROUND(SUM(amount_usd), 2) AS exposed_usd
FROM v_open_exposure GROUP BY ROLLUP(status) ORDER BY status NULLS LAST""",
        [("failed", 396, 13157652.28), ("pending", 498, 15825603.53), (None, 894, 28983255.81)],
        "894 and 28983255.81 present, or both per-status rows present",
    ),
]

# --- Tier 3a: guard (G cases, no model call) -----------------------------------------------

GUARD_CASES: list[GuardCase] = [
    GuardCase("G1", "DROP TABLE invoices", "not a SELECT"),
    GuardCase("G2", "SELECT 1; DELETE FROM invoices", "more than one statement"),
    GuardCase("G3", "SELECT * FROM read_csv('data/cloudnova_invoices.csv')", "relation outside the allow-list"),
    GuardCase("G4", "UPDATE invoices SET status = 'paid'", "not a SELECT"),
]
