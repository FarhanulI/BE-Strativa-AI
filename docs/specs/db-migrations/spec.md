# Database Migrations Module Specification

## Backend

### Purpose

Own SQLAlchemy 2 async database metadata, explicit pooled/direct engine capabilities, Alembic configuration, migration safety, and database test fixtures. This module does not own domain tables.

### Architecture sections implemented

- Product architecture §§42, 52, 55, 58, 62.

### Owned entities

- SQLAlchemy declarative `Base` and metadata naming convention.
- Alembic version state and schema metadata only. `outbox_events`, `processed_events`, and `audit_log` are owned by their respective modules.

### DB schema and indexes

The initial revision enables `pgcrypto` and `vector` only and inserts no data. Revision `0004_citext` adds reversible `citext` support required by the tenancy foundation; it creates no domain or vector tables. PostgreSQL provides the UUID type and `gen_random_uuid()` without requiring `uuid-ossp`. All tables must set `table.info["tenant_scope"]` to `tenant_scoped` or `global`. Use one naming convention for PK, FK, unique, check, and index constraints. Domain modules provide their own revisions. Use asyncpg and async SQLAlchemy; structurally rewrite PostgreSQL URLs, strip `sslmode`/`channel_binding`, set TLS connect args when requested, set a 30-second connect timeout and `pool_pre_ping=True`. Pooled mode disables both caches through `connect_args.statement_cache_size=0` and `connect_args.prepared_statement_cache_size=0`; do not use session-level `SET`, advisory locks, or `LISTEN/NOTIFY` through the pooled engine. Direct mode is reserved for Alembic/session features.

### Public interface

- `Base`, metadata, tenant-scope constants, pooled/direct async engine factories, and explicit async session factories.
- Migration guard validates `APP_ENV`/`NEON_BRANCH_NAME`; production requires `--allow-prod`.
- DB tests marked `db` use direct URL for one session-scoped migration setup and SAVEPOINT-wrapped rollback transactions. `just test-db` requires test/test selectors.

### OpenAPI endpoints

None. API readiness is owned by `api_contract`.

### Events in/out

None. No event tables or imports from domain event modules.

### Jobs

None.

### AI tasks used

None.

### Authorization rules

No end-user authorization. Never substitute or infer a database branch; do not expose connection URLs. DB-using functions receive sessions explicitly.

### Invariants

- Runtime uses only `DATABASE_URL`; migrations use only `DATABASE_URL_DIRECT`.
- No DB access occurs during import or OpenAPI generation.
- Configured database URLs require the explicitly matching branch selector. Production migration requires an explicit flag.
- Migrations are reversible; production is not run automatically.

### Acceptance criteria

- Unit tests cover URL rewriting/TLS/cache options and migration guard selectors without a database.
- Migration enables both extensions, has no seed data, and passes upgrade/downgrade/upgrade plus `alembic check` on dev and test when credentials are available.
- DB-free metadata test rejects an unclassified table.
- DB fixture fails clearly unless APP_ENV=test and branch=test; applies migrations once and rolls back each test via SAVEPOINT.

### Non-goals

Domain schemas, event/audit tables, data seeding, production migration execution, ORM repositories, and hidden/global session ownership.

### Deviations

- The integration follow-up called for bounded exponential-backoff retries in the database engine's first connection. `build_async_engine` does not retry connection establishment; the readiness checker has a separate bounded retry loop. Ordinary database operations therefore do not receive that first-connect retry behavior.

## Frontend

to be added by the FE task.

## Public interfaces and events later features must use

- Import stable database contracts from `app.db_migrations`: `Base`, `GLOBAL`, `TENANT_SCOPED`, `validate_tenant_scope`, `normalize_postgres_url`, `build_async_engine`, `runtime_engine`, `direct_engine`, `async_session_factory`, and `validate_migration_target`.
- Signatures: `normalize_postgres_url(url: str) -> tuple[str, bool]`; `build_async_engine(url: str | URL, *, pooled: bool, engine_options: Mapping[str, object] | None = None) -> AsyncEngine`; `async_session_factory(engine: AsyncEngine) -> async_sessionmaker`; `runtime_engine(settings: Settings) -> AsyncEngine`; `direct_engine(settings: Settings) -> AsyncEngine`; `validate_migration_target(settings: Settings, *, allow_prod: bool = False) -> str`.
- Runtime/API/worker code uses the pooled `DATABASE_URL`; Alembic and DB test migration setup use `DATABASE_URL_DIRECT` or its validated `DATABASE_URL_UNPOOLED` alias. DB-using functions receive a session or unit of work explicitly. No events, jobs, endpoints, or AI tasks are owned here.
- Migration target rules: configured URLs must match `APP_ENV` and `NEON_BRANCH_NAME` (dev/dev, test/test, prod/production); production additionally requires `allow_prod=True` (`--allow-prod` in the CLI). Never infer branch identity from a label or default-branch status.
- DB test setup: use repository-root `.env.test.local`, explicitly set `APP_ENV=test` and `NEON_BRANCH_NAME=test`, and independently verify the pooled/direct endpoint hosts against Neon branch metadata before destructive operations. Mark DB tests `db`; run session-scoped migrations with the direct URL and each test in a rolled-back SAVEPOINT transaction. DB-free checks must not require a database. See [the Phase 0 verification report](../../reports/phase0-verification.md) for commands and evidence.
- Shared errors and pagination are `app.core.ProblemDetails`, `CursorParams`, and `CursorPage[T]`. Environment-file selection, URL secrecy, and test credentials are owned by `app.core`; no additional setup rules are specified for this module.
