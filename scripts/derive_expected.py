"""Independent oracle for the eval expected values.

This is a deliberately separate, pandas-only implementation of specs/schema.md.
The pipeline in app/ must NOT import or copy from it: the evals are only
meaningful if two independent implementations of the spec agree.

Usage: python scripts/derive_expected.py data/cloudnova_invoices.csv
Prints the expected values as JSON (the numbers recorded in specs/evals.md).
"""
import json
import re
import sys

import numpy as np
import pandas as pd

PLAN = {"starter": "Starter", "start": "Starter", "tier 1": "Starter",
        "pro": "Pro", "professional": "Pro", "tier 2": "Pro",
        "enterprise": "Enterprise", "ent": "Enterprise", "tier 3": "Enterprise"}
STATUS = {"paid": "paid", "complete": "paid", "completed": "paid", "success": "paid",
          "pending": "pending", "in_review": "pending", "awaiting": "pending",
          "failed": "failed", "declined": "failed", "error": "failed",
          "refunded": "refunded", "refund": "refunded", "charged_back": "refunded",
          "void": "void", "cancelled": "void", "canceled": "void"}
PRICE = {"Starter": 49, "Pro": 99, "Enterprise": 299}
FX = {"USD": 1.0, "EUR": 1.08, "GBP": 1.27}
PRECEDENCE = ["refunded", "void", "paid", "failed", "pending"]  # lower index wins
DATE_FORMATS = ["%Y-%m-%d", "%Y/%m/%d", "%m/%d/%Y", "%d-%m-%Y", "%b %d %Y"]


def parse_date(s):
    for fmt in DATE_FORMATS:
        try:
            return pd.to_datetime(s.strip(), format=fmt)
        except ValueError:
            continue
    raise ValueError(f"unparseable date: {s!r}")


def main(path):
    raw = pd.read_csv(path, dtype=str, keep_default_na=False)
    n_raw = len(raw)
    raw["source_row"] = np.arange(2, n_raw + 2)
    cols = [c for c in raw.columns if c != "source_row"]

    exact = raw.drop_duplicates(subset=cols, keep="first").copy()
    exact["status"] = exact["status"].str.strip().str.lower().map(STATUS)
    exact["rank"] = exact["status"].map({s: i for i, s in enumerate(PRECEDENCE)})
    per_id = exact.groupby("invoice_id")
    near_dup_ids = int((per_id.size() > 1).sum())
    conflict_ids = int((per_id["status"].nunique() > 1).sum())
    df = exact.sort_values(["invoice_id", "rank", "source_row"]).drop_duplicates("invoice_id", keep="first").copy()

    df["plan"] = df["plan"].str.strip().str.lower().map(PLAN)
    df["churned"] = df["churned"].str.strip().str.lower().isin({"true", "yes", "1", "y"})
    df["seats"] = df["seats"].astype(int)
    df["discount_pct"] = df["discount_pct"].astype(float)
    df["amount_local"] = df["amount"].map(lambda s: float(re.sub(r"[^\d.\-]", "", s)))
    df["amount_usd"] = df["amount_local"] * df["currency"].map(FX)
    df["mrr_usd"] = df["plan"].map(PRICE) * df["seats"] * (1 - df["discount_pct"] / 100)
    df["invoice_date"] = df["invoice_date"].map(parse_date)
    df["csat_score"] = pd.to_numeric(df["csat_score"], errors="coerce")
    assert df[["plan", "status"]].notna().all().all()

    rev = df[df["status"].isin(["paid", "refunded"])]
    r24 = rev[rev["invoice_date"].dt.year == 2024]
    accounts = (df.sort_values(["account_id", "invoice_date", "invoice_id"])
                  .drop_duplicates("account_id", keep="last").set_index("account_id"))
    active = accounts[(accounts["status"] == "paid") & (~accounts["churned"])]
    mrr = active.groupby("region")["mrr_usd"].agg(["mean", "count"]).sort_values("mean", ascending=False)
    churn = accounts.groupby("plan")["churned"].agg(["sum", "count", "mean"])
    top = rev.groupby("account_id")["amount_usd"].sum().sort_values(ascending=False).head(5)
    open_ = df[df["status"].isin(["pending", "failed"])]

    out = {
        "dq": {"raw_rows": n_raw, "exact_duplicates_dropped": n_raw - len(exact),
               "near_duplicate_invoice_ids": near_dup_ids, "status_conflict_invoice_ids": conflict_ids,
               "clean_invoices": len(df), "accounts": len(accounts),
               "status_counts": df["status"].value_counts().to_dict()},
        "q1_revenue_2024": {"net_usd": round(r24["amount_usd"].sum(), 2),
                            "paid_usd": round(r24[r24["status"] == "paid"]["amount_usd"].sum(), 2),
                            "refunds_usd": round(r24[r24["status"] == "refunded"]["amount_usd"].sum(), 2)},
        "q2_avg_mrr_per_active_account_by_region": {
            r: {"avg_mrr_usd": round(v["mean"], 2), "active_accounts": int(v["count"])} for r, v in mrr.iterrows()},
        "q3_refunds": {"total_usd": round(df[df["status"] == "refunded"]["amount_usd"].sum(), 2),
                       "invoices": int((df["status"] == "refunded").sum())},
        "q4_churn_by_plan": {p: {"churned": int(v["sum"]), "accounts": int(v["count"]),
                                 "rate_pct": round(100 * v["mean"], 2)} for p, v in churn.iterrows()},
        "q5_top5_accounts": [{"account_id": a, "account_name": accounts.loc[a, "account_name"],
                              "revenue_usd": round(v, 2),
                              "csat_score": None if pd.isna(accounts.loc[a, "csat_score"]) else int(accounts.loc[a, "csat_score"]),
                              "low_csat_flag": bool(accounts.loc[a, "csat_score"] <= 2)} for a, v in top.items()],
        "q6_open_exposure": {"invoices": len(open_), "exposed_usd": round(open_["amount_usd"].sum(), 2),
                             "pending": {"invoices": int((open_["status"] == "pending").sum()),
                                         "usd": round(open_[open_["status"] == "pending"]["amount_usd"].sum(), 2)},
                             "failed": {"invoices": int((open_["status"] == "failed").sum()),
                                        "usd": round(open_[open_["status"] == "failed"]["amount_usd"].sum(), 2)}},
    }
    print(json.dumps(out, indent=2))
    return df, accounts


if __name__ == "__main__":
    main(sys.argv[1])
