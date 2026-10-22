# Jobs and Workers Module Specification

## Backend

### Purpose

Provide Redis-backed asynchronous job/event delivery, worker lifecycle, retries, dead-letter handling, and idempotent consumer execution for long-running or non-critical work.

### Architecture sections implemented

- Product architecture §§53, 55, 58, 62.

### Owned entities

- Versioned `JobEnvelope` value contract and Redis stream/consumer-group conventions.
- Worker registry, retry policy, and dead-letter stream handling. Redis is infrastructure state, not a domain database table.

### DB schema and indexes

No SQL tables. Redis streams carry job ID, type/version, JSON payload, enqueue timestamp, attempt, and request/correlation/causation metadata. Configure a primary stream, consumer group, and dead-letter stream per queue. Redis persistence/retention are deployment settings and must be documented; no payload secrets.

### Public interface

- `enqueue_job(redis, job)` validates the registered schema and appends to the stream.
- Worker registration binds a typed handler to a job type/version.
- Worker loop claims messages through consumer groups, acknowledges success, retries transient failures with bounded exponential backoff, and moves exhausted/permanent failures to the DLQ with a sanitized failure code.
- Shutdown stops intake, drains within a bounded grace period, and leaves unacknowledged work recoverable.
- Health check reports Redis independently and never logs the Redis URL.

### OpenAPI endpoints

None. Readiness transport is owned by `api_contract`.

### Events in/out

Consumes versioned event envelopes from `events_outbox`'s public Redis stream contract; delivers registered jobs to handlers. No imports of outbox persistence internals. Handler DB effects use an explicit session and `ProcessedEvent` idempotency contract.

### Jobs

Owns generic worker execution and retry semantics, including the outbox relay scheduling/worker entrypoint. Individual business jobs belong to their domain modules.

### AI tasks used

None.

### Authorization rules

No end-user authorization. Redis is a trusted service; restrict credentials/network access operationally and avoid secrets in job payloads.

### Invariants

- Acknowledgement occurs only after handler success/committed effects.
- Retries are bounded and idempotency is required for handlers with side effects.
- Shutdown/restart does not discard pending or unacknowledged work.
- Job errors and trace context are sanitized and correlated.

### Acceptance criteria

- Unit tests cover validation, retry classification/backoff, shutdown behavior, and DLQ routing.
- Redis integration tests cover enqueue/claim/ack, redelivery after consumer failure, and DLQ after exhaustion.
- Readiness reports Redis `not_configured` when optional configuration is absent and does not attempt a connection during OpenAPI generation.

### Non-goals

Business job implementations, a SQL job scheduler, Kafka, arbitrary code execution, or exactly-once delivery.

### Deviations

- The original interface describes `enqueue_job(redis, job)` validating a registered schema. The implementation exposes `JobQueue.enqueue(job)` and does not validate against a job-schema registry at enqueue time; `JobRegistry` resolves handlers during processing.

## Frontend

to be added by the FE task.

## Public interfaces and events later features must use

- Import `JobEnvelope`, `JobQueue`, and `JobRegistry` from `app.jobs_workers`; worker entrypoints are `run_worker` and `run_worker_process`, and outbox integration is exposed through `EventWorker` and `OutboxRelay`.
- Queue API: `JobQueue(redis, *, stream="jobs", dead_letter_stream="jobs:dead", clock=None, max_attempts=5)`, `await JobQueue.enqueue(job: JobEnvelope) -> str`, `JobRegistry.register(job_type: str, version: int, handler: JobHandler) -> None`, and `await JobQueue.process_fields(fields, *, registry: JobRegistry) -> str`. A job carries `job_id`, `job_type`, `job_version` (default 1), payload, string metadata, and attempt count.
- Job type/version identifies the handler contract. The queue accepts versioned event envelopes from `events_outbox`; this module defines no named business event types or AI tasks. Retry and dead-letter behavior is bounded; handlers with side effects must be idempotent.
- OpenAPI endpoints: none. Shared errors and pagination use `app.core.ProblemDetails`, `CursorParams`, and `CursorPage[T]`. `REDIS_URL` is optional for DB-free startup/OpenAPI; actual queue and demo use require a real Redis service. Do not put credentials in payloads. No additional environment-selection rules are specified here; see `app.core`.
