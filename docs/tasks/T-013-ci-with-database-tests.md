# T-013: CI with database tests (verification infrastructure)

- **Module and phase:** None of its own. Verification infrastructure that serves T-002 (Phase 0) and T-003 (Phase 1). It is not the `delivery` module (Phase 9, no specification).
- **State:** Proposed
- **Requirement IDs:** None: dependency on T-002 and T-003. The task executes tests already mapped in [traceability.md](../traceability.md); it adds no product behavior and satisfies no requirement by itself.
- **Specification references:** [conformance report](../architecture/conformance-report.md) findings E-1, C-1; [README Test database modes](../../README.md); DBM-AC-4 (the fixture and guard are used unchanged)
- **Dependencies:** T-002 approved first. T-012 approved (gates, safety tiers). For fork pull requests, no secrets are used.

## Objective
Run the DB-free checks and the database-marked tests automatically on every pull request, so that tenant-isolation and role-matrix tests stop depending on someone running them by hand.

## Scope
- One workflow, `.github/workflows/ci.yml`, triggered by `pull_request` and by `push` to the working branches. Not `pull_request_target`.
- Steps: install Python 3.12 and `uv` at pinned versions; `ruff check`; `mypy`; `pytest -m "not db"`; the database suite on a local container in the existing local mode (`TEST_DB_MODE=local`, `APP_ENV=test`); a Redis service container for T-015.
- The database suite uses the existing guard unchanged: `compose.test-db.yaml` (image `pgvector/pgvector:pg16`, fixed name, `127.0.0.1:55444`, marker script) and `bash scripts/run_db_suite.sh all`. `TEST_DB_PASSWORD` is a throwaway value generated inside the job and masked; it is not a repository or organization secret.
- Third-party actions are pinned to a full commit SHA with the version in a comment; each SHA is checked against the action's official repository in the same session.
- Workflow `permissions: contents: read`; job timeouts; concurrency cancels superseded runs.
- The workflow references no secrets, so fork pull requests run without any.

## Non-goals
Neon (the nightly Neon run belongs to T-001 and needs its own authorization and a separate workflow). Deploys, releases, caching tuning, coverage reporting, any product code. Changing the guard, `run_db_suite.sh` or `compose.test-db.yaml`. The Phase 9 `delivery` module.

## Implementation expectations
Smallest workflow that runs the same commands as local development (`scripts/check.py` behavior plus the DB suite). Any divergence from local commands is recorded in the task. The Postgres major version in CI equals the local container's; whether the Neon test branch runs the same major version is not documented here and is raised as SDD-Q-2.

## Required tests
The existing suite is the test. Add one check that the workflow file contains no `secrets.` reference and no `pull_request_target` (a DB-free test, or a `sdd-arch-check` step; decided at preparation).

## Verification requirements
A recorded CI run on a pull request from a branch of this repository: run URL, date, job results, counts of passed, failed, skipped and deselected tests, and exit codes. A run that was not executed is `NOT RUN`. A deliberately failing change confirms the job turns red (recorded, then reverted).

## Acceptance criteria
- A pull request runs lint, type check, DB-free tests, the database suite and the Redis service.
- No secret is referenced; fork pull requests get no secret.
- All actions are pinned by SHA.
- The recorded run shows counts that match the local `/run-db-suite` counts for the same commit, or the difference is explained.

## Evidence
None recorded.

## Review and approval
Not requested. **Gate: always** (dependencies: CI actions). Plan approval required.
