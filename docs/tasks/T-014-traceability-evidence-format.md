# T-014: Traceability evidence format

- **Module and phase:** None (SDD process support); serves T-002 and T-003
- **State:** Proposed
- **Requirement IDs:** None: process support. It changes no requirement and no status.
- **Specification references:** [traceability.md](../traceability.md) rules 1 to 11; [sdd.md](../sdd.md) sections 4 and 6; T-012 proposals P-2 and P-3
- **Dependencies:** T-012 approved (it defines the evidence rule this task puts into a template). Must exist before T-002 records its first result.

## Objective
Give every recorded verification run one dated, linkable record with the same fields, so that an Evidence cell can link to it and an unrun item is visibly `NOT RUN`.

## Scope
- A report template under `docs/reports/`, named `_template-evidence.md`, with these fields: task, date, environment, commit, one table of commands (exact command, exit code, passed, failed, skipped, errors), requirement IDs covered (with the clause covered when partial), failures, items `NOT RUN` with reason.
- File naming for records: `docs/reports/YYYY-MM-DD-<task>-<scope>.md`.
- The Evidence cell format for traceability rows: `[YYYY-MM-DD <env>](reports/<file>.md#<anchor>)`. No row is changed by this task.
- A short procedure note for `sdd-verify` users, inside the template (the skill file is not edited here).

## Non-goals
Changing any row's status. Recording any run (T-002 and T-003 do that). Editing `traceability.md` rules, `sdd-verify`, or `phase0-verification.md`. Tooling that validates links (candidate for a later task).

## Implementation expectations
One new template file and nothing else. Fields mirror P-2 exactly so that the template is the rule in usable form.

## Required tests
None (documentation).

## Verification requirements
`sdd-close-milestone` link checks on the new file, with commands and results recorded.

## Acceptance criteria
The template exists, contains every P-2 field, and a trial record built from it (not committed as evidence) shows `NOT RUN` for an unexecuted item.

## Evidence
None recorded.

## Review and approval
Not requested. **Gate: milestone end.**
