# ADR-0003: auth and workspace dependency: inversion at the composition root

- **Status:** Proposed (direction approved 2026-11-20; Accepted when T-016 completes)
- **Date:** 2026-11-20 (drafted from the code and docs; not a decision by itself)
- **Related:** CORE-INV-11, WS-AC-7, AUTH-AC-2, AUTH-AC-7; task T-016; conformance finding B-1.

## Context

`auth.routes` calls `WorkspaceService.create_workspace_for_owner` (registration) and the workspace public interface (`/me`); `workspace.access`, `.routes` and `.service` use `auth` (`AuthService`, `User`). The cycle is hidden by a lazy import in `app/auth/__init__.py:register_routes`. AUTH-AC-2 requires one transaction; AUTH-AC-7 requires `/me` roles through the workspace public interface.

## Decision (as observed or as decided)

Owner direction, 2026-11-20: dependency inversion at the composition root. `auth` defines protocols that take the caller's session or unit of work; `workspace` implements them; `api_contract` wires them. Registration stays one transaction. Not yet implemented; recorded as Accepted when T-016 completes.

## Rationale

Preserves AUTH-AC-2 and AUTH-AC-7 and removes the cycle without changing the spec. See the corrected finding B-1 in the conformance report.

## Alternatives considered

Considered and rejected: an outbox event or consumer, because it is asynchronous and would break AUTH-AC-2. Not recorded: other options.

## Consequences

Not recorded beyond the observations above. The owner confirms, amends or rejects this record.
