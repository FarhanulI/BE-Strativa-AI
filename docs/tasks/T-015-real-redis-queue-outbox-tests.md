# T-015: Real-Redis queue, outbox and lease tests

- **Module and phase:** jobs_workers, events_outbox, observability_audit; Phase 0
- **State:** Accepted (owner started 2026-11-20; runs recorded 2026-11-20; 3 of 4 requirements `Verified`, OBS-AC-3 stays `Gap`; accepted by the owner 2026-11-25, "accept T-014, T-015 and T-016")
- **Requirement IDs:** JOB-AC-2 (currently `Gap`), OUT-AC-3 (`Gap`), OBS-AC-3 (`Gap`), and the lease-reclaim clause of OUT-AC-2 (`Implemented`, partial). JOB-AC-1 and JOB-AC-3 are not changed.
- **Specification references:** [jobs-workers](../specs/jobs-workers/spec.md), [events-outbox](../specs/events-outbox/spec.md), [observability-audit](../specs/observability-audit/spec.md) acceptance criteria; [conformance report](../architecture/conformance-report.md) E-2, E-4
- **Dependencies:** T-013 for the CI Redis service (the tests can be developed locally first). T-014 for recording. A real Redis instance. T-002 depends on this task for its JOB rows, which stay `Gap` until it is done.

## Objective
Replace mock-based and manual evidence with automated tests against a real Redis and a real local Postgres for the queue, the outbox relay and event worker, lease reclaim, and cross-component correlation.

## Scope
- JOB-AC-2: enqueue, claim, ack; redelivery after consumer failure; dead-letter after exhaustion, using the real `JobQueue`.
- OUT-AC-3: the relay publishes correlation metadata and retries with bounded backoff (`app/jobs_workers/relay.py`, `mark_delivery_failed`).
- OUT-AC-2 clause: an expired outbox lease can be reclaimed.
- OBS-AC-3: one automated test that follows a single correlation ID through API call, outbox, worker and audit, replacing the manual `scripts/demo_ping.py` check as the repeatable evidence.
- Test isolation: a unique stream name and consumer group per test, cleanup in teardown, a dedicated Redis database index, and refusal of a non-loopback `TEST_REDIS_URL`. Tests must fail loudly, not skip silently, when Redis is not reachable in CI.
- A `redis` pytest marker declared in `pyproject.toml`. This is a dependency-free configuration change but it touches `pyproject.toml`, so it is listed for the owner's review.

## Non-goals
Changing `JobQueue`, the relay or the worker behavior. Neon. Load or failover testing. A scheduler (D-2). Starting Redis for the owner: how a developer runs Redis locally is SDD-Q-1; the agent never starts Docker.

## Implementation expectations
Tests live under `tests/` and name their requirement IDs in the docstring. The Redis URL comes from the environment, never from `.env*` files read by the agent. If a defect is found, stop and report; fixing it is another task.

## Required tests
The four items in Scope. DB parts run only through `/run-db-suite`.

## Verification requirements
Local run against a real Redis and the local Postgres container, and the CI run from T-013. Each recorded with commands, exit codes, counts and date (T-014 format). A part not run is `NOT RUN`.

## Acceptance criteria
JOB-AC-2, OUT-AC-3 and OBS-AC-3 each have a mapped, executed test with dated evidence, or stay `Gap` with the reason. The OUT-AC-2 lease clause has a mapped test.

## Implementation record (2026-11-20)
- `pyproject.toml`: one `redis` marker added to `markers` (the only change to that file; dependencies untouched).
- `tests/helpers/redis_setup.py` and a `redis_scope` fixture in `tests/conftest.py`: URL only from `TEST_REDIS_URL`; loopback host, plain `redis://`, dedicated non-zero database index required; fixed error messages; unique key prefix per test and cleanup of only that prefix. Unset URL: the test is skipped with a visible reason, unless `REQUIRE_REDIS_TESTS=1`, which fails loudly (for CI). Set but wrong or unreachable: fail.
- `tests/redis_integration/test_job_queue_redis.py` (JOB-AC-2, 4 tests, `redis`): enqueue/claim/ack; redelivery after consumer failure (`XCLAIM IDLE` ages one message, no sleep); retry with backoff then success; dead-letter after exhaustion (delays 2, 4, 8, then the dead-letter entry).
- `tests/db/test_outbox_relay_redis.py` (OUT-AC-3 two tests, OBS-AC-3 one test, `db` and `redis`): correlation metadata reaches the stream; bounded backoff driven by a real Redis WRONGTYPE refusal (delays 2 to 256, capped below 300), then publication; one request ID across outbox, relay, worker and audit.
- `tests/db/test_outbox_lease_reclaim.py` (OUT-AC-2 clause, `db` only): committed live lease is not claimable, expired lease is reclaimed by another relay.
- `tests/unit/jobs_workers/test_redis_test_target.py`: DB-free tests of the helper (14 cases).
- `docs/traceability.md`: test references added for JOB-AC-2, OUT-AC-3, OBS-AC-3 and OUT-AC-2; JOB-AC-2 and OUT-AC-3 moved `Gap` to `Implemented`; OBS-AC-3 stays `Gap`; none `Verified`.

## Finding (stop-and-report item, not fixed here)
API route handlers that publish events do not put a request ID into the outbox metadata. Example: `app/auth/routes.py` `register` calls `publish(session, UserRegistered(...))` with no `metadata`, and `DomainEvent.envelope` uses only the metadata passed in. So a request ID sent to the API (`X-Request-ID`) does not reach the outbox row, the stream, the worker or the audit row. OBS-AC-3 says one correlation ID can be verified across API, outbox, worker and audit. The T-015 test covers every hop except the API, with an explicitly supplied ID. A fix would change `publish` or its callers, which is outside this task and needs its own task (owner decision).

## Evidence
**Local DB-free gate, 2026-11-20** (branch `feat/Ai-platform`, uncommitted changes at the time of the run)
- Command: `uv run --python 3.12 --no-sync python scripts/check.py`. Exit code 0. Local Windows, Python 3.12.14. ruff clean; mypy clean; pytest `-m "not db"`: 1698 passed, 4 skipped, 0 failed, 200 deselected. The 4 skipped are the Redis-only job queue tests, skipped because `TEST_REDIS_URL` is not set. The 14 helper tests ran and passed (1684 to 1698 passed).
- Collection: the 8 new integration tests collect (`pytest --collect-only`): 4 in `tests/redis_integration`, 3 in `test_outbox_relay_redis.py`, 1 in `test_outbox_lease_reclaim.py`.

**Run 1, 2026-11-20, Redis-only tests** (run by the agent in the owner's session; `TEST_REDIS_URL` set, checked as set or not set only)
- Command: `uv run --python 3.12 --no-sync python -m pytest tests/redis_integration -q -rs`. Exit code 0. 4 passed, 0 failed, 0 skipped.
- Environment: local Windows, Python 3.12.14, pytest 9.1.1; Redis `redis:7.4-alpine` in the owner's container `strativa-test-redis` on `127.0.0.1:6379`, database index 15. Container started by the owner, not by the agent. Not Neon, no managed Redis.
- Requirement covered: JOB-AC-2 (all three clauses).

**Run 2, 2026-11-20, local database suite with Redis** (run by the owner through `/run-db-suite all`)
- Command: `bash scripts/run_db_suite.sh all`. Exit code 0. 200 passed, 0 failed; 1702 deselected (the DB-free tests and the 4 Redis-only tests, which are not `db`-marked). The script prints no skipped count; the progress lines show no skipped test and the passed count equals the selected count (200).
- Environment: local Postgres container `strativa-test-db` (`TEST_DB_MODE=local`) and the same local Redis (`TEST_REDIS_URL` inherited from the environment). `cleanup done` printed.
- Included: `test_outbox_relay_redis.py` (3 tests), `test_outbox_lease_reclaim.py` (1), and all earlier DB tests. An earlier attempt with an extra argument was refused by the script (exit 2, no tests, no container).
- Requirements covered: OUT-AC-3, OUT-AC-2 (rollback, concurrent claim, committed live lease, expired lease reclaim, idempotency), and the correlation test for OBS-AC-3 (outbox, relay, worker, audit).

**Row statuses set by these runs:** JOB-AC-2, OUT-AC-3 and OUT-AC-2 are `Verified`. OBS-AC-3 stays `Gap`: the test passed for outbox, relay, worker and audit, but the API hop is not met (see Finding). Traceability evidence cells link here.

**Still NOT RUN:** the CI run (T-013 deferred); the independent audit; any Neon run. Redis was not run with `REQUIRE_REDIS_TESTS=1`.

## Review and approval
Plan started by the owner on 2026-11-20. **Gate: milestone end.** The `pyproject.toml` change is a single added marker, so the gate is not raised; the owner may raise it. Independent audit (sdd.md section 11): NOT RUN. The task is not `Verified` because OBS-AC-3 is not met (API hop, a decision for the owner). Accepted by the owner 2026-11-25 ("accept T-014, T-015 and T-016"); OBS-AC-3 stays `Gap` and the independent audit stays NOT RUN.
