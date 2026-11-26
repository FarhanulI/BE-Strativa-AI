# T-001: Workspace Neon TEST-branch concurrency verification

- **Module and phase:** workspace, Phase 1
- **State:** Blocked
- **Requirement IDs:** WS-AC-3, WS-INV-1
- **Specification references:** [Workspace spec](../specs/workspace/spec.md), Invariants and Acceptance criteria; SDD-D-2 in [decisions.md](../decisions.md)
- **Dependencies:** Separate explicit owner authorization naming the Neon TEST branch and the run. The environment guard and the rule in [.github/copilot-instructions.md](../../.github/copilot-instructions.md) that Neon runs only in an explicitly authorised, separate task.

## Objective
Produce dated evidence that concurrent demotion or removal cannot leave a workspace without an OWNER, on the real Neon TEST branch.

## Scope
Identify or write the concurrency test that matches WS-AC-3, run it on the Neon TEST branch under the existing environment guard, and record the result.

## Non-goals
Any run on dev or production. Substituting local PostgreSQL. Changing workspace behavior. Running Neon in any other task.

## Implementation expectations
Reuse the existing environment guard and test fixtures. Any new test follows the module's test conventions. No secret is printed.

## Required tests
A committed-session concurrency test for WS-INV-1 (final-owner demotion and removal races). Its mapping is recorded in [traceability.md](../traceability.md).

## Verification requirements
Execution on the Neon TEST branch only, with date, a branch identity check as in the Phase 0 verification report, and counts. Local PostgreSQL results are recorded separately and do not satisfy WS-AC-3.

## Acceptance criteria
WS-AC-3 has dated Neon TEST-branch evidence in traceability, or the failure is recorded as a Gap with the failing scenario.

## Evidence
None recorded.

## Review and approval
Not requested. Blocked until the owner authorizes the Neon run.
