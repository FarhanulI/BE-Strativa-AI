# T-002: Phase 0 re-verification

- **Module and phase:** core, events_outbox, jobs_workers, observability_audit, db_migrations, api_contract; Phase 0
- **State:** In Progress (owner approved 2026-11-20; started 2026-11-20)
- **Requirement IDs:** CORE-INV-1..11, CORE-AC-1..11, OUT-INV-1..4, OUT-AC-1..3, JOB-INV-1..4, JOB-AC-1..3, OBS-INV-1..3, OBS-AC-1..3, DBM-INV-1..4, DBM-AC-1..4, API-INV-1..3, API-AC-1..3
- **Specification references:** The six Phase 0 specs under [docs/specs/](../specs/); [Phase 0 verification report](../reports/phase0-verification.md)
- **Dependencies:** Owner approval. A real Redis instance for worker tests. Any Neon execution requires a separate authorization (see T-001). Local DB tests run only through `/run-db-suite`.

## Objective
Replace the single dated Phase 0 report (2026-10-14, Neon test branch, before later changes) with requirement-level, reproducible evidence that matches the current code.

## Scope
Execute the mapped Phase 0 tests, record per-requirement evidence, and record gaps. The 2026-10-14 report is historical evidence for its date only and does not verify behavior that changed afterwards.

## Non-goals
New features. Changing specs. Dev or production runs. Web foundation.

## Implementation expectations
Documentation and evidence only. A defect found by a run becomes a separate task.

## Required tests
The tests mapped for each ID in [traceability.md](../traceability.md), including the DB-free suite and the DB suite.

## Verification requirements
Dated runs with command or skill, environment (local Postgres or Neon branch), pass/fail counts, and the mapping to IDs. A row whose scope names Neon or Redis is verified only by a run against those.

## Acceptance criteria
Every Phase 0 row is either `Verified` with dated matching evidence or stays `Gap` or `Blocked` with a stated reason.

## Evidence
Historical, for its date only: [phase0-verification.md](../reports/phase0-verification.md), dated 2026-10-14.

**Run 1, 2026-11-20, DB-free gate** (branch `feat/Ai-platform` at `a20f78d` plus uncommitted task-state edits to docs only)
- Command: `uv run --python 3.12 --no-sync python scripts/check.py`
- Exit code: 0
- Environment: local Windows 11, Python 3.12.14, pytest 9.1.1; no Postgres, no Redis, no network provider.
- Results: ruff "All checks passed!"; mypy "no issues found in 36 source files"; pytest `-m "not db"`: 1679 passed, 0 failed, 196 deselected (1875 collected). Skipped and error counts are not printed by this run, so none are claimed.
- Scope: this run covers only rows whose mapped tests are DB-free. It does not verify any row mapped to a `db`-marked test, Redis, or Neon.

**Database suite: NOT RUN.** Preconditions missing on 2026-11-20: Docker daemon not reachable, and `TEST_DB_PASSWORD` not set in the agent's shell (checked as set or not set only; no value read). The agent does not start Docker or set the password. It runs only through `/run-db-suite`.

**Real-Redis rows (JOB-AC-2, OUT-AC-3, OBS-AC-3, OUT-AC-2 lease clause, API-INV-3 readiness): NOT RUN.** They wait for T-015.

**Row statuses:** no row in [traceability.md](../traceability.md) was changed by this run. Per-row promotion to `Verified` (rows whose full scope is DB-free and not marked Partial) is pending and needs the per-row audit through `sdd-verify`.

## Review and approval
Plan approved by the owner on 2026-11-20 (`Ready`). Gate: milestone end (documentation and evidence only; no migration, contract, security, dependency, ADR or AI-target change), subject to the owner raising it. Independent audit (sdd.md section 11) precedes review. Real-Redis rows stay `Gap` until T-015 provides a Redis run; Neon-named rows stay open without a separate authorization.
