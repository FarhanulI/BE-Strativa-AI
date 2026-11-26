---
name: sdd-implement
description: Implement a Ready task within its scope with requirement-tagged tests, traceability updates and logical commits.
argument-hint: <task ID, for example T-012>
---

Implement one task. Follow [docs/sdd.md](../../../docs/sdd.md) and the repository rules in `.github/copilot-instructions.md`.

1. Open the task. Proceed only if its state is `Ready` or `In Progress` and its dependencies are met. If `Blocked`, `Proposed` or missing, stop and report.
2. Re-read the module spec sections and decisions for the task's requirement IDs. If code and spec conflict, stop and write a change proposal; do not edit the approved spec.
3. Set the task `In Progress`. Work only inside its scope and non-goals. Respect module boundaries (public interfaces and events only).
4. Write or update tests for each applicable acceptance criterion. Name or tag tests so the requirement ID is traceable (for example in the docstring).
5. Update `docs/traceability.md`: Implementation and Test references for each ID, status `Implemented`. Never set `Verified` here.
6. Set the task `Implemented`.
7. Hand over to `sdd-verify`. Do not run the database suite except through `/run-db-suite`, and never run Neon.
