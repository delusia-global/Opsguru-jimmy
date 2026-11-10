---
name: build-from-spec
description: Implement or update code from one of the specs in specs/, section by section, then run the evals
argument-hint: [spec-file]
disable-model-invocation: true
---

Implement `$ARGUMENTS` (a file in `specs/`).

1. Read the spec in full, and `CLAUDE.md` if you have not this session.
2. List the numbered sections you will implement and the file each maps to. If any section is
   ambiguous, silent on a case you need, or conflicts with another spec, stop and ask before
   writing code.
3. Implement section by section. Put every constant, mapping and path in `app/config.py`.
4. Run `python -m app build`, then `python -m evals`.
5. Report: sections implemented with file and function, the eval pass/fail line, any section
   you could not implement as written and why, and a proposed commit message.

Do not edit the spec or the expected values. Do not read `scripts/derive_expected.py`.
