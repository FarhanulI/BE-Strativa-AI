# T-008: Remaining AI Platform implementation and verification gaps

- **Module and phase:** ai_platform, Phase 2
- **State:** Proposed
- **Requirement IDs:**
  - `Specified` (no implementation identified in the matrix): INV-1, INV-4, INV-16, INV-25, INV-26, INV-27, INV-28, AC-1, AC-9, AC-15, AC-39, AC-40, AC-41, AC-42, AC-43, AC-44, AC-47, AC-48, AC-49, AC-50, AC-51, AC-54, AC-55, AC-56, AC-57, AC-60.
  - `Gap` (implementation mapped, no test mapped): AC-38.
  - Every other AI Platform requirement is `Implemented` with partial or unexecuted coverage; their verification is part of this task (see the matrix).
- **Specification references:** [AI Platform spec](../specs/ai-platform/spec.md), sections 16 and 17; [traceability.md](../traceability.md)
- **Dependencies:** T-004 (D-32) and T-006 (revision 5 to 7 approval) for governance. SDD-D-3: feature development resumes only after the owner approves the SDD foundation. AC-54 to AC-57 need the separately authorized real-provider setup described in the spec (spend cap 20 USD total, INV-27).

## Objective
Track the AI Platform work that is not yet implemented or not yet verified so it stays visible and is carried out under the SDD workflow.

## Scope
Split into approved sub-tasks before any implementation: (a) governance resolution (T-004, T-006); (b) implementation of the missing components (the matrix lists the requirements without an implementation); (c) test mapping and execution for partial rows; (d) the real-provider smoke suite.

## Non-goals
Implementing anything under this task as written; it is a tracking task. New AI features outside the spec. Real-provider calls without the spec's spend controls. Neon runs.

## Implementation expectations
Each sub-task is prepared with `sdd-prepare-task`, owner-approved as `Ready`, and cites its requirement IDs and the applicable decisions (D-n).

## Required tests
Those named in the spec for each AC. Database tests run only through `/run-db-suite`.

## Verification requirements
Dated execution evidence per ID recorded in traceability. Real-provider tests only under the spec's spend cap and with synthetic text (privacy gate D-27).

## Acceptance criteria
Every listed ID is `Verified` with dated matching evidence, or stays `Specified`, `Gap` or `Blocked` with the reason recorded.

## Evidence
None recorded.

## Review and approval
Not requested.
