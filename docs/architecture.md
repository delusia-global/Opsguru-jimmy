# Architecture

One diagram, matching the code. Left: the build (`python -m app build`). Right: one question
(`python -m app ask` and the demo). The views are the only thing the question layer may query.

```mermaid
flowchart LR
  subgraph build["python -m app build — app/pipeline.py, app/db.py"]
    CSV["data/cloudnova_invoices.csv<br/>5,125 raw rows, every column read as text"]
    P["pipeline.run<br/>normalise · parse amounts and dates · dedup · flag"]
    INV[("invoices<br/>5,000 rows, typed")]
    QUAR[("quarantine<br/>rows that failed a rule, with reason")]
    DQ[("dq_report<br/>one row per check")]
    V1["v_recognized_revenue<br/>status in paid, refunded"]
    V2["v_open_exposure<br/>status in pending, failed"]
    V3["v_accounts<br/>one row per account_id, latest invoice"]
    CSV --> P
    P --> INV
    P --> QUAR
    P --> DQ
    INV --> V1
    INV --> V2
    INV --> V3
  end
  subgraph ask["python -m app ask — app/ask.py"]
    U["question<br/>non-empty, ≤ 500 chars"]
    L["app/llm.py<br/>Claude writes SQL + one-sentence explanation,<br/>or a refusal. Never sees results."]
    G["app/guard.py<br/>sqlglot parse: one SELECT, allow-listed relations,<br/>no table functions or file access"]
    X["db.run_query<br/>read-only connection · 200-row cap · 30 s timeout"]
    C["guard.caveats<br/>rule-based, from the parsed SQL"]
    A["answer<br/>question, explanation, SQL, result table, caveats"]
    U --> L
    L -->|"SQL"| G
    L -->|"refusal"| A
    G -->|"accepted"| X
    G -->|"rejected, with reason"| A
    X -->|"SQL error, one retry"| L
    X --> C
    C --> A
  end
  INV -.-> X
  V1 -.-> X
  V2 -.-> X
  V3 -.-> X
```

Where each box lives:

| Box | Code |
|---|---|
| pipeline.run | `app/pipeline.py` `read_raw`, `clean_row`, `parse_amount`, `parse_date`, `run` |
| tables and views | `app/db.py` `write_database`, `view_ddl` |
| Claude writes SQL | `app/llm.py` `system_prompt`, `glossary`, `generate_sql` |
| guard | `app/guard.py` `check_sql` |
| run_query | `app/db.py` `run_query` |
| caveats | `app/guard.py` `caveats` |
| answer | `app/ask.py` `answer`, `render`, `to_json` |
| constants | `app/config.py` (paths, FX, list prices, mappings, model, limits, caveat text) |

Evals (`python -m evals`) rebuild the database, run the data-quality checks and the canonical SQL
for each question against it, and probe the guard. `--nl` adds the same questions through the
model and the expected-fail case X1.
