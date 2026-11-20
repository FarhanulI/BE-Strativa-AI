# ADR-0006: mypy strict scope limited to core and ai_platform

- **Status:** Proposed
- **Date:** 2026-11-20 (drafted from the code and docs; not a decision by itself)
- **Related:** Conformance finding E-3. Widening the scope is a separate task.

## Context

Static type checking.

## Decision (as observed or as decided)

`pyproject.toml` sets `strict = true` with `packages = ["app.core", "app.ai_platform"]`. Other modules are not type-checked (for example `register_routes(app)` in `app/auth/__init__.py` has no annotations).

## Rationale

Not recorded.

## Alternatives considered

Not recorded. The owner supplies the alternatives that were weighed.

## Consequences

Not recorded beyond the observations above. The owner confirms, amends or rejects this record.
