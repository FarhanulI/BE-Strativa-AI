# Profile Feature Specification

## Backend

### Purpose

Own the universal `ContentProfile` strategic root, its identity, optional business context and commercial child records, and deterministic profile maturity. Creator and business behavior is represented by profile data, not separate engines. This feature does not own brand, audience, market, or performance intelligence.

### Architecture sections implemented

- Product architecture §3: universal ContentProfile, ProfileIdentity, and optional BusinessContext.
- Product architecture §§23-24: maturity is an input to later adaptive exploration; this feature computes only the stage and does not implement exploration policy.
- Product architecture §55: module boundaries and public-interface integration.
- Product architecture §58 Principles 2, 3, 4, and 24: universal strategy root, shared creator/business engine, optional business context, and profile strategy boundary.

### Owned entities

- `ContentProfile` with profile identity, goal, archive, version, and maturity state.
- Optional `ProfileBusinessContext` plus `ProfileProduct`, `ProfileService`, and `ProfileOffer` child records.
- `ProfileGoal` and profile/business-context request/response schemas.

### DB schema and indexes

- `content_profiles`: UUIDv7 `id`; non-null `workspace_id`; `type` constrained to `creator|business|personal_brand|expert|coach|startup|local_business|ecommerce_brand`; `name`; `positioning`; PostgreSQL `text[]` `topics` and `expertise`; JSONB `goals` array of `{type: growth|authority|lead_gen|sales, priority: int, description: str}`; `maturity_stage` constrained to `cold_start|early_growth|mature`, default `cold_start`; `verified_performance_count` default `0`; optimistic `version` default `1`; nullable `archived_at`; `created_at`; `updated_at`. Unique `(id, workspace_id)` supports composite child references. Indexes `(workspace_id, archived_at)`, `(workspace_id, type)`, and GIN `(topics)`.
- `profile_business_contexts`: `profile_id` primary key, `workspace_id`, JSONB `commercial_objectives`; composite FK `(profile_id, workspace_id)` to `content_profiles(id, workspace_id)`. A row is optional and at most one per profile.
- `profile_products`, `profile_services`, `profile_offers`: UUIDv7 `id`, `workspace_id`, `profile_id`, `name`, `description`, JSONB `metadata`, nullable `archived_at`, `created_at`, and `updated_at`; each has a composite FK `(profile_id, workspace_id)` to the profile and indexes supporting `(workspace_id, profile_id, id)` queries.
- Every profile table is tenant-scoped and includes `workspace_id`. One reversible Alembic migration is owned by this module. Child composite foreign keys prevent cross-workspace links at the database boundary.

### Public interface

- `ProfileService.get(ctx, profile_id)`, `.list(ctx, params, ...)`, and `.get_maturity(ctx, profile_id)` require `WorkspaceContext`; every query filters by both `ctx.workspace_id` and the requested ID.
- `ProfileService.record_verified_performance(ctx, profile_id, delta, idempotency_key)` requires a positive delta and caller-provided UUID idempotency key. It uses `events_outbox.handle_once` with a fixed profile consumer name and the key as `EventEnvelope.event_id`; processed-key, count/stage update, audit, and any maturity event share the caller-owned transaction. No profile-owned idempotency table is added.
- `compute_stage(verified_performance_count, thresholds)` is a deterministic pure function. Defaults: `cold_start` for counts below 5; `early_growth` for counts from 5 through 29; `mature` for counts of 30 or more. Thresholds are configurable and validated.
- The `profile` package exports its public services, role permission registration, typed contracts/events, and `register_routes(app)`. Other modules must not import profile persistence internals.
- Profile mutations use the caller-owned async SQLAlchemy session; the module never commits a transaction itself.

### OpenAPI endpoints

Prefix: `/api/v1/workspaces/{workspace_id}/profiles`. Every route obtains a `WorkspaceContext` using `require_workspace_permission` and scopes profile/item queries by both workspace and entity ID. Collections use `CursorParams`/`CursorPage[T]`; errors use RFC 7807.

| Method and path | Permission | Behavior |
| --- | --- | --- |
| `GET /?cursor=<uuid>&limit=20&archived=false&profile_type=<profile-type>` | `profile:read` | Cursor-paginated list; default limit is 20, cursor is optional, archived defaults to false (active profiles only) and true selects archived profiles; `profile_type` is an optional filter. `limit=1` supports onboarding-state derivation. |
| `POST /` | `profile:create` | Create a profile of any supported type. |
| `GET /{profile_id}` | `profile:read` | Read one active profile in this workspace; the body includes `version` and the response includes an ETag containing that version. |
| `PATCH /{profile_id}` | `profile:update` | Require `If-Match: <version>`; stale versions return 409 `application/problem+json` with `current` server state. Missing header returns 428. |
| `POST /{profile_id}/archive` | `profile:archive` | Soft-archive a profile; requires parent `If-Match`. |
| `POST /{profile_id}/restore` | `profile:archive` | Restore an archived profile; requires parent `If-Match`. |
| `GET /{profile_id}/business-context` | `profile:read` | Return the optional context, or `null` when absent. |
| `PUT /{profile_id}/business-context` | `profile:update` | Create or replace optional context for any profile type; requires parent `If-Match`. |
| `GET/POST /{profile_id}/products` | `profile:read` / `profile:create` | List active products / create a product. POST requires parent `If-Match`. |
| `PATCH/DELETE /{profile_id}/products/{item_id}` | `profile:update` / `profile:archive` | Both require parent `If-Match`; stale versions return 409 with current profile state. DELETE soft-archives. |
| `GET/POST /{profile_id}/services` | `profile:read` / `profile:create` | List active services / create a service. POST requires parent `If-Match`. |
| `PATCH/DELETE /{profile_id}/services/{item_id}` | `profile:update` / `profile:archive` | Both require parent `If-Match`; stale versions return 409 with current profile state. DELETE soft-archives. |
| `GET/POST /{profile_id}/offers` | `profile:read` / `profile:create` | List active offers / create an offer. POST requires parent `If-Match`. |
| `PATCH/DELETE /{profile_id}/offers/{item_id}` | `profile:update` / `profile:archive` | Both require parent `If-Match`; stale versions return 409 with current profile state. DELETE soft-archives. |

### Events in/out

- Events in: none required for this chunk. Verified performance is recorded through the public service with an explicit idempotency key; future consumers can call it from an idempotent outbox handler.
- Events out: `ProfileCreated`, `ProfileUpdated`, `ProfileArchived`, `ProfileRestored`, `BusinessContextUpdated`, and `ProfileMaturityChanged`. Payloads contain IDs only. Each event is written through the outbox in the same transaction as its state change. `ProfileMaturityChanged` is emitted only when the deterministic stage actually changes and only once for a processed idempotency key.

### Jobs

None.

### AI tasks used

None in Phase 1.

### Authorization rules

- Extend the one central role-to-permission map in `workspace.access`; route handlers use `require_workspace_permission` and never implement a second membership check.
- OWNER and ADMIN receive all four profile permissions. MEMBER receives `profile:read` and `profile:update` only.
- `workspace_id` comes from the authorization dependency's `WorkspaceContext`, never from client input alone. A profile or child ID from another workspace resolves to 404.
- Profile and business-context data are workspace-scoped; profile IDs passed to future modules do not authorize access by themselves.

### Invariants

- BusinessContext is optional for every profile type. Creators remain complete without it; adding context later does not require profile-row changes or a schema change.
- This module owns identity, business context, and maturity only. Phase 3 intelligence modules reference `profile_id`; they do not add their columns or tables here.
- All tenant queries include `workspace_id` and entity `id`; all child rows also have composite profile/workspace foreign keys.
- Every mutation of an existing profile (PATCH, archive, restore, business-context PUT, child POST/PATCH/DELETE) is optimistic-concurrency checked against the parent profile version under a row lock. A mismatch never overwrites user edits and returns the current profile state in the conflict response; successful mutations advance the parent version and return its ETag. Profile creation has no existing version and does not require If-Match.
- Archive and child DELETE are soft state changes; profile and child records are never hard-deleted by the API.
- Verified performance count is non-negative and monotonic. A replayed idempotency key causes no count, version, stage, audit, or event change.
- Stage transitions use configured deterministic thresholds. This module does not compute exploration percentages.
- Create/update validation failures return 422 `application/problem+json`; `field_errors`, `request_id`, and `trace_id` use the single shape documented by API Contract. This API does not use 400 for model validation.

### Acceptance criteria

- A profile in workspace A cannot be read, updated, or linked to children through workspace B, including crafted profile/item IDs; cross-workspace child inserts also fail their composite FK.
- Every profile route is registered in the shared tenant-isolation route registry and returns 404 to a non-member.
- OWNER/ADMIN/MEMBER permissions are tested on every profile route, including `profile:*` permissions.
- A creator profile can be created, read, and updated without BusinessContext; context can later be added without changing the profile row.
- A stale `If-Match` returns 409 with current state and leaves the stored user edit/version unchanged; missing `If-Match` is rejected.
- Configured maturity thresholds are tested at boundaries. Transitions emit exactly one `ProfileMaturityChanged`; replaying an idempotency UUID changes nothing.
- The architecture boundary test continues to reject cross-module internal imports.

### Non-goals

Intelligence data, RAG, signals, onboarding AI analysis, social-account import, and exploration percentage calculation.

## Frontend

### Workspace profile screens

`/w/{workspaceId}/profiles` lists name, profile type and server-derived maturity,
with cursor pagination and an explicit archived-only filter. Empty/create states
use the profile feature's public wizard route export. Members can read/update,
but only owners/admins can create/archive/restore.

Profile detail has exactly Identity, Business context and Maturity tabs. Identity
edits name, positioning, topics and expertise. Business context is optional and
available on every profile type, with commercial objectives and product/service/
offer forms. Maturity is read-only and explains verified-performance derivation.
There are no placeholder Phase 3 tabs.

### Concurrency and error handling

Profile PATCH/archive/restore, business-context PUT and child POST/PATCH/DELETE
send the quoted parent profile version in If-Match. Missing headers return 428,
malformed versions return 422, and stale versions return 409 with `current`
including archived state (so restore conflicts can be resolved).
409 `current` opens an explicit conflict dialog; Escape does not discard changes.
Keep re-applies the edited fields against the returned version, while Discard
loads current server state. Unedited identity fields are not resent, avoiding
overwriting unrelated concurrent edits. Problem field errors and request IDs
remain available to forms/error screens. Dirty forms protect link navigation
and browser unload.

All existing-profile writes now enforce expected versions atomically in the
backend service. The same conflict choices cover identity, objectives, child
items, archive and restore. Discarding objectives reloads their separate current
resource, since the conflict body contains the parent profile, not context.
Identity and child-item PATCH bodies contain only fields the user edited, so
re-applying does not overwrite unrelated concurrent changes. Parent-only conflict
responses explicitly label child/context fields whose latest values are absent.

Frozen design notes: the profile screens inherit the shared muted-text token
adjustment (`#64748b` to `#607086`, for axe `color-contrast`) recorded under
"Frozen design notes" in the auth-onboarding spec.

## Public interfaces and events later features must use

- Use `ProfileService.get(ctx, profile_id)`, `.list(ctx, ...)`, `.get_maturity(ctx, profile_id)`, and `.record_verified_performance(ctx, profile_id, delta, idempotency_key)`. The workspace context is required for tenant safety.
- Reuse the workspace permission map/dependency and register future profile-scoped routes in the shared tenant-isolation harness.
- Phase 3+ modules reference profiles through `profile_id` and public profile services/events; they do not query profile tables directly or add brand/audience/market/performance columns to `content_profiles`.
- Consume `ProfileMaturityChanged` by profile ID and read current maturity through the public service. Maturity is input to the experiment module; this feature owns no exploration percentages.
- Use shared core pagination/errors, transactional outbox publication, `observability_audit.append_audit`, and Phase 0 `events_outbox.handle_once` idempotency.