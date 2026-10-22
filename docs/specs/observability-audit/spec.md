# Observability and Audit Module Specification

## Backend

### Purpose

Provide structured, secret-safe logs and trace correlation plus an append-only audit trail for security-relevant and business actions. Audit persistence and dependency readiness belong to this module.

### Architecture sections implemented

- Product architecture §§42, 55, 58, 62.

### Owned entities

- `AuditRecord` contract, append service, SQLAlchemy `AuditLog` table, and append-only database protection.
- Structured logging configuration and trace/request correlation middleware helpers.

### DB schema and indexes

`audit_log`: UUID PK, `occurred_at`, nullable `actor_id`, `actor_type`, `action`, `resource_type`, nullable `resource_id`, nullable `workspace_id`, `request_id`, nullable `event_id`, JSONB allowlisted `details`. Global append-only infrastructure table (`tenant_scope=global`) with indexes on `(occurred_at)`, `(workspace_id, occurred_at)`, `(actor_id, occurred_at)`, and `(resource_type, resource_id, occurred_at)`. A PostgreSQL trigger rejects UPDATE and DELETE; inserts are the only supported write.

### Public interface

- `append_audit(session, record)` writes within the caller transaction and does not commit.
- Configure structured JSON logs with request/correlation IDs and trace IDs where available; redact known secret keys and never log request bodies by default.
- Readiness checks required DB/Redis dependencies through bounded checks; this module owns dependency-check helpers, not the HTTP endpoint.

### OpenAPI endpoints

None; `/readyz` is registered by `api_contract`.

### Events in/out

Accepts explicit audit records from module services and worker handlers. Emits no domain events. Audit writes are not performed by importing another module's private internals.

### Jobs

None. Audit insertion is synchronous in the state-change transaction when required by the owning contract.

### AI tasks used

None.

### Authorization rules

No end-user authentication or policy decisions. Audit reads are not exposed as an API in Phase 0. Audit details must be allowlisted and must exclude passwords, tokens, URLs, and other secrets.

### Invariants

- Audit record and corresponding state mutation share a transaction when required.
- Audit rows cannot be modified or deleted by ordinary database roles.
- Logs carry request correlation, avoid sensitive data, and preserve useful error codes without raw exception secrets.

### Acceptance criteria

- DB-free tests prove redaction and structured context propagation.
- DB tests prove audit insert succeeds and UPDATE/DELETE are rejected by the trigger.
- Demo output can verify one correlation ID across API, outbox, worker, and audit without displaying credentials.

### Non-goals

Metrics backend deployment, Sentry provisioning, AI token/cost accounting before AI tasks exist, audit UI/API, or general compliance export/deletion workflows.

## Frontend

to be added by the FE task.

## Public interfaces and events later features must use

- Import `AuditRecord`, `AuditLog`, `append_audit`, `configure_logging`, `redact_sensitive_values`, `check_database`, and `check_redis` from `app.observability_audit`.
- `append_audit(session: AsyncSession, record: AuditRecord) -> AuditLog` participates in the caller's transaction and does not commit. Dependency checks accept `Settings` and return `"ok"`, `"unavailable"`, or `"not_configured"`.
- Audit data is an allowlisted record; rows are append-only. No events, jobs, named event versions, OpenAPI endpoints, or AI tasks are emitted/owned here. Shared errors and pagination use `app.core.ProblemDetails`, `CursorParams`, and `CursorPage[T]`.
- Environment/setup rules: database and Redis URLs are secret settings and must not be logged. Database readiness uses the pooled runtime URL; optional Redis may be unconfigured. No further module-specific setup is specified.
