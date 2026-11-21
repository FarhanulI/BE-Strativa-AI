# Evidence record: T-019 stop 2 (instructions_version: migration 0009, request type, repository, tests)

## Record

| Field | Value |
| --- | --- |
| Task | [T-019](../tasks/T-019-instructions-version.md) |
| Date of execution | 2026-11-21 |
| Environment | Local Windows, Python 3.12, `uv run`, DB-free. No database, no Redis (`TEST_REDIS_URL` unset for the gate), no Neon, no provider call. |
| Commit | Spec revision 9 commit, then the implementation commit that carries this record; the code was uncommitted when the gate ran |
| Run by | Agent session. The database suite is NOT RUN here (owner runs `/run-db-suite all`) |

## Commands

| # | Exact command | Exit code | Passed | Failed | Skipped | Errors |
| --- | --- | --- | --- | --- | --- | --- |
| 1 | `env -u TEST_REDIS_URL uv run python scripts/check.py` (ruff, mypy, `pytest -m "not db"`) | 0 | 1762 | 0 | 4 (the `redis`-marked tests, by design) | 0 |
| 2 | `uv run ruff format --check` on the touched app, migration and test files | 0 | n/a | n/a | n/a | n/a |
| 3 | `/run-db-suite all` | NOT RUN | n/a | n/a | n/a | n/a |

The previous gate count was 1730 passed (T-018). The 32 new DB-free tests are the label validation tests. 217 tests are deselected (the `db` tests; it was 200 before, so 17 new DB tests exist and are unexecuted).

## Requirements covered

| Requirement ID | Mapped tests that ran | Clause covered | Result | Proposed status |
| --- | --- | --- | --- | --- |
| AC-62 | `test_ai_platform_registries_types.py` (valid and invalid labels, the value never echoed), `test_request_repository_validation.py` (repository validation, no label on an embedding request) | Unit part: validation and no echo of the value | passed | Implemented. The DB part (CHECK refuses bad labels, round trip, embedding row null) is written and has NOT RUN. The same-key different-label `Conflict` clause needs `submit` (T-011) and is not covered |
| AC-63 | `test_ai_platform_schema_metadata.py::test_alembic_has_a_single_head_after_instructions_version` (DB-free: one head, chain 0007, 0008, 0009) | Only the single-head and chain clause | passed | Implemented. Upgrade, downgrade, upgrade with an existing row and `alembic check` are written (`tests/db/test_ai_platform_schema.py`) and have NOT RUN |

## Failures

None in the commands that ran.

## Not run

`/run-db-suite all`: the migration, the CHECK constraint, the round-trip and the constraint-name test (`EXPECTED_CONSTRAINTS` now lists `ck_ai_requests_instructions_version`), plus the reversibility test. Nothing marks AC-62 or AC-63 `Verified` before that run.

## Decisions and deviations

1. **Migration revision id** is `0009_instructions_version`, not `0009_ai_requests_instructions_version` as CP-2 wrote. Alembic's version column holds 32 characters by default and the longer id has 37. The file name matches. No spec text names the revision id.
2. **Error messages.** `AiTaskRequest` now sets `hide_input_in_errors=True`. Without it a pydantic error prints the rejected value, which the spec forbids for this field. It applies to every field of `AiTaskRequest` (including `instructions` and the context text, so it also stops those from being echoed). No existing test needed a change.
3. **Repository.** `insert_sync_request` takes an optional `instructions_version` (default None) after `now`, validates it with the same function, and refuses a label on an `EMBED_TEXT` request. `submit` does not exist, so the fingerprint rule of D-36 is only recorded in the spec and applies when T-011 builds it.
4. **Single source for the rule.** `validate_instructions_version` (Python) and `INSTRUCTIONS_VERSION_RULE` (SQL) express the same rule. A drift between them is caught only by the DB tests that have not run yet.
5. An existing head test was renamed and updated for the new head (`test_alembic_has_a_single_head_after_instructions_version`).
