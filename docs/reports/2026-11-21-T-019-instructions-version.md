# Evidence record: T-019 stop 2 (instructions_version: migration 0009, request type, repository, tests)

## Record

| Field | Value |
| --- | --- |
| Task | [T-019](../tasks/T-019-instructions-version.md) |
| Date of execution | 2026-11-21 |
| Environment | Local Windows, Python 3.12, `uv run`, DB-free. No database, no Redis (`TEST_REDIS_URL` unset for the gate), no Neon, no provider call. |
| Commit | Spec revision 9 commit, then the implementation commit that carries this record; the code was uncommitted when the gate ran |
| Run by | Agent session. The database suite was run later the same day by the owner with `/run-db-suite all` (command 3) |

## Commands

| # | Exact command | Exit code | Passed | Failed | Skipped | Errors |
| --- | --- | --- | --- | --- | --- | --- |
| 1 | `env -u TEST_REDIS_URL uv run python scripts/check.py` (ruff, mypy, `pytest -m "not db"`) | 0 | 1762 | 0 | 4 (the `redis`-marked tests, by design) | 0 |
| 2 | `uv run ruff format --check` on the touched app, migration and test files | 0 | n/a | n/a | n/a | n/a |
| 3 | `bash scripts/run_db_suite.sh all` (via `/run-db-suite all`, local Postgres container `strativa-test-db`, `TEST_DB_MODE=local`) | 0 | 217 | 0 | not reported by the script | 0 |

The previous gate count was 1730 passed (T-018). The 32 new DB-free tests are the label validation tests. 217 tests are deselected by command 1 (the `db` tests). Command 3 ran them: 217 passed (200 before this task plus 17 new), 1766 deselected (the DB-free tests), `cleanup done`. Local PostgreSQL, not Neon.

## Requirements covered

| Requirement ID | Mapped tests that ran | Clause covered | Result | Proposed status |
| --- | --- | --- | --- | --- |
| AC-62 | `test_ai_platform_registries_types.py` (valid and invalid labels, the value never echoed), `test_request_repository_validation.py`, `tests/db/test_ai_platform_schema.py::test_ai_requests_check_constraints_reject_bad_rows`, `::test_instructions_version_accepts_null_and_valid_labels`, `tests/db/test_request_repository.py::test_insert_stores_the_instructions_version_label`, `::test_an_embedding_row_has_no_instructions_version` | Validation, no echo, CHECK refusal, round trip, embedding row null. NOT covered: the same-key different-label `Conflict` clause (needs `submit`, T-011) | passed | Implemented (not Verified: one clause of the requirement is untested) |
| AC-63 | `test_ai_platform_schema_metadata.py::test_alembic_has_a_single_head_after_instructions_version`, `tests/db/test_ai_platform_schema.py::test_instructions_version_migration_keeps_existing_rows_and_is_reversible`, `::test_constraint_and_index_names_match_the_spec` | Whole requirement: nullable column and CHECK only, upgrade, downgrade and upgrade with an existing row, `alembic check` with no drift | passed | Verified (local PostgreSQL; the spec names no Neon scope) |

## Failures

None in the commands that ran.

## Not run

The idempotency `Conflict` clause of AC-62 (same key, different label): `submit` does not exist until T-011. A Neon run: none, and none is required by AC-62 or AC-63.

## Decisions and deviations

1. **Migration revision id** is `0009_instructions_version`, not `0009_ai_requests_instructions_version` as CP-2 wrote. Alembic's version column holds 32 characters by default and the longer id has 37. The file name matches. No spec text names the revision id.
2. **Error messages.** `AiTaskRequest` now sets `hide_input_in_errors=True`. Without it a pydantic error prints the rejected value, which the spec forbids for this field. It applies to every field of `AiTaskRequest` (including `instructions` and the context text, so it also stops those from being echoed). No existing test needed a change.
3. **Repository.** `insert_sync_request` takes an optional `instructions_version` (default None) after `now`, validates it with the same function, and refuses a label on an `EMBED_TEXT` request. `submit` does not exist, so the fingerprint rule of D-36 is only recorded in the spec and applies when T-011 builds it.
4. **Single source for the rule.** `validate_instructions_version` (Python) and `INSTRUCTIONS_VERSION_RULE` (SQL) express the same rule. A drift between them is caught only by the DB tests (CHECK refusal and the valid-label test), which passed in command 3.
5. An existing head test was renamed and updated for the new head (`test_alembic_has_a_single_head_after_instructions_version`).
