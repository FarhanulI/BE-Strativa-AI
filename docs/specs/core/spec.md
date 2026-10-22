# Core Module Specification

## Backend

### Purpose

Provide the dependency-light shared kernel used by the API, worker, and domain modules: identifiers and entity primitives, validated application configuration, clock abstraction, standard errors, cursor pagination, request context, and a unit-of-work contract. Core defines stable cross-module primitives without owning product-domain behavior or persistence.

### Architecture sections implemented

- Product architecture §5: workspace-centric authorization; client-supplied workspace IDs are not authorization.
- Product architecture §55: modular-monolith boundaries and interfaces that allow future worker extraction.
- Product architecture §58: explicit workspace and profile boundaries, provider independence, and evolution readiness.
- Product architecture §61: identify ownership and preserve domain boundaries for every feature.
- Product architecture §62: prefer simple, deterministic, traceable, testable, modular foundations.

### Owned entities

Core owns non-persistent shared value types and abstractions only:

- UUIDv7 identifier type/factory.
- `Entity`, `AggregateRoot`, `ValueObject`, timestamp mixin, and opt-in soft-delete mixin.
- Typed application settings and configuration errors.
- Domain error hierarchy and RFC 7807 problem-details representation.
- `Clock` interface, system implementation, and controllable fake implementation.
- Shared cursor pagination request/response schemas.
- `RequestContext` and its context-variable access/set/reset contract.
- Unit-of-work protocol/abstraction.

These are not database entities and do not imply tables.

### DB schema and indexes

None. Core owns no tables, migrations, database queries, or indexes. Persistence mapping and session/transaction implementations belong to `db_migrations` or the owning domain module; this module defines only the unit-of-work contract.

### Public interface

Expose stable shared primitives through the `core` package public exports. Consumers must depend on these exports rather than another module's internals.

- Identity/model primitives: UUIDv7 IDs; entity, aggregate-root, value-object, timestamp, and opt-in soft-delete contracts.
- Configuration: Pydantic Settings-backed configuration validated at application startup. `DATABASE_URL`, `DATABASE_URL_DIRECT`, and `REDIS_URL` are optional at this phase. A capability that requires an unset integration raises a clear configuration error at the point it is used. Secret values must never appear in logs or error representations.
- Environment configuration: resolve repository-root environment files independently of CWD; select `.env` plus `.env.local` for dev, `.env` plus `.env.test.local` for test, and no env files for explicitly selected prod. Test/prod require explicit `APP_ENV`. Support the `DATABASE_URL_UNPOOLED` alias for direct connections, reject conflicting aliases without values in diagnostics, and require configured database URLs to match `NEON_BRANCH_NAME` (`dev`, `test`, `production`).
- Errors: `NotFound`, `Conflict`, `ValidationFailed`, `Forbidden`, `Unauthenticated`, `RateLimited`, and `ExternalServiceError`, each with a stable machine-readable code. Provide one RFC 7807 `application/problem+json` representation/handler contract; the API entrypoint installs the global handler.
- Time: all time-dependent core behavior receives a `Clock`; system and fake clocks implement the same interface. Core code must not call `datetime.now()` directly.
- Pagination: one shared cursor request/response schema for collection APIs.
- Request context: immutable context containing `request_id`, optional `user_id`, optional `workspace_id`, and `actor_type` (`user`, `system`, or `worker`), propagated through context variables with explicit set/reset semantics. Provide a placeholder FastAPI dependency. Context is metadata, not proof of authentication or workspace authorization.
- Unit of work: asynchronous protocol for explicit transaction-scoped work. Database-backed functions receive a session or unit of work explicitly; the core abstraction does not construct engines or hide transaction ownership.
- Boundaries: core may be imported by other modules, but must not import domain modules or depend on their persistence, services, or private implementation. Cross-module use is through public interfaces or versioned domain events.

### Local Test Setup and Guard Diagnosis

- Keep test credentials in repository-root `.env.test.local`, with `APP_ENV=test` and `NEON_BRANCH_NAME=test`. Launch verification commands with `APP_ENV=test` explicitly. Keep dev selectors and credentials in `.env.local`; shared `.env` should not contain branch-specific URLs.
- `DATABASE_URL` must be the test branch's pooled endpoint. Use `DATABASE_URL_DIRECT` OR `DATABASE_URL_UNPOOLED` for the same branch's direct endpoint, database, and role. If both aliases are present, their full values must match. Empty aliases are ignored; do not copy production credentials or infer branch identity from the default-branch flag.
- A matching environment/branch label does not prove the URL's Neon branch. Before destructive test migrations, independently compare the configured direct and pooled hostnames with Neon's branch/endpoint metadata.
- Close-out on 2026-10-14 found both local files had URLs but no `APP_ENV` or `NEON_BRANCH_NAME`. The exact failing check was `NEON_BRANCH_NAME must match APP_ENV when a database URL is set`; aliases were not conflicting. Only non-secret selectors were added, and the guard was not weakened.
- The dedicated test branch was independently confirmed as `br-rapid-silence-b3iezotg`, endpoint `ep-jolly-grass-b3wiywq9`, in project `nameless-heart-50634755`; dev uses a separate endpoint. Identifiers document the verification run, not a hard-coded application default.
- A real Redis URL is required for the demo. Verification used a temporary local Redis instance, not an in-memory replacement. See [the Phase 0 verification report](../../reports/phase0-verification.md) for commands and results.

### OpenAPI endpoints

None. Core contributes reusable error and pagination schemas and request-context plumbing; endpoint registration and the `/api/v1` contract belong to `api_contract` and owning modules. `ProblemDetails`, `CursorParams`, and `CursorPage` are importable from `app.core` and included as reusable OpenAPI components even before any collection endpoint is registered.

### Events in/out

None. Core defines no domain events and does not publish or consume events.

### Jobs

None. Core defines no worker jobs and does not enqueue work.

### AI tasks used

None. Core must not select or call AI providers; AI task routing belongs to the AI platform phase.

### Authorization rules

- Core performs no authentication, membership lookup, role evaluation, or resource authorization.
- `RequestContext` carries optional identity and workspace metadata only. A `workspace_id` in a request or context is never sufficient authorization for a workspace resource.
- Future workspace-scoped modules remain responsible for verifying membership and permissions on every request, consistent with product architecture §5.

### Invariants

- IDs generated by the shared factory are UUIDv7.
- Every entity has an identity; aggregate roots are the consistency boundary for their own module; value objects are compared by value.
- Timestamp behavior is injectable through `Clock`; fake-clock tests are deterministic.
- Soft deletion is opt-in and is not silently applied to all entities.
- Configuration validates at startup, permits absent database and Redis settings, and never leaks secret values.
- Environment selection is deterministic from repository-root files; production reads no env files, and configured database URLs never select a branch implicitly.
- Every public error has a stable code and maps to a standards-compliant problem-details response without exposing secrets or internal details.
- Cursor pagination has one shared schema and deterministic ordering requirements; module-specific filtering remains with the owning module.
- Request context is scoped to the current async execution and always reset after use to prevent context leakage between requests or jobs.
- Unit-of-work/session ownership is explicit; core does not use hidden global sessions.
- Dependency direction is inward toward core: core has no imports from domain modules, and consumers use public module contracts rather than internals.

### Acceptance criteria

- Core public exports cover all primitives and abstractions listed above, with Python 3.12-compatible typing.
- UUIDv7 creation and entity/value-object behavior have deterministic unit coverage.
- System and fake clocks share a tested interface, and core time-dependent logic is testable without wall-clock sleeps.
- Settings load and validate without database or Redis variables; missing integration settings produce clear errors only when the corresponding capability is requested.
- Secret values are excluded from settings representations, logs, and problem responses.
- Each required domain error maps to a stable code and RFC 7807 response shape through the single global handler contract.
- Cursor pagination schemas validate inputs and represent continuation consistently.
- Request context set/get/reset and placeholder dependency behavior are tested, including absence of identity/workspace and async context isolation.
- The unit-of-work abstraction is usable by async callers without importing a database implementation into core.
- A boundary rule/test prevents core from depending on domain modules and documents that cross-module imports target public exports only.
- All core tests run without a database, Redis, network access, or Docker.

### Non-goals

- Authentication, authorization policies, workspace membership, or tenant enforcement.
- Database engine/session creation, Alembic, migrations, repositories, or table metadata.
- Outbox/event-bus behavior, job queues, retries, dead-letter storage, or worker lifecycle.
- Logging, tracing, metrics, audit storage, or Sentry integration.
- API route ownership, endpoint registration, OpenAPI export, or frontend code.
- Domain entities, domain services, AI/RAG behavior, provider selection, or product workflows.
- Introducing microservices, Docker, or infrastructure required for tests.

## Frontend

to be added by the FE task.

## Public interfaces and events later features must use

- Import shared contracts from `app.core`: `Settings`, `ConfigurationError`, `AppEnvironment`, `Clock`, `SystemClock`, `FakeClock`, `UUID7`, `UUID7Factory`, `new_uuid7`, entity/value-object types, `RequestContext`, `UnitOfWork`, errors, and cursor schemas.
- Configuration methods: `Settings.require_database_url(*, direct: bool = False) -> str` and `Settings.require_redis_url() -> str`. Context methods: `set_request_context(context) -> Token`, `get_request_context(*, required: bool = False) -> RequestContext | None`, and `reset_request_context(token) -> None`.
- Errors use `ProblemDetails` with `type`, `title`, `status`, `detail`, optional `instance`, and stable `code`; `domain_error_handler` returns `application/problem+json`. Codes/statuses are `unauthenticated`/401, `forbidden`/403, `not_found`/404, `conflict`/409, `validation_failed`/422, `rate_limited`/429, `external_service_error`/502, and `internal_error`/500.
- Pagination schemas are `CursorParams(cursor: str | None = None, limit: int = 20)` with limit 1-100, and `CursorPage[T](items: list[T], next_cursor: str | None = None)`. Filtering belongs to each feature module.
- Events and jobs: none owned by core. AI tasks: none.
- Environment/setup: use repository-root `.env` plus `.env.local` for dev and `.env` plus `.env.test.local` for test; prod reads environment variables only. Set `APP_ENV=test` and `NEON_BRANCH_NAME=test` explicitly for test DB operations. Pair pooled `DATABASE_URL` and direct `DATABASE_URL_DIRECT` (or `DATABASE_URL_UNPOOLED`) with the same branch; aliases must match if both are set. Before destructive test migrations, compare both configured endpoint hosts with Neon branch metadata; branch labels alone do not prove endpoint identity. Keep URLs in ignored local files and never print them. A real `REDIS_URL` is required for worker/demo verification; no in-memory substitute is used. Exact verification commands and results are in [the Phase 0 verification report](../../reports/phase0-verification.md).
- `.env.example` provides blank keys for `APP_ENV`, `NEON_BRANCH_NAME`, `DATABASE_URL`, `DATABASE_URL_DIRECT`, `DATABASE_URL_UNPOOLED`, `REDIS_URL`, and `EMBEDDING_DIM`; keep credentials only in ignored local env files.