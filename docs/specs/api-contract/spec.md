# API Contract Module Specification

## Backend

### Purpose

Own the FastAPI application entrypoint, stable RFC 7807 response contract, OpenAPI generation, request/trace plumbing, and dependency readiness endpoint. Mount feature routes only through each feature package's public registration interface. API schema generation must work without live infrastructure.

### Architecture sections implemented

- Product architecture §§5, 55, 58, 62.

### Owned entities

- FastAPI app factory and ASGI entrypoint.
- Readiness response schema and API-wide dependency wiring.
- Registration of public auth and workspace route sets; route and schema definitions remain owned by those features.
- OpenAPI JSON artifact/generation script. Domain request/response models remain owned by their modules.

### DB schema and indexes

None. Uses the `db_migrations`, `jobs_workers`, and `observability_audit` public interfaces; importing the app or generating OpenAPI must not create a database/Redis connection.

### Public interface

- `create_app(settings, readiness_dependencies=...)` builds the app without connecting to dependencies.
- `GET /readyz` performs bounded PostgreSQL pooled-connection check with cold-start retry and reports Redis independently (`ok`, `error`, or `not_configured`). Do not expose connection details. Return 503 when PostgreSQL is unavailable; optional unconfigured Redis does not fail readiness.
- Install the core `DomainError` -> `application/problem+json` handler and request-context middleware/dependency.
- Canonical RFC 7807 extension fields: `request_id` echoes `X-Request-ID`; optional `trace_id` is the W3C `traceparent` trace ID; validation 422 responses include `field_errors: [{field, code, message}]`. Field errors omit submitted values and use a generic message. Domain errors omit `field_errors`. These extensions are common to auth/profile and other API features; do not invent feature-specific validation error shapes.
- Export deterministic OpenAPI JSON through a script; generated file is refreshed from registered routes, not hand-edited.
- Include `ProblemDetails`, `CursorParams`, and `CursorPage` from core as reusable OpenAPI components without adding placeholder routes. Error responses advertise `application/problem+json`, matching the installed handler.

### OpenAPI endpoints

- `GET /readyz`: typed readiness response, no secrets; status reflects required database readiness. Document the RFC 7807 `ProblemDetails` schema for shared domain errors and a typed readiness response for HTTP 503.
- Auth and workspace endpoints registered from their public feature packages; feature specs own their endpoint contracts.
- No demo endpoint or unrelated health routes in this integration.

### Events in/out

None. Routes/services use public module contracts; API layer publishes no events directly.

### Jobs

None. Worker process entrypoint belongs to `jobs_workers`.

### AI tasks used

None.

### Authorization rules

No auth in Phase 0. Readiness discloses dependency status only, with no URLs, versions, SQL, or credentials.

### Invariants

- Import, app creation, and OpenAPI generation are DB/Redis-free.
- Every request has a generated or propagated request ID; errors follow the shared problem-details schema.
- Readiness timeouts and retries are bounded.

### Acceptance criteria

- OpenAPI generation runs with no DB/Redis configuration and includes readiness plus routes registered through public feature interfaces.
- App-level tests verify success, database unavailable, Redis unavailable/unconfigured, redacted response, and RFC 7807 errors.
- Request ID propagates to logs/context; generated OpenAPI artifact is reproducible.

### Non-goals

Domain route definitions, demo endpoint, frontend client generation, deployment/CI, and automatic production migration.

### Deviations

- The original contract specifies `create_app(settings, readiness_dependencies=...)`. The implementation instead accepts separate `database_check` and `redis_check` callables. This implementation difference is recorded, not silently reconciled.

## Frontend

to be added by the FE task. The FE task will add client generation (`api:generate`, `api:check`) here.

## Public interfaces and events later features must use

- Import `create_app` from `app.api_contract.app`; import `ReadinessResponse` and `DependencyStatus` from `app.api_contract.readiness`.
- API contract imports `register_routes(app)` from each feature's public package. Feature route modules are not imported directly by API contract or other modules.
- Implemented factory signature: `create_app(settings: Settings | None = None, *, database_check: DependencyCheck = check_database, redis_check: DependencyCheck = check_redis) -> FastAPI`, where `DependencyCheck = Callable[[Settings], Awaitable[DependencyStatus]]`.
- `GET /readyz` returns `ReadinessResponse(status: "ready" | "not_ready", database: "ok" | "unavailable" | "not_configured", redis: "ok" | "unavailable" | "not_configured")`; an unavailable database yields HTTP 503. Readiness is not authentication.
- Shared errors use `app.core.ProblemDetails` and `application/problem+json`; cursor schemas are `app.core.CursorParams` and `app.core.CursorPage[T]`. Error codes/statuses: `unauthenticated`/401, `forbidden`/403, `not_found`/404, `conflict`/409, `validation_failed`/422, `rate_limited`/429, `external_service_error`/502, and `internal_error`/500.
- Validation and correlation extensions follow the canonical RFC 7807 contract documented in the Public interface section above.
- Events: none. AI tasks: none. Environment/setup rules: API import, app construction, and OpenAPI generation require no database or Redis configuration. No additional API-specific setup is specified.
