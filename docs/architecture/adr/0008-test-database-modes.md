# ADR-0008: Local container by default, Neon nightly

- **Status:** Proposed
- **Date:** 2026-11-20 (drafted from the code and docs; not a decision by itself)
- **Related:** D-10, DBM-AC-4, SDD-D-2; tasks T-001 and T-013.

## Context

Where database tests run.

## Decision (as observed or as decided)

Tests run on a local Postgres container by default (`TEST_DB_MODE=local`, `APP_ENV=test`, `compose.test-db.yaml`, image `pgvector/pgvector:pg16`) and on the Neon test branch nightly. `README.md` describes the nightly run as planned and not yet defined. SQLite is never a substitute.

## Rationale

D-10 (local mode for the guard) and the standing rules record the policy. Whether the local PostgreSQL major version matches the Neon test branch is not documented (SDD-Q-2).

## Alternatives considered

Not recorded. The owner supplies the alternatives that were weighed.

## Consequences

Not recorded beyond the observations above. The owner confirms, amends or rejects this record.
