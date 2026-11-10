# Build plan — the prompt sequence

How this repo was meant to be built: specs first, then Claude Code driven from the specs in
six steps, one commit per step. The real session is exported to `docs/session-log.txt`.

## Before opening Claude Code (5 minutes)

1. Unzip the kit into an empty folder. Copy `cloudnova_invoices.csv` and `BUSINESS_CONTEXT.md`
   into `data/`.
2. Read `specs/schema.md` end to end. Change anything you disagree with. These are your
   decisions and you will be asked to defend them.
3. Copy `.env.example` to `.env` and put your Anthropic key in it.
4. `git init`, then two commits, in this order:
   - `data/` and `docs/data-profile.md`, `scripts/` → "Add raw data, business context and data profile"
   - `specs/`, `CLAUDE.md`, `.claude/`, `.gitignore`, `.env.example`, `docs/build-plan.md` → "Add specs and AI configuration (before any code)"

The second commit is the evidence that the spec came first.

## In Claude Code

Start `claude` in the folder. Paste each prompt, review what comes back, commit, move on.

### Step 1 — plan, no code (3 min)
```
Read CLAUDE.md, the three files in specs/, and data/BUSINESS_CONTEXT.md. Do not write code yet.
Give me: (1) the files you will create and which spec section each implements,
(2) every place where a spec is ambiguous, silent, or contradicts another spec or the
business context, (3) the dependencies you need. Keep it under one page.
```
Answer its questions. If it found a real gap, fix the spec and commit that on its own.

### Step 2 — pipeline (15 min)
```
/build-from-spec specs/schema.md
```
The evals do not exist yet, so follow with:
```
Now build the Tier 1 and Tier 3a cases from specs/evals.md as `python -m evals`.
Expected values come from the spec only. Run it and show me the output.
```
Check the data-quality report against section 10 of the schema spec yourself.
Commit: "Implement cleaning pipeline and DuckDB model from schema spec", then
"Add eval harness: pipeline and guard cases".

### Step 3 — question layer (15 min)
```
/build-from-spec specs/query_contract.md
```
Then run the demo yourself: `python -m app`. Read the SQL it generates for each question.
Commit: "Add natural-language question layer with SQL guard".

### Step 4 — question-layer evals (5 min)
```
Add the Tier 2, Tier 3b and X1 cases from specs/evals.md behind `python -m evals --nl`.
```
Then `/run-evals --nl`. Expect X1 to report XFAIL. If anything else fails, decide whether
the code or the spec is wrong before letting it change anything.
Commit: "Add question-layer evals and the expected-fail case".

### Step 5 — independent review (5 min)
```
Use the spec-reviewer subagent to check the implementation against all three specs.
```
Fix what matters; note what you chose not to fix. Optional, if time allows:
```
Use the guard-redteam subagent on the question layer.
```
Commit: "Address spec review findings".

### Step 6 — README, diagram, CI (10 min)
```
Write README.md for a finance stakeholder who has three minutes. Sections, in this order:
what it does (3 sentences); how to run it (setup and the single demo command); a Mermaid
architecture diagram that matches the code exactly (raw CSV → pipeline → DuckDB tables and
views → guard → model → answer); the six answers with their numbers; links to the specs;
design decisions and trade-offs; known limitations and failure modes; how AI was used;
next steps with another day. Take limitations from docs/data-profile.md, the caveats table in
specs/query_contract.md, and case X1. Also save the diagram as docs/architecture.md.
Then add .github/workflows/evals.yml that installs dependencies and runs `python -m evals`
on push. No API key in CI.
```
Edit the README yourself afterwards. The limitations and "how AI was used" sections should
be in your words.
Commit: "Add README, architecture diagram and CI eval check".

## After the build

1. In Claude Code run `/export docs/session-log.txt`. Trim tool noise only; do not rewrite
   prompts.
2. Add `docs/overrides.md`: three to five bullets on where you overruled or corrected the AI.
3. Commit, create the GitHub repo, push, and confirm the CI run is green.
4. Send the hiring team the link, and the two open questions below.

## Open questions to send with the submission

1. **FX.** Non-USD amounts in the export already equal the USD list price multiplied by the
   reference rate. Converting to USD as briefed applies the rate twice (about $2.9M on 2024
   revenue). I followed the briefing and flagged it. Which is intended?
2. **Account key.** 976 of 980 multi-invoice account IDs map to more than one account name.
   I treated `account_id` as the key and took attributes from the latest invoice. Is there a
   better key?

## Next steps to list in the README (not to build)

- Hybrid routing: SQL for aggregates, retrieval over rows for lookup questions.
- Entity resolution for accounts once a reliable key exists.
- As-of FX rates instead of fixed ones.
- Query result caching and per-question cost and latency logging.
- A reviewed library of approved queries for the questions finance asks most.
