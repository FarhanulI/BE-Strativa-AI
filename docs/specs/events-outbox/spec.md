# Events and Outbox Module Specification

## Backend

### Purpose

Define versioned domain-event envelopes and persist event publication atomically with caller-owned database transactions, then relay committed events at least once. Consumers handle duplicates idempotently.

### Architecture sections implemented

- Product architecture §§53, 55, 58, 62.

### Owned entities

- `DomainEvent` contract and registered event schema/version registry.
- `OutboxEvent` and `ProcessedEvent` persistence models.

### DB schema and indexes

`outbox_events`: `event_id` UUID PK, `event_type`, `event_version`, `aggregate_type`, `aggregate_id`, nullable `workspace_id`, JSONB `payload`, JSONB `metadata` (request/correlation/causation IDs), `occurred_at`, `created_at`, `available_at`, nullable `claimed_until`, `published_at`, `attempts`, nullable sanitized `last_error`. Index pending delivery by `(available_at, created_at)` where `published_at IS NULL`, and an aggregate lookup index. `processed_events`: `(consumer_name, event_id)` composite PK and `processed_at`. Both tables are global infrastructure tables, marked `tenant_scope=global`; workspace ID is event metadata, not table tenancy.

### Public interface

- Register typed, versioned event schemas; serialize/validate without provider or domain-internal coupling.
- `publish(session, event, metadata=...)` adds an outbox row to the caller's transaction and never commits it.
- Relay claims a bounded batch with `FOR UPDATE SKIP LOCKED`, records a lease, and commits before Redis delivery. After successful delivery mark published; failures back off and release/expire the lease. Delivery is at least once.
- Consumer helper atomically claims `(consumer_name,event_id)` with the consumer's DB effect; duplicate deliveries are no-ops.

### OpenAPI endpoints

None.

### Events in/out

Accepts registered versioned domain events from any module. Emits serialized envelopes to the public worker/event stream. The demo registers one simple event. No direct module-internal imports.

### Jobs

Outbox relay is a worker job owned by `jobs_workers`; this module supplies relay operations and does not start worker processes.

### AI tasks used

None.

### Authorization rules

No user authorization. Tenant authorization remains with the domain module. Payloads and metadata must not contain secrets; logs never include raw tokens or credentials.

### Invariants

- Event rows commit or roll back with the originating state change.
- External delivery never occurs while holding the claim transaction open.
- Crashes may produce duplicate delivery, never silent loss of a committed unexpired event.
- Processed-event idempotency is scoped by consumer and event ID.

### Acceptance criteria

- DB-free tests validate envelope versions and safe serialization.
- DB tests prove caller rollback removes the event, concurrent claimers do not claim the same live lease, expired leases can be reclaimed, and duplicate processing is idempotent.
- Relay publishes correlation metadata and retries with bounded backoff.

### Non-goals

Kafka, a general event broker, cross-module table access, exactly-once external delivery, or domain event payload ownership.

## Frontend

to be added by the FE task.

## Public interfaces and events later features must use

- Import public contracts from `app.events_outbox`: `DomainEvent`, `EventEnvelope`, `EventRegistry`, `DEFAULT_EVENT_REGISTRY`, and `DemoPingRequested`; persistence/service imports are `OutboxEvent`, `ProcessedEvent`, `publish`, `claim_batch`, `mark_published`, `mark_delivery_failed`, and `handle_once`.
- `publish(session: AsyncSession, event: DomainEvent, *, metadata: dict[str, str] | None = None, registry: EventRegistry = DEFAULT_EVENT_REGISTRY) -> OutboxEvent` adds to the caller-owned transaction and does not commit. `claim_batch(session: AsyncSession, *, relay_id: str, now: datetime, lease_seconds: int = 60, limit: int = 100, event_ids: list[UUID] | None = None) -> list[OutboxEvent]`; `mark_published(session, *, event_id, relay_id: str, published_at: datetime) -> None`; `mark_delivery_failed(session, *, event_id, relay_id: str, now: datetime, retry_after_seconds: int) -> None`; `handle_once(session: AsyncSession, *, consumer_name: str, event: EventEnvelope, handler: EventHandler, clock: Clock | None = None) -> bool`.
- Event identity is the `(event_type, event_version)` pair. The implemented registered event is `foundation.demo_ping_requested` version `1`; future event types must register a typed schema and increment versions for incompatible contracts. Envelopes carry event/aggregate IDs, optional workspace ID, occurrence time, payload, and string metadata. Sensitive keys are rejected.
- Consumer idempotency is exposed as `handle_once` and keyed by consumer name plus event ID. Delivery is at least once; event and state writes remain in one caller-owned database transaction.
- `apps/api/scripts/demo_ping.py` is an integration client, not an HTTP route or persistence owner. It exercises the real DB/outbox/worker/audit path only in `APP_ENV=dev` or `APP_ENV=test`, uses no in-memory substitute, and verifies correlation without printing credentials.
- OpenAPI endpoints: none. Jobs are relayed by `jobs_workers`; AI tasks: none. Shared errors and pagination use `app.core.ProblemDetails`, `CursorParams`, and `CursorPage[T]`. Environment/setup rules: none specific to this module; database and Redis setup belongs to the owning integration instructions in `app.core` and `jobs_workers`.
