# T-002: Phase 0 re-verification

- **Module and phase:** core, events_outbox, jobs_workers, observability_audit, db_migrations, api_contract; Phase 0
- **State:** Proposed
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
None recorded by this migration. Existing historical evidence: [phase0-verification.md](../reports/phase0-verification.md), dated 2026-10-14.

## Review and approval
Not requested.
