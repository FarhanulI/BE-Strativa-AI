# ADR-0002: HS256 symmetric JWT access tokens

- **Status:** Proposed
- **Date:** 2026-11-20 (drafted from the code and docs; not a decision by itself)
- **Related:** AUTH requirements for token behavior. `AUTH_JWT_SECRET` is a secret and is never printed.

## Context

Access tokens for authenticated API calls.

## Decision (as observed or as decided)

Access tokens are JWTs signed and verified with `HS256` (`app/auth/security.py`), using the secret `AUTH_JWT_SECRET`. The auth spec fixes a 15-minute lifetime and only `sub` and `sid` application claims; workspace roles are never in the token.

## Rationale

Lifetime and claims are specified. Why a symmetric algorithm, and how the secret is rotated, are not recorded.

## Alternatives considered

Not recorded. The owner supplies the alternatives that were weighed.

## Consequences

Not recorded beyond the observations above. The owner confirms, amends or rejects this record.
