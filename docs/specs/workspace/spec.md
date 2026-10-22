# Workspace Feature Specification

## Backend

### Purpose

Own workspace, membership, invitation, ownership-transfer, and workspace-scoped authorization behavior. Workspace is the collaboration and tenant boundary; all consumers must use its public authorization and listing interfaces rather than workspace tables.

### Architecture sections implemented

- Product architecture §§4-5: membership role is the sole ownership source; client-supplied workspace IDs are not authorization.
- Product architecture §55: cross-module integration uses public interfaces or versioned outbox events.
- Product architecture §58 Principle 23: workspace membership is the tenant/collaboration boundary.

### Owned entities

- `Workspace`, `WorkspaceMember`, and `WorkspaceInvitation`, owned and persisted by `workspace`.
- `WorkspaceContext` and the role-to-permission map are workspace authorization contracts.

### DB schema and indexes

- `workspaces`: UUIDv7 `id` primary key; `name`; unique `slug`; `created_at`; `updated_at`; nullable `deleted_at`. There is no `owner_id`; the OWNER membership is the only ownership source.
- `workspace_members`: UUIDv7 `id`; `workspace_id` and `user_id` foreign keys; role enum `OWNER|ADMIN|MEMBER`; timestamps. Unique `(workspace_id, user_id)` and index `(user_id)`.
- `workspace_invitations`: UUIDv7 `id`; `workspace_id`; normalized `email`; role `ADMIN|MEMBER`; `token_hash`; `invited_by_user_id`; status `pending|accepted|revoked|expired`; `expires_at`; nullable `accepted_at`; `created_at`. Partial unique index on `(workspace_id, lower(email)) WHERE status='pending'`.
- Workspace tables are tenant-scoped; invitation token plaintext is never stored. Use shared migration metadata and one reversible workspace migration.

### Public interface

- `require_workspace_permission(permission)`: dependency factory. Resolve the authenticated user using auth's public dependency, load `(user_id, workspace_id)` membership from the database for every request, and return `WorkspaceContext(user_id, workspace_id, role)`. A non-member receives 404; an insufficiently privileged member receives 403.
- `WorkspaceAccessService.authorize`, `.is_member`, and `.list_workspaces_for_user` are the supported APIs for workspace authorization and membership-backed workspace listings.
- `WorkspaceService.create_workspace_for_owner(session, user_id, name)` creates the workspace and OWNER membership using the caller's session/transaction, then emits `WorkspaceCreated` through the outbox.
- One central role-to-permission map owns the permission matrix. Future modules extend the permission vocabulary there and must authorize through `require_workspace_permission`; they must not implement independent membership checks.
- Initial permissions: `workspace:read|update|delete`, `member:read|invite|update_role|remove`, `ownership:transfer`. OWNER has all. ADMIN has all except workspace delete and ownership transfer, and cannot change/remove OWNERs or other ADMINs. MEMBER has workspace read and member read.
- The registered profile extension adds `profile:read|create|update|archive`: OWNER and ADMIN receive all; MEMBER receives `profile:read` and `profile:update`. Profile routes still use this workspace-owned permission map and dependency.
- Collection endpoints use `CursorParams` and `CursorPage[T]` from core.

### OpenAPI endpoints

Prefix: `/api/v1`. All workspace-scoped endpoints authorize membership on every request and return 404 for non-members. Errors use the shared RFC 7807 problem schema.

| Method and path | Permission or access rule |
| --- | --- |
| `GET /workspaces` | Authenticated; list only caller memberships. |
| `POST /workspaces` | Authenticated; create caller-owned workspace. |
| `GET /workspaces/{workspace_id}` | `workspace:read` |
| `PATCH /workspaces/{workspace_id}` | `workspace:update` |
| `DELETE /workspaces/{workspace_id}` | `workspace:delete`; soft-delete. |
| `GET /workspaces/{workspace_id}/members` | `member:read` |
| `PATCH /workspaces/{workspace_id}/members/{user_id}` | `member:update_role`; role matrix restrictions apply. |
| `DELETE /workspaces/{workspace_id}/members/{user_id}` | `member:remove`; role matrix and last-OWNER protection apply. |
| `POST /workspaces/{workspace_id}/ownership-transfer` | `ownership:transfer`; atomic OWNER swap. |
| `GET /workspaces/{workspace_id}/invitations` | `member:invite` |
| `POST /workspaces/{workspace_id}/invitations` | `member:invite`; returns the invitation token/link once. |
| `DELETE /workspaces/{workspace_id}/invitations/{id}` | `member:invite`; revoke a pending invitation. |
| `GET /invitations/{token}` | Bearer-token preview only; return workspace name, role, expiry. Never log the raw token. |
| `POST /invitations/{token}/accept` | Authenticated email must match invitation email; token is single-use. |

### Events in/out

- Events in: none.
- Events out: `WorkspaceCreated`, `WorkspaceDeleted`, `MemberAdded`, `MemberRoleChanged`, `MemberRemoved`, `InvitationCreated`, `InvitationAccepted`, and `OwnershipTransferred`. Event payloads contain IDs only; role/email/token details remain in workspace-owned persistence and audit records. Events commit in the same transaction as their state changes.

### Jobs

- Workspace owns an idempotent stale-invitation expiration job registered with `jobs_workers`. It marks pending invitations expired when `expires_at` has passed. Job payload contains identifiers/time bounds only; retries are idempotent. The generic worker queue is reused; no scheduler infrastructure is added here.

### AI tasks used

None in Phase 1.

### Authorization rules

- The role-to-permission map is centralized in one workspace-owned file, with a documented extension point for later modules to add permissions.
- Every workspace-scoped route depends on `require_workspace_permission` (or the equivalent authenticated invitation flow). A URL workspace ID is never sufficient authorization.
- Non-members receive 404 to prevent workspace-existence disclosure. Members lacking permission receive 403.
- MEMBER can read workspace and member lists only. ADMIN cannot delete a workspace, transfer ownership, or change/remove OWNERs or ADMINs. Only the explicit transfer operation can promote a new OWNER.
- Invitation preview is token-authorized and returns no membership or credential data. Acceptance requires an authenticated user with a case-insensitive email match.

### Invariants

- Every active workspace has at least one OWNER. Demotion/removal locks the workspace row before counting/checking owners; concurrent operations cannot both remove the final owner.
- Ownership transfer is one transaction: new owner becomes OWNER and previous owner becomes ADMIN.
- Slugs are unique. Soft-deleted workspaces are not exposed as active workspaces.
- Invitation tokens are random, hashed at rest, expire after seven days, and can be accepted only once. Pending invitations are unique per workspace and normalized email.
- All workspace changes and corresponding outbox events share a transaction. All auditable actions append through `observability_audit`; audit rows are never updated/deleted by workspace code.
- No token or password appears in logs, events, audit payloads, or error responses. URL token routes are logged by route template, not raw path.

### Acceptance criteria

- The complete OWNER/ADMIN/MEMBER permission matrix is covered for every workspace endpoint.
- The reusable tenant-isolation harness takes registered workspace-scoped routes and asserts a non-member receives 404 on every route. Chunk 1 registers all workspace-scoped routes; later features add route cases to the same registry when adding endpoints.
- A real Neon TEST-branch concurrency test proves concurrent demotion/removal cannot leave a workspace without an OWNER. Tests and migrations must retain the existing environment guard and never target dev/production.
- Invitation tests cover create, token preview, matching-email accept, wrong-email rejection, expiry, revocation, and token reuse.
- The invitation-expiration worker marks stale pending invitations once; repeated execution is idempotent.
- Workspace events are committed with state changes and sensitive event payload fields are rejected. Audit tests verify append-only use through the public audit interface.
- Architecture tests reject cross-module internal imports; auth/workspace consumers import only public package exports.

### Non-goals

SSO, custom roles, per-resource ACLs, billing seats, and email delivery (Phase 9 notifications).

## Frontend

The frontend workspace shell uses `/auth/me` memberships and a single role-to-
permission map mirroring the backend map. It includes a workspace switcher/create
dialog, logout/logout-all menu, responsive navigation and general/member/
invitation settings. Workspace entry redirects to profiles.

General settings support rename and OWNER-only typed-name deletion. Member
actions are role-aware and confirmed; ownership transfer explicitly states that
the caller becomes ADMIN. Backend last-OWNER errors are surfaced, not replaced
by optimistic success. Invitations offer email/ADMIN-or-MEMBER creation,
copy-once links, cursor listing and revoke confirmation. Public invite previews
preserve next through authentication and acceptance surfaces backend state errors.

**Contract gaps:** MemberResponse contains user_id, role and created_at, not
other members' display names/emails. The current UI identifies those members by
ID. Invitation preview/accept omit workspace_id; the frontend resolves the
newly added membership by comparing `/auth/me` before/after acceptance, falling
back to the entry resolver if no unique membership was added. Supplying
workspace_id would make that redirect unambiguous for every acceptance case.

## Public interfaces and events later features must use

- Every workspace resource route must use `require_workspace_permission(permission)` and receive a DB-verified `WorkspaceContext`; no consumer may authorize from a URL ID alone.
- Use `WorkspaceAccessService.authorize|is_member|list_workspaces_for_user` for access decisions and user workspace listings. Use `WorkspaceService.create_workspace_for_owner` for initial ownership creation.
- Future feature permissions are registered in the centralized role-to-permission map and still resolve through the shared dependency. Future workspace-scoped routes must register with the tenant-isolation harness and test non-member 404 behavior.
- Consumers subscribe to versioned workspace outbox events rather than querying workspace tables. Outbox payloads contain identifiers only where sensitive values could otherwise leak.
- Audit writes go only through `observability_audit.append_audit`; jobs use the public `jobs_workers` queue/registry. Shared errors and pagination use `app.core.ProblemDetails`, `CursorParams`, and `CursorPage[T]`.