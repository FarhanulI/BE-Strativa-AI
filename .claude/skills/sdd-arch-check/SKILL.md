---
name: sdd-arch-check
description: Check module boundaries, import cycles, table ownership and decision coverage of the current code, using the DB-free architecture tests and read-only inspection.
argument-hint: <module, or all>
allowed-tools: Read, Grep, Glob, Bash(uv run --python 3.12 --no-sync python -m pytest tests/unit/architecture:*)
---

Check the architecture of the code against the repository rules. Follow [docs/sdd.md](../../../docs/sdd.md) and `docs/modules.md`. Change no file. Never run the database suite (only `/run-db-suite` does), never touch Neon, never open `.env*` files.

1. Run exactly `uv run --python 3.12 --no-sync python -m pytest tests/unit/architecture -q`. Report the exact command, the exit code and the counts. If it cannot run, say `NOT RUN` and why. Do not infer a pass.
2. Imports: with Grep, list `from app.` and `import app.` lines per module, including imports inside functions and methods. Report every edge between modules. Flag any import of `app.<other>.<submodule>` (the boundary test covers only that) and any pair of modules that import each other, even through a lazy import.
3. Ownership: look for queries (`select(`, `update(`, `delete(`, `text(` with table names) against ORM classes or tables the module does not own, and for exported ORM entities used outside metadata registration.
4. AI boundary: no provider or SDK import outside `app/ai_platform/`; no model or provider name in public types.
5. Tenancy: new workspace-scoped routes appear in `tests/helpers/tenant_isolation.py`.
6. Decisions: for each finding, check `docs/decisions.md`, the module spec and `docs/architecture/adr/`. Say whether a decision exists, and name an ADR that should be written.
7. Compare with `docs/architecture/conformance-report.md` findings B-1 to B-7. Report which are still true.
8. Report findings by severity (blocker, should-fix, note) with file and line. Do not fix anything; a fix needs a task.
