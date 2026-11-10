"""Profile the raw CloudNova ledger. Usage: python scripts/profile_raw.py data/cloudnova_invoices.csv"""
import re
import sys
from collections import Counter

import pandas as pd

path = sys.argv[1]
df = pd.read_csv(path, dtype=str, keep_default_na=False)
print("rows", len(df), "cols", len(df.columns))
print(list(df.columns))


def sec(t):
    print("\n=== " + t + " ===")


sec("blank counts (empty or whitespace)")
for c in df.columns:
    n = (df[c].str.strip() == "").sum()
    if n:
        print(f"{c}: {n}")

sec("leading/trailing whitespace counts")
for c in df.columns:
    n = (df[c] != df[c].str.strip()).sum()
    if n:
        print(f"{c}: {n}")

for c in ["plan", "status", "billing_cycle", "currency", "region", "payment_method",
          "churned", "industry", "seats", "discount_pct", "csat_score"]:
    sec(f"distinct {c}")
    print(df[c].value_counts(dropna=False).to_string())

sec("support_tickets describe")
st = pd.to_numeric(df["support_tickets"], errors="coerce")
print(st.describe().to_string(), "| non-numeric:", st.isna().sum())


def amt_class(s):
    s2 = s.strip()
    if s2 == "":
        return "blank"
    if re.fullmatch(r"-?\d+\.\d{2}", s2):
        return "plain_float_2dp"
    if re.fullmatch(r"-?\d+", s2):
        return "integer_no_cents"
    if re.fullmatch(r"-?\d+\.\d+", s2):
        return "plain_float_other_dp"
    if re.fullmatch(r"\$-?[\d,]+\.\d{2}", s2):
        return "$ prefixed"
    if re.fullmatch(r"-\$[\d,]+\.\d{2}", s2):
        return "-$ prefixed"
    if re.fullmatch(r"[£€]-?[\d,]+\.\d{2}", s2):
        return "£/€ prefixed"
    if re.fullmatch(r"-?[\d,]+\.\d{2} (USD|EUR|GBP)", s2):
        return "suffix currency code"
    if re.fullmatch(r"-?[\d,]+\.\d{2}", s2):
        return "comma thousands"
    return "OTHER:" + s2


sec("amount format classes")
ac = df["amount"].map(amt_class)
vc = ac.value_counts()
print(vc.head(30).to_string())

sec("amount symbol/code vs currency column mismatches")
sym = {"$": "USD", "£": "GBP", "€": "EUR"}
mm = Counter()
for a, cur in zip(df["amount"], df["currency"]):
    a = a.strip()
    found = None
    for k, v in sym.items():
        if k in a:
            found = v
    m = re.search(r"(USD|EUR|GBP)", a)
    if m:
        found = m.group(1)
    if found and found != cur.strip():
        mm[(found, cur)] += 1
print(dict(mm) or "none")


def date_class(s):
    s = s.strip()
    if s == "":
        return "blank"
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", s):
        return "YYYY-MM-DD"
    if re.fullmatch(r"\d{4}/\d{2}/\d{2}", s):
        return "YYYY/MM/DD"
    if re.fullmatch(r"\d{2}/\d{2}/\d{4}", s):
        return "NN/NN/YYYY"
    if re.fullmatch(r"\d{2}-\d{2}-\d{4}", s):
        return "NN-NN-YYYY"
    if re.fullmatch(r"[A-Za-z]{3} \d{1,2} \d{4}", s):
        return "Mon D YYYY"
    return "OTHER:" + s


for c in ["signup_date", "invoice_date"]:
    sec(f"{c} format classes")
    print(df[c].map(date_class).value_counts().head(15).to_string())
    for cls, sepr in [("NN/NN/YYYY", "/"), ("NN-NN-YYYY", "-")]:
        sub = df[c][df[c].map(date_class) == cls].str.strip()
        a = sub.str.split(sepr).str[0].astype(int)
        b = sub.str.split(sepr).str[1].astype(int)
        print(f"  {cls}: first>12: {(a > 12).sum()}, second>12: {(b > 12).sum()}, "
              f"both<=12 (ambiguous): {((a <= 12) & (b <= 12)).sum()}, "
              f"both<=12 and a!=b: {((a <= 12) & (b <= 12) & (a != b)).sum()}")

sec("emails")
e = df["contact_email"].str.strip()
print("blank", (e == "").sum(), "| _at_", e.str.contains("_at_").sum(),
      "| no @ and not blank and no _at_", ((~e.str.contains("@")) & (e != "") & (~e.str.contains("_at_"))).sum())
ok = e.str.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+")
print("other malformed sample:", e[(~ok) & (e != "") & (~e.str.contains("_at_"))].head(10).tolist())

sec("duplicates")
print("full duplicate rows (extra copies):", df.duplicated().sum())
stripped = df.apply(lambda s: s.str.strip())
print("full dups after strip:", stripped.duplicated().sum())
dd = df.drop_duplicates()
g = dd.groupby("invoice_id").size()
print("unique invoice_ids:", df["invoice_id"].nunique(), "| ids with >1 distinct row:", (g > 1).sum(),
      "| max rows per id:", g.max())
print("blank invoice_id:", (df["invoice_id"].str.strip() == "").sum())
diffcols = Counter()
examples = []
for iid, grp in dd.groupby("invoice_id"):
    if len(grp) > 1:
        cols = tuple(c for c in df.columns if grp[c].nunique() > 1)
        diffcols[cols] += 1
        if len(examples) < 6:
            examples.append(grp[["invoice_id", "status", "amount", "currency", "plan", "seats", "invoice_date"]])
print("columns that differ within near-dup groups:")
for k, v in diffcols.most_common(15):
    print("  ", v, k)
for ex in examples:
    print(ex.to_string(index=False))
    print()

sec("id formats")
print("invoice_id pattern ok:", df["invoice_id"].str.fullmatch(r"INV-\d{6}").sum(), "/", len(df))
print("account_id pattern ok:", df["account_id"].str.fullmatch(r"ACC-\d{4}").sum(), "/", len(df))
print("unique accounts:", df["account_id"].nunique(), "| unique account_name:", df["account_name"].nunique())
