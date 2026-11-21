# T-009: Approval metadata for the nine non-AI-Platform specs

- **Module and phase:** core, events_outbox, jobs_workers, observability_audit, db_migrations, api_contract, auth, workspace, profile; Phases 0 and 1
- **State:** Blocked
- **Requirement IDs:** None. Dependency: specification status, revision, approval status and approval date of each spec.
- **Specification references:** The nine specs under [docs/specs/](../specs/)
- **Dependencies:** Owner confirmation.

## Objective
Replace `Not stated` and `Pending owner confirmation` in each spec's metadata with owner-confirmed values.

## Scope
The metadata block of each spec only.

## Non-goals
Changing requirement text. Inferring values from git history or file dates.

## Implementation expectations
Documentation only.

## Required tests
None.

## Verification requirements
Owner-attributed values with dates.

## Acceptance criteria
Each spec states Draft, Approved or Superseded, its revision, and the approval date, from the owner.

## Evidence
None recorded.

## Review and approval
Not requested.
