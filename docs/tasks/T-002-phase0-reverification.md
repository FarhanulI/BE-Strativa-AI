# T-002: Phase 0 re-verification

- **Module and phase:** core, events_outbox, jobs_workers, observability_audit, db_migrations, api_contract; Phase 0
- **State:** Implemented (owner approved 2026-11-20; runs and row audit recorded 2026-11-20; 8 of 56 rows `Verified`; awaiting owner review)
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

**Run 2, 2026-11-20, local database suite** (same commit; run by the owner through `/run-db-suite all`)
- Command: `bash scripts/run_db_suite.sh all`
- Exit code: 0
- Environment: local Postgres container `strativa-test-db` (`pgvector/pgvector:pg16`, `127.0.0.1:55444`), `TEST_DB_MODE=local`, Windows 11, Python 3.12.14. Not Neon.
- Results: 196 passed, 0 failed, 1679 deselected (the DB-free tests of Run 1). The script prints no skipped count, so none is claimed. Script printed `cleanup done`.
- Files: `tests/db/` test_ai_platform_schema, test_audit_teardown_helper, test_auth_workspace, test_budget_coordinator, test_budget_refuse_for_call, test_budget_repository, test_budget_usage_services, test_foundation_schema, test_outbox_claim, test_profile, test_request_repository.
- Scope: local PostgreSQL. Verifies no requirement that names Neon.

**Real-Redis rows (JOB-AC-2, OUT-AC-3, OBS-AC-3, OUT-AC-2 lease clause, API-INV-3 readiness): NOT RUN.** They wait for T-015.

**Neon:** NOT RUN (separate authorization, T-001).

### Row audit (Phase 0, 56 rows)
Rule applied: a row became `Verified` only if every mapped test is in Run 1 or Run 2 and passed, the spec text names no Neon or Redis scope, and the Notes column carries no "Partial" or untested-clause caveat. Test existence was checked by name; the pass comes from the aggregate runs (0 failed). I did not run the tests individually.

**Verified (8):** CORE-AC-2, CORE-AC-4, DBM-INV-3, DBM-AC-1, DBM-AC-3, API-AC-1 (Run 1); OUT-INV-1, OBS-INV-1 (Run 2).

**Not promoted (48):**
- Unmapped, so `Gap` (11): CORE-INV-4, CORE-INV-10, CORE-AC-1, CORE-AC-9, CORE-AC-11, OUT-INV-2, OUT-INV-3, OUT-AC-3, JOB-AC-2, OBS-AC-3, API-INV-3.
- Real-Redis rows kept at their current status until T-015: JOB-AC-2, OUT-AC-3, OBS-AC-3, API-INV-3 (also in the list above), plus the OUT-AC-2 expired-lease clause.
- Mapped tests passed but the Notes name a Partial or untested clause, so they stay `Implemented`: the remaining 37 rows, including CORE-INV-1 (the note says other modules' ID use is not re-verified; my reading of the spec is ambiguous, so I held it back) and CORE-INV-9 (the `EventWorker.run_once` reset path is untested).
- Rows with a historical Neon-branch report in their Evidence cell (OUT-AC-2, OBS-AC-2, OBS-AC-3, DBM-AC-2) keep that note; the old report is not current evidence.

**Task result:** T-002 acceptance ("every Phase 0 row is `Verified` or stays `Gap`/`Blocked` with a stated reason") is met by the row notes and this audit. The task is `Implemented`, not `Verified`, because 48 of 56 rows are not `Verified`. Closing the rest needs new tests (separate tasks), T-015 (Redis) and T-001 (Neon).

## Review and approval
Plan approved by the owner on 2026-11-20 (`Ready`). Gate: milestone end (documentation and evidence only; no migration, contract, security, dependency, ADR or AI-target change), subject to the owner raising it. Independent audit (sdd.md section 11) precedes review. Real-Redis rows stay `Gap` until T-015 provides a Redis run; Neon-named rows stay open without a separate authorization.
