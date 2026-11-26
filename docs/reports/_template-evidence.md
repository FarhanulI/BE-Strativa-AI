# Evidence record: <task ID> <scope>

Copy this file to `docs/reports/YYYY-MM-DD-<task>-<scope>.md` (for example `2026-11-20-T-002-phase0-db-free.md`) and fill every field. Write `None` or `NOT RUN` rather than leaving a field out. Rules: [sdd.md](../sdd.md) sections 6 and 10 to 11, [traceability.md](../traceability.md) rules 1 to 11.

## Record

| Field | Value |
| --- | --- |
| Task | `T-nnn` (link) |
| Date of execution | `YYYY-MM-DD` |
| Environment | Where it ran, for example: local Windows, Python 3.12.x, local container `strativa-test-db` (`TEST_DB_MODE=local`); or: CI run URL. Name Neon only if it truly ran on Neon. |
| Commit | Full or short SHA the run used, and whether the working tree had uncommitted changes |
| Run by | Agent session, owner, or CI. Name the owner for `/run-db-suite` (the skill is manual-only) |

## Commands

One row per command. Exact command line with secrets omitted. A command that was not executed gets `NOT RUN` in the exit-code cell and its reason in the Notes table below.

| # | Exact command | Exit code | Passed | Failed | Skipped | Errors |
| --- | --- | --- | --- | --- | --- | --- |
| 1 | `<command>` | `<n>` | `<n>` | `<n>` | `<n or "not reported">` | `<n>` |

A count the tool does not print is written `not reported`, never `0` and never guessed. Deselected tests are not skipped tests; note them below.

## Requirements covered

One row per requirement ID. Say which clause the run covers when the coverage is partial. A row is eligible for `Verified` only when the run covers the requirement's whole scope in the environment the requirement names.

| Requirement ID | Mapped tests that ran (file::name) | Clause covered | Result | Proposed status |
| --- | --- | --- | --- | --- |
| `<MODULE>-AC-n` | `tests/...::test_...` | whole requirement, or the named clause | passed / failed | Verified / Implemented / Gap / Blocked, with the reason if not Verified |

## Failures

None, or one entry per failing test: test name, exception class, short cause (no secrets, no prompts or user content).

## Not run

Everything that was expected and did not execute. Never leave this section empty if the task lists a required test that is absent from the Commands table.

| Item | Reason |
| --- | --- |
| `<command, test group, environment or requirement>` | `NOT RUN`: for example Docker not running, Redis not available, Neon needs separate authorization |

## Notes

Deselected counts, environment divergences from the documented local commands, and anything a reader needs to reproduce the run.

## Review

| Step | State |
| --- | --- |
| Independent audit (sdd.md section 11) | PASS / PARTIAL / FAIL per criterion, by whom; or `NOT RUN` |
| Owner review | Not requested / accepted on `YYYY-MM-DD` |

---

## Procedure note for `sdd-verify` users

This note is guidance inside the template. It does not replace the `sdd-verify` skill.

1. Run only what the task permits. DB-free: `uv run --python 3.12 --no-sync python scripts/check.py`. Database suite: only through `/run-db-suite all` (owner types it). Never Neon unless a task separately authorizes it.
2. Copy the printed command, exit code and counts into the Commands table as produced. Do not retype from memory or round.
3. Map each requirement to the tests that ran. Do not map a test that was deselected, skipped or never collected.
4. Set a status per requirement from the Requirements table using the rules in [traceability.md](../traceability.md): `Verified` only if the whole scope ran, in the named environment, with no failure and no untested clause in its Notes.
5. In the traceability row, set the Evidence cell to a link in this format and set the status:

   `[YYYY-MM-DD <env>](reports/<file>.md#<anchor>)`

   where `<env>` is a short label such as `local-db-free`, `local-postgres` or `ci`, `<file>` is this record's file name and `<anchor>` is the heading of the section that proves the row (for example `#requirements-covered`). A row without such a link is not `Verified`.
6. List every unexecuted item under Not run. Never write "should pass", "presumably" or "expected to pass".
7. Write Commit message of the record with the traceability change, citing the task and requirement IDs.
