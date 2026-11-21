# ADR-0007: Raw SQL for atomic budget operations

- **Status:** Proposed
- **Date:** 2026-11-20 (drafted from the code and docs; not a decision by itself)
- **Related:** INV-32, D-24, D-33, AC-59; conformance finding B-3 (raw SQL is not covered by the boundary test).

## Context

Budget reservation, settlement and refusal must be atomic under concurrency.

## Decision (as observed or as decided)

`app/ai_platform/budget_repository.py` and `request_repository.py` use `text()` SQL (including `IS NOT DISTINCT FROM` and conditional single-statement updates; `budget_service.py` uses `SET TRANSACTION READ ONLY`) instead of ORM updates. The module docstring explains the READ COMMITTED re-evaluation behavior it relies on. Lock order is fixed by INV-32.

## Rationale

Partly: the module docstring and AI Platform spec section 12.3 explain the mechanics. The choice of raw SQL over the ORM is not recorded as a decision.

## Alternatives considered

Not recorded. The owner supplies the alternatives that were weighed.

## Consequences

Not recorded beyond the observations above. The owner confirms, amends or rejects this record.
