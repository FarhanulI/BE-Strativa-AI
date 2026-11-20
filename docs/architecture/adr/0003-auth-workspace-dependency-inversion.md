# ADR-0003: auth and workspace dependency: inversion at the composition root

- **Status:** Accepted as implemented by T-016 step 2 (commit `7426ceb`, 2026-11-20). Owner review of the result is pending; the owner confirms, amends or rejects this record.
- **Date:** 2026-11-20 (drafted from the code and docs; not a decision by itself)
- **Related:** CORE-INV-11, WS-AC-7, AUTH-AC-2, AUTH-AC-7; task T-016; conformance finding B-1.

## Context

`auth.routes` calls `WorkspaceService.create_workspace_for_owner` (registration) and the workspace public interface (`/me`); `workspace.access`, `.routes` and `.service` use `auth` (`AuthService`, `User`). The cycle is hidden by a lazy import in `app/auth/__init__.py:register_routes`. AUTH-AC-2 requires one transaction; AUTH-AC-7 requires `/me` roles through the workspace public interface.

## Decision (as observed or as decided)

Owner direction, 2026-11-20: dependency inversion at the composition root. `auth` defines protocols that take the caller's session or unit of work; `workspace` implements them; `api_contract` wires them. Registration stays one transaction. Implemented in T-016 step 2: `app/auth/ports.py` defines `WorkspaceProvisioner` and `WorkspaceRoleReader`; `app/auth/routes.py` imports no `app.workspace` name and receives both through `register_routes(app, *, workspace_provisioner, workspace_roles)`; `app.api_contract.create_app` passes `WorkspaceService` and `WorkspaceAccessService`; the lazy import in `app/auth/__init__.py` is gone.

## Rationale

Preserves AUTH-AC-2 and AUTH-AC-7 and removes the cycle without changing the spec. See the corrected finding B-1 in the conformance report.

## Alternatives considered

Considered and rejected: an outbox event or consumer, because it is asynchronous and would break AUTH-AC-2. Not recorded: other options.

## Consequences

- The package import graph is acyclic apart from the Alembic registry file `app/db_migrations/alembic/env.py`, which is exempt by owner decision (ADR-0005), enforced by `tests/unit/architecture/test_package_import_cycles.py`.
- The one remaining direction is `workspace` to `auth` (`AuthService`, `User`).
- Routes and OpenAPI are unchanged (`test_checked_in_openapi_matches_registered_routes` passes).
- New wiring: any new caller of `app.auth.register_routes` must pass the two implementations.
- AUTH-INV-7 names `WorkspaceAccessService.list_workspaces_for_user`; the wired object is that method, so roles are still resolved through it. The owner may read the clause as requiring a direct import, in which case a change proposal is needed.
