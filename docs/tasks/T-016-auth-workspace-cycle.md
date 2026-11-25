# T-016: auth and workspace dependency cycle (check, then fix)

- **Module and phase:** auth, workspace, api_contract (composition root); Phase 1 and Phase 0
- **State:** Accepted by the owner 2026-11-25 ("accept T-014, T-015 and T-016"); steps 0 to 2 done 2026-11-20; step 1 exemption approved by the owner; step 2 result reviewed and accepted
- **Requirement IDs:** CORE-INV-11, WS-AC-7 (the boundary rules the check strengthens); AUTH-AC-2 and AUTH-AC-7 (must stay satisfied by the fix)
- **Specification references:** [auth-onboarding](../specs/auth-onboarding/spec.md) (registration calls `WorkspaceService.create_workspace_for_owner(session, user_id, name)` in the caller-owned transaction; `/me` reads roles through the workspace public interface); [workspace](../specs/workspace/spec.md); [conformance report](../architecture/conformance-report.md) B-1 (corrected 2026-11-20); ADR-0003 (proposed)
- **Dependencies:** A recorded baseline run of the auth and workspace DB tests before any change (step 0), from T-003 or from this task. T-013 preferred. Owner decisions of 2026-11-20: dependency inversion at the composition root; the protocol takes the caller's session or unit of work; the cycle check includes function-level imports; owner review between step 1 and step 2.

## Objective
Make the package import graph acyclic without changing observable behavior: registration stays one transaction (AUTH-AC-2), `/me` still reads roles through the workspace public interface (AUTH-AC-7).

## Scope
**Step 0, baseline.** Run the auth and workspace DB tests through `/run-db-suite` and the DB-free suite before touching code. Record the result (T-014 format). Stop if the baseline is red.

**Step 1, cycle check (tests only; review follows).**
- Add a DB-free architecture test that builds the package-level import graph of `app/` from the AST and fails on any cycle.
- It must include imports inside functions and methods (such as the lazy import in `app/auth/__init__.py:register_routes`), not only module-level imports. String-based dynamic imports are out of scope and the limit is stated in the test.
- Landing it on a red tree is not allowed. The one known cycle (auth and workspace) is listed in a visible allowlist that names this task and step 2; step 2 removes the entry.
- Stop for owner review.

**Step 2, fix (after review).**
- `auth` defines protocols that receive the caller's `AsyncSession` (or unit of work) and return what auth needs: a workspace provisioner for registration, and a role reader for `/me`. Auth imports no `app.workspace` name.
- `workspace` implements them; `workspace` keeps depending on `auth` for `get_current_user` (the one remaining direction).
- `api_contract.create_app` wires the implementations into `auth` when routes are registered; the lazy import disappears.
- The allowlist entry is removed; ADR-0003 is updated from proposed to the recorded decision.

## Non-goals
Any change to behavior, routes, OpenAPI, events or schema. Editing any spec. Using the outbox or any asynchronous mechanism for registration. Fixing B-2 or B-3 (ORM export and table-ownership checks). Other module pairs.

## Implementation expectations
If, during step 2, the spec wording of AUTH-AC-2 or AUTH-AC-7 turns out to require a direct import, stop and write a change proposal. Boundaries: protocols live in `auth`; no new cross-module import other than through package exports. Commits cite T-016, the step and the IDs.

## Required tests
- Step 1: the cycle test (fails on a seeded cycle in a fixture, passes on the allowlisted tree).
- Step 2: the existing registration and `/me` DB tests unchanged, including the rollback test for AUTH-AC-2, plus `test_checked_in_openapi_matches_registered_routes` (OpenAPI must not change), the boundary test, and the cycle test with the allowlist empty.

## Verification requirements
Before and after runs with exact commands, exit codes and counts. DB tests only through `/run-db-suite`. The after-run must equal the baseline except for the added test.

## Acceptance criteria
- The cycle test exists, sees function-level imports, and with an empty allowlist passes.
- AUTH-AC-2 and AUTH-AC-7 tests pass before and after with the same counts.
- No `app.auth` file imports `app.workspace`.
- OpenAPI output is unchanged.

## Step 1 record (2026-11-20)
- `tests/helpers/import_graph.py`: package-level import graph from the AST (every `import` and `from ... import`, including inside functions, methods and `if TYPE_CHECKING`; relative imports resolved; `from app import x` counted) and a Tarjan cycle finder.
- `tests/unit/architecture/test_package_import_cycles.py` (9 tests): the real-tree test with a visible `KNOWN_CYCLES` allowlist (auth and workspace; step 2 removes it; a stale entry also fails), edge-visibility, the exemption-soundness test, the "without the exemption" documentation test, and six seeded-fixture tests (module-level, function-level, method-level, three-node cycles, relative imports, acyclic graph with third-party imports).
- `traceability.md`: the test is listed on CORE-INV-11 and WS-AC-7 (status unchanged, `Implemented`).

## Finding that changes the premise of this task (owner decision needed)
The task states one known cycle, auth and workspace. The AST graph shows a second source of cycles that the earlier analysis did not report: `app/db_migrations/alembic/env.py` imports the models of `ai_platform`, `auth`, `events_outbox`, `observability_audit`, `profile` and `workspace` (the Alembic metadata registry, ADR-0005), while each of those packages imports `app.db_migrations` for `Base`, `database_session` or `runtime_engine`. Counted as is, the whole graph is one strongly connected component of eight packages: ai_platform, auth, db_migrations, events_outbox, jobs_workers, observability_audit, profile, workspace. (jobs_workers joins through `workspace/jobs.py` importing it and `jobs_workers` importing `events_outbox`.)

Excluding that single file leaves exactly one cycle, auth and workspace, matching the task. So step 1 as written needs a decision:
- **Proposed (implemented, pending your review):** a second visible list, `REGISTRY_EXEMPT_FILES`, containing only `db_migrations/alembic/env.py`, with its rationale; a test that no file under `app/` imports `app.db_migrations.alembic` (so the exemption stays sound) and a test that without it the large cycle exists (so the exemption cannot go stale silently).
- **Alternative:** keep the graph unexempted and treat `db_migrations` as a lower layer by moving the registry out of the package. That is an architecture change outside this task (ADR-0005), so I did not do it.
- **Also noted:** the auth to workspace edge is a module-level import in `app/auth/routes.py` line 37, which `app/auth/__init__.py` loads lazily inside `register_routes`. The AST sees `routes.py`, so the lazy import does not hide the edge from this check. Step 2's inversion must cover `routes.py` and `service.py`, not only `__init__.py`.

## Evidence
**Step 0, baseline (2026-11-20)**
- DB-free gate, run now: `env -u TEST_REDIS_URL uv run --python 3.12 --no-sync python scripts/check.py`, exit 0, ruff and mypy clean, pytest `-m "not db"`: 1707 passed, 4 skipped, 0 failed, 200 deselected. This includes the 9 new step 1 tests; the baseline before them was 1698 passed, 4 skipped (T-015 record). `TEST_REDIS_URL` was unset for this process only: the Redis container from T-015 was no longer running, and with the variable set the 4 Redis-only tests fail loudly by design.
- Database suite baseline: not re-run for this task. Reused from [T-015 Run 2](T-015-real-redis-queue-outbox-tests.md#evidence): `bash scripts/run_db_suite.sh all`, exit 0, 200 passed, 0 failed, local Postgres. No file under `app/` has changed since (`git diff --stat 11f779f HEAD -- app` is empty), and the only test changes since are step 1's DB-free files. It includes `tests/db/test_auth_workspace.py` (13 tests), the AUTH-AC-2 and AUTH-AC-7 tests. A fresh `/run-db-suite all` baseline is available on request.

**Step 1 test run:** `uv run --python 3.12 --no-sync python -m pytest tests/unit/architecture/test_package_import_cycles.py -q`: 9 passed.

**Step 2 (2026-11-20, commit `7426ceb`)**
- Changes: `app/auth/ports.py` (new), `app/auth/routes.py`, `app/auth/__init__.py`, `app/api_contract/app.py`, and the cycle test (allowlist emptied; three tests replace the edge test).
- DB-free gate: `env -u TEST_REDIS_URL uv run --python 3.12 --no-sync python scripts/check.py`, exit 0, ruff and mypy clean, pytest `-m "not db"`: 1709 passed, 4 skipped, 0 failed, 200 deselected (baseline 1707 plus 2 net new tests). The OpenAPI freshness test and the boundary test are among them.
- Import check: `app.auth`, `app.workspace`, `app.profile`, `app.api_contract`, `app.events_outbox`, `app.db_migrations` each import in a fresh interpreter.
- **After-run, first attempt:** `bash scripts/run_db_suite.sh all`, exit 1, 197 passed, 3 errors, 0 failed. The 3 errors were the `db`+`redis` tests in `test_outbox_relay_redis.py`, which fail at fixture setup with "TEST_REDIS_URL is set but Redis is not reachable" because the owner's Redis container was stopped. Not related to the refactor; everything else passed.
- **After-run, Redis running (owner ran `/run-db-suite all`):** `bash scripts/run_db_suite.sh all`, exit 0, **200 passed, 0 failed**, 1713 deselected, `cleanup done`. Local Postgres container and local Redis, `TEST_DB_MODE=local`.
- **Comparison:** the before-run (T-015 Run 2, same `app/` code except step 2) was 200 passed; the after-run is 200 passed. `tests/db/test_auth_workspace.py` ran 13 passed in both. Equal counts.

**Acceptance criteria**
- Cycle test exists, sees function-level imports (seeded fixtures), and passes with an empty allowlist: met (exemption of the Alembic registry approved by the owner).
- AUTH-AC-2 and AUTH-AC-7 tests pass before and after with the same counts: met (13 in `test_auth_workspace.py` and 200 in total, both runs).
- No `app.auth` file imports `app.workspace`: met (checked by graph and by the test).
- OpenAPI output unchanged: met (`test_checked_in_openapi_matches_registered_routes` passes; `openapi.json` untouched).

**Row statuses:** CORE-INV-11, WS-AC-7, AUTH-AC-2, AUTH-AC-7 (and AUTH-INV-1, AUTH-INV-7) stay `Implemented`: each carries Partial coverage notes that this task did not close. Nothing is `Verified` by this task.

**NOT RUN:** the independent audit; CI (T-013 deferred); Neon.

## Review and approval
Plan started by the owner on 2026-11-20. **Gate: always** (auth behavior; contracts). Owner review after step 1: done, exemption approved 2026-11-20. Owner review after step 2: **done, accepted 2026-11-25** (gate always; the acceptance confirms ADR-0003 as Accepted as implemented).
