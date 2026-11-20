# ADR-0005: Alembic metadata registration imports every module

- **Status:** Proposed
- **Date:** 2026-11-20 (drafted from the code and docs; not a decision by itself)
- **Related:** DBM-AC-2, DBM-AC-3; conformance finding B-5.

## Context

Alembic autogenerate and `alembic check` need every table on one metadata object.

## Decision (as observed or as decided)

`app/db_migrations/alembic/env.py` imports `app.ai_platform`, `app.auth`, `app.events_outbox`, `app.observability_audit`, `app.profile` and `app.workspace` to register their models. A foundation module therefore imports domain modules. The Phase 0 report records that explicit model registration fixed an initially empty autogeneration metadata.

## Rationale

Partly: the Phase 0 report records the fix, not the design choice. The dependency direction is not discussed.

## Alternatives considered

Not recorded. A registry hook that modules call is a possible alternative and has not been evaluated.

## Consequences

Not recorded beyond the observations above. The owner confirms, amends or rejects this record.
