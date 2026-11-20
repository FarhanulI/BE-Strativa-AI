# T-013: CI with database tests (verification infrastructure)

- **Module and phase:** None of its own. Verification infrastructure that serves T-002 (Phase 0) and T-003 (Phase 1). It is not the `delivery` module (Phase 9, no specification).
- **State:** In Progress (owner started 2026-11-20 after accepting T-002; plan decisions below)
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

## Preparation decisions (2026-11-20)
- **Safety check form:** a DB-free test, `tests/unit/architecture/test_ci_workflow_safety.py`: no `secrets.`, `pull_request_target`, `workflow_run` or explicit token reference; every `uses:` pinned to a 40-hex SHA; top-level `permissions: contents: read`; no Neon or real-provider names.
- **Actions pinned (full SHA, checked against the official repositories with `git ls-remote --tags` on 2026-11-20):** `actions/checkout` v7.0.1 = `3d3c42e5aac5ba805825da76410c181273ba90b1`; `astral-sh/setup-uv` v10.3.3 = `68559e99cc807c1eb7e9238fd43a15bba460eec2`. Both tags are lightweight, so the tag target is the commit. I did not read the action source code. Python comes from `uv` (`UV_PYTHON=3.12`), so `actions/setup-python` is not used. `uv` is pinned to 0.12.5, the version of the local runs.
- **Redis image:** `redis:7.4-alpine` by tag only. The digest was not verified. The service exists for T-015; no test reads it yet, and `REDIS_URL` is deliberately not exported, so existing tests are unchanged.
- **Divergences from local commands:** (1) `uv sync` with `UV_FROZEN=1` and `uv run python scripts/check.py`, instead of `--no-sync`, because the CI environment is fresh; (2) the database URLs come from the process environment, because the local ones live in the git-ignored `.env.test.docker.local`, which CI does not have. The password is generated per job, masked and not a secret. The guard, `run_db_suite.sh` and `compose.test-db.yaml` are unchanged.
- **Postgres major version:** the same image as local (`pgvector/pgvector:pg16`, through the compose file). Whether the Neon test branch has the same major version stays SDD-Q-2.

## Evidence
**Local, 2026-11-20** (before the first CI run)
- Command: `uv run --python 3.12 --no-sync python scripts/check.py`. Exit code 0. Local Windows, Python 3.12.14. ruff clean; mypy clean; pytest `-m "not db"`: 1684 passed, 0 failed, 196 deselected (5 new tests in `test_ci_workflow_safety.py`).
- The workflow YAML parses (`yaml.safe_load`): jobs `checks` and `database`, triggers `pull_request` and `push`.
- **GitHub Actions run: NOT RUN yet.** It starts when this commit is pushed. The run URL, job results and counts are recorded below once read. A deliberately failing change to confirm a red job: NOT RUN.

## Review and approval
Plan started by the owner on 2026-11-20. **Gate: always** (dependencies: CI actions). Result review required before T-014 starts. Independent audit (sdd.md section 11): NOT RUN.
