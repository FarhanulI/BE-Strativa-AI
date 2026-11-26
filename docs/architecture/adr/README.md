# Architecture Decision Records

ADRs record the rationale and alternatives for decisions that are visible in the code. They sit beside, and never replace, the existing records:

- [decisions.md](../../decisions.md) is the register of `D-n` (AI Platform history) and `SDD-D-n` (SDD governance). Those IDs are not re-decided or copied here; an ADR links to them.
- Module specs under `docs/specs/` remain normative for requirements.
- Product architecture and the module map keep their authority ([sdd.md](../../sdd.md) section 1). An ADR never overrides them.

## Rules

- ID format: `ADR-nnnn`, files `NNNN-<slug>.md`. IDs are never reused or renumbered.
- Status: Proposed, Accepted, Superseded. **Every ADR below is Proposed.** The code shows what was chosen; the rationale and the alternatives are not recorded anywhere, so they are marked "Not recorded" and the owner confirms or supplies them. Nothing in a Proposed ADR is a decision.
- An ADR is result-reviewed by the owner before it becomes Accepted (a gate in [T-012](../../tasks/T-012-sdd-process-amendment.md) once approved).
- Do not invent rationale. Use "Not recorded".

## Template

```markdown
# ADR-nnnn: Title
- **Status:** Proposed | Accepted | Superseded by ADR-nnnn
- **Date:**
- **Related:** requirement IDs, D-n or SDD-D-n, tasks
## Context
## Decision (as observed or as decided)
## Rationale
## Alternatives considered
## Consequences
```

## Index

| ADR | Title | Status |
| --- | --- | --- |
| [0001](0001-structlog-logging.md) | structlog for structured logging | Proposed |
| [0002](0002-hs256-access-tokens.md) | HS256 symmetric JWT access tokens | Proposed |
| [0003](0003-auth-workspace-dependency-inversion.md) | auth and workspace dependency: inversion at the composition root | Proposed (direction approved by the owner 2026-11-20; Accepted when T-016 completes) |
| [0004](0004-cross-module-foreign-keys-and-delete-policy.md) | Cross-module foreign keys and delete policy | Proposed |
| [0005](0005-alembic-metadata-registry.md) | Alembic metadata registration imports every module | Proposed |
| [0006](0006-mypy-strict-scope.md) | mypy strict scope limited to core and ai_platform | Proposed |
| [0007](0007-raw-sql-for-budget-atomicity.md) | Raw SQL for atomic budget operations | Proposed |
| [0008](0008-test-database-modes.md) | Local container by default, Neon nightly | Proposed |

Decisions already written in specs and needing only an index pointer here (no ADR stub): UUIDv7 identifiers, Argon2 password hashing, refresh-token family rotation, Redis Streams jobs with a dead-letter stream, `SKIP LOCKED` outbox claims, `If-Match` optimistic concurrency, integer micro-USD cost, "units" instead of "token" in names, RFC 7807 problem responses, `citext`. Find them in the specs listed in [modules.md](../../modules.md).
