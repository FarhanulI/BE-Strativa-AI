# T-014: Traceability evidence format

- **Module and phase:** None (SDD process support); serves T-002 and T-003
- **State:** Accepted by the owner 2026-11-25 ("accept T-014, T-015 and T-016"); owner started 2026-11-20
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
- 2026-11-20: created `docs/reports/_template-evidence.md` (one new file). Field check by script: it contains exact command, exit code, passed, failed, skipped, errors, environment, date, commit, requirements covered (with clause), failures, `NOT RUN` section, and the procedure note. Mirrors P-2 (sdd.md section 10).
- Trial record (scratchpad, not committed): built from the template with one unexecuted command; it renders `NOT RUN` with its reason in the Not run table. This is the acceptance trial.
- Link check (ad-hoc local script, not `sdd-close-milestone`): 27 links in the 2 changed markdown files, 1 flagged. The flagged item is the literal placeholder `reports/<file>.md#<anchor>` inside a code span of the procedure note, not a real link. Exit code of the script was 1 for that reason.
- Note: the 8 traceability rows verified in T-002 link to `tasks/T-002-phase0-reverification.md#evidence`, not to a `docs/reports/` record in this format. This task changes no row (non-goal); migrating them is a candidate follow-up.
- Local database suite: NOT RUN, not applicable. The owner clarified on 2026-11-20 that `/run-db-suite all` is run for tasks that implement something for a phase; this task changes documentation only. An attempted run was stopped by the owner before it produced output, and no container was left behind (checked with `docker ps -a`).
- `sdd-close-milestone`: NOT RUN. Independent audit: NOT RUN.

## Review and approval
Plan approved by the owner on 2026-11-20 ("start T-014"). Accepted by the owner 2026-11-25 ("accept T-014, T-015 and T-016"). **Gate: milestone end** (documentation only; no migration, contract, security, dependency, ADR or AI-target change).
