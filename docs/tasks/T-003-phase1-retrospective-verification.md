# T-003: Phase 1 retrospective verification gaps

- **Module and phase:** auth, workspace, profile; Phase 1
- **State:** Proposed
- **Requirement IDs:** AUTH-INV-1..7, AUTH-AC-1..9, WS-INV-1..6, WS-AC-1..7, PROF-INV-1..8, PROF-AC-1..7
- **Specification references:** [auth-onboarding](../specs/auth-onboarding/spec.md), [workspace](../specs/workspace/spec.md), [profile](../specs/profile/spec.md); SDD-D-1 in [decisions.md](../decisions.md)
- **Dependencies:** Owner approval. T-001 for WS-AC-3. Phase 1 is owner-declared closed (SDD-D-1); that does not mean verified.

## Objective
Establish requirement-level evidence for Phase 1 and close or record each gap in traceability.

## Scope
Review the Phase 1 rows in [traceability.md](../traceability.md); run mapped tests through `/run-db-suite`; add tests only for rows with no test and only under an approved task; record evidence.

## Non-goals
Reopening Phase 1 for features. Neon runs (T-001). Frontend scope (T-010).

## Implementation expectations
Evidence recording. A missing test is added within module boundaries, with tenant-isolation coverage where relevant.

## Required tests
Those mapped in traceability for each ID.

## Verification requirements
Dated execution evidence per ID. Local PostgreSQL does not verify WS-AC-3.

## Acceptance criteria
Each Phase 1 row is `Verified` with dated matching evidence, or remains `Gap` or `Blocked` with a stated reason.

## Evidence
None recorded.

## Review and approval
Not requested.
