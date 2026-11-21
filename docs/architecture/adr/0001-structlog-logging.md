# ADR-0001: structlog for structured logging

- **Status:** Proposed
- **Date:** 2026-11-20 (drafted from the code and docs; not a decision by itself)
- **Related:** OBS-AC-1 (redaction and context propagation tests); the rule that no prompts or user content appear in logs.

## Context

Application logging and request-context propagation.

## Decision (as observed or as decided)

`structlog` (`pyproject.toml`: `structlog>=24,<26`) is configured by `app.observability_audit.configure_logging` and used in 12 files under `app/`. A processor redacts sensitive keys recursively (`redact_sensitive_values`).

## Rationale

Not recorded. No document mentions structlog. The observability-audit spec requires structured, redacted, correlated logs (OBS-AC-1) but does not name a library.

## Alternatives considered

Not recorded. The owner supplies the alternatives that were weighed.

## Consequences

Not recorded beyond the observations above. The owner confirms, amends or rejects this record.
