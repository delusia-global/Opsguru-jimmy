---
name: run-evals
description: Run the eval harness and explain every failure against the spec
argument-hint: [--nl]
disable-model-invocation: true
---

Run `python -m evals $ARGUMENTS` and report.

1. Give the summary line: passed, failed, xfail, xpass.
2. For each FAIL: the case ID, expected value, actual value, and the spec section that
   defines the expected behaviour. Say whether you think the code is wrong or the spec is
   wrong, and why. Do not fix anything yet.
3. For an XPASS: say what changed that made the expected-fail case pass.
4. Never edit `specs/evals.md` or the expected values in the harness.
