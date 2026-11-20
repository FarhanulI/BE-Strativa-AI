# T-015: Real-Redis queue, outbox and lease tests

- **Module and phase:** jobs_workers, events_outbox, observability_audit; Phase 0
- **State:** Proposed
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

## Evidence
None recorded.

## Review and approval
Not requested. **Gate: milestone end.** (Raised to always if `pyproject.toml` marker handling needs more than one line.)
