| `PATCH /me` | Update the authenticated user's display name; return user and workspaces with roles. |
# Auth and Onboarding Feature Specification

## Backend

### Purpose

Own credential registration and login, short-lived access tokens, rotating refresh sessions, and the registration handoff that creates the user's initial workspace atomically through the workspace public service. Onboarding state is derived from whether the user has a workspace with a ContentProfile; this chunk implements only auth and workspace creation, not profile creation.

### Architecture sections implemented

- Product architecture §§4-5: registration creates a user, workspace, and OWNER membership; resource authorization is resolved from current workspace membership.
- Product architecture §55: modules integrate only through public interfaces or transactional outbox events.
- Product architecture §58 Principle 23: workspace membership is the tenant/collaboration boundary.

### Owned entities

- `User` and `AuthSession`, owned and persisted by `auth`.
- Password credentials and refresh-token session-family state; token material is never persisted in plaintext.

### DB schema and indexes

- `users`: UUIDv7 `id` primary key; case-insensitive, unique `email` (`citext`, normalized to lowercase on write); Argon2id `password_hash`; `display_name`; `is_active`; nullable `email_verified_at` (unused in this chunk); `created_at`; `updated_at`. Unique index on `email`.
- `auth_sessions`: UUIDv7 `id`; `user_id` FK to users; `family_id`; unique `token_hash`; `user_agent`; `ip`; `expires_at`; nullable `revoked_at`; nullable `rotated_to_id`; `created_at`. Indexes on `user_id` and `family_id`, plus unique `token_hash`.
- Auth tables are global identity/session records, not workspace-scoped tables. Use the shared migration metadata and one reversible auth migration.

### Public interface

- `AuthService.get_current_user`: FastAPI dependency that validates the access JWT and resolves the active user and referenced session from the database.
- `AuthService.get_user(user_id)` and `AuthService.find_user_by_email(email)`.
- Registration accepts `email`, `password`, `display_name`, and `workspace_name`; email is trimmed/lowercased and must be a valid address no longer than 320 chars, password is 12-128 chars, display/workspace names are trimmed non-whitespace strings of at most 160 chars. A single DB transaction creates the user, calls `WorkspaceService.create_workspace_for_owner(session, user_id, name)`, and adds `UserRegistered` and `WorkspaceCreated` outbox events.
- Access JWT lifetime is 15 minutes. Its application claims are only `sub` and `sid`; temporal JWT claims required for expiry/validation are not authorization claims. Workspace roles are never embedded in tokens.
- Register, login, and refresh JSON responses use `access_token` for the bearer token and `expires_in: 900` (seconds). The JWT also carries the standard `exp` timestamp; clients should use `expires_in` for response-level expiry handling.
- Configure a stable `AUTH_JWT_SECRET` of at least 32 bytes outside source control; missing or weak secret configuration fails closed when auth is used.
- Refresh credentials are opaque random values; persist only a cryptographic hash. Rotate on every use. The cookie is named `refresh_token`, with `HttpOnly`, `Secure`, `SameSite=Lax`, `Path=/api/v1/auth`, and `Max-Age=2592000` seconds (30 days). `/api/v1/auth/refresh` reads this cookie from the request `Cookie` header, including server-side clients. Return the access token in the JSON body.
- Concurrent refresh requests using the same token have no grace window: the row lock lets one request rotate; the other observes the rotated token, treats it as reuse, and revokes the entire family, including the successor session.
- Login throttling uses a Redis-backed per-normalized-email-and-IP sliding window. Invalid email/password responses are identical; throttle responses use the shared `RateLimited` problem error. This is login-specific abuse protection, not general API rate limiting.

### OpenAPI endpoints

Prefix: `/api/v1/auth`. Errors use the shared RFC 7807 problem schema.

| Method and path | Purpose |
| --- | --- |
| `POST /register` | Create the user and initial OWNER workspace atomically; return access token and user/workspace summary; set refresh cookie. |
| `POST /login` | Verify credentials, record session, return access token; set refresh cookie. |
| `POST /refresh` | Rotate refresh session; return access token and replace cookie. |
| `POST /logout` | Revoke the presented refresh session and clear cookie. |
| `POST /logout-all` | Revoke all active sessions for the authenticated user. |
| `GET /me` | Return authenticated user and workspaces with roles via the workspace public interface. |
| `PATCH /me` | Update the authenticated user's trimmed, non-empty `display_name`; audit the mutation and return the user plus all workspaces with the caller's role. |

### Response and cookie contract

- Register validates `email` length 3-320 and a basic address shape, `password` length 12-128, and `display_name`/`workspace_name` length 1-160 after trimming; names containing only whitespace are rejected. Validation problems use `field_errors: [{field, code, message}]` with non-sensitive generic messages.
- `PATCH /api/v1/auth/me` accepts `{ "display_name": string }`, length 1-160 after trimming. It requires the current access-token session, updates only the caller's display name, appends `auth.display_name_updated` audit metadata without the supplied name, and returns the normal `/me` shape (user plus workspace list and caller roles). It emits no token, password, or other sensitive value.
- Register and login JSON use `access_token` (Bearer JWT), `expires_in` (integer seconds; 900), `token_type` (`Bearer`), `user`, and `workspace` (a single workspace summary or `null`). Register creates one initial OWNER workspace. Login may return `workspace: null` when the user has zero or multiple workspaces. `GET /me` is the authoritative workspace-list response and returns `{user, workspaces: [{id, name, slug, role}]}`; each role is `OWNER`, `ADMIN`, or `MEMBER`.
- Refresh JSON uses `access_token`, `expires_in` (integer seconds; 900), and `token_type` (`Bearer`). The API does not return an absolute access-token expiry timestamp.
- The refresh cookie is named `refresh_token`; attributes are `HttpOnly`, `Secure`, `SameSite=Lax`, `Path=/api/v1/auth`, and `Max-Age=2592000` (30 days). No `Domain` attribute is set. Logout expires this cookie at the same path and with matching security attributes.
- `/api/v1/auth/refresh` reads this cookie from the request's Cookie header. A server-side client must forward it as `Cookie: refresh_token=<opaque value>`; the token is never placed in the request JSON body.
- A refresh credential is single-use. If two requests concurrently present the same credential, the row lock serializes them: one rotates it and the other observes reuse and revokes the entire session family. There is no grace window. The first response's successor is consequently revoked along with the family after reuse is detected.

### Events in/out

- Events in: none.
- Events out: `UserRegistered` containing only user ID; `WorkspaceCreated` is emitted by the workspace service in the registration transaction. No credentials, password hashes, cookies, or token values appear in event payloads.

### Jobs

None.

### AI tasks used

None in Phase 1.

### Authorization rules

- Registration and login are public. `/refresh` uses only the refresh cookie and validates its stored session state. `/logout-all` and both `/me` operations require a valid access token and active session.
- `sub` and `sid` identify the principal/session only; every workspace permission is resolved from the database through the workspace interface on each request.
- Never log passwords or tokens. Audit login success/failure, logout-all, and refresh-token reuse through `observability_audit`; details contain no secrets.

### Invariants

- User, initial workspace, OWNER membership, and registration events commit or roll back together.
- Passwords use Argon2id; refresh tokens are random, single-use, stored hashed, rotated each use, and family-revoked on replay.
- Invalid credentials do not reveal whether an email exists. Inactive users cannot authenticate.
- Auth session validation checks session revocation/expiry in addition to JWT signature and expiry.
- Login audit records distinguish success/failure without recording the submitted password or token. Events and audit payloads are checked against sensitive-key validation.
- Cookie attributes are HttpOnly, Secure, SameSite=Lax, and Path `/api/v1/auth`.
- `/me` GET and PATCH resolve all workspace roles through `WorkspaceAccessService.list_workspaces_for_user`; PATCH never changes workspace membership or emits a token-bearing event.

### Acceptance criteria
- The existing auth endpoint test `tests/db/test_auth_workspace.py::test_auth_me_patch_updates_display_name_audits_and_returns_workspace_roles` covers normalization, validation, audit behavior, workspace roles, and no sensitive audit details for `PATCH /me`.

- Registration creates exactly one user, workspace, and OWNER membership in a single transaction; failures at each operation leave no partial state or outbox event.
- Register/login/refresh return `access_token` and `expires_in=900`; access tokens expire after 15 minutes and carry no workspace role. Session revocation invalidates access tokens.
- A server-side refresh request containing `Cookie: refresh_token=<opaque value>` rotates successfully. Concurrent reuse has no grace window and revokes the family.
- Refresh rotation succeeds once; replaying an old refresh credential revokes the whole family. Expired, revoked, malformed, and unknown refresh credentials fail without leaking token values.
- Login throttling is keyed by normalized email and client IP; a throttled attempt returns 429. Wrong email and wrong password produce the same public response.
- `/me` returns workspace role data through the workspace public interface; PATCH updates and audits `display_name` and returns the same workspace-role shape.
- Register input validation failures use the shared 422 problem response with `field_errors`; the exact shape and correlation extensions are defined once in the API Contract specification.
- Tests verify that passwords and tokens are absent from logs, outbox events, and audit details.

### Non-goals

Email verification, password reset, OAuth/social login, MFA, magic links, general rate limiting (Phase 9), and email delivery (Phase 9 notifications).

### Onboarding

Completed in Chunk 2 (profile). Onboarding is derived state: onboarding is needed when `GET /api/v1/workspaces/{workspace_id}/profiles?limit=1` returns an empty list for a workspace the caller can access. It adds no table and no endpoint; the frontend derives the state from the profile list response.

## Frontend

### BFF session and entry routing

The Next.js frontend exposes same-origin `/api/v1` handlers. Auth handlers consume
`access_token`/`expires_in` and the backend `refresh_token` Set-Cookie server-side;
browser JSON contains only user/workspace data. The frontend owns HttpOnly,
SameSite=Lax `strativa_access` (Path=/, Max-Age=expires_in) and `strativa_refresh`
(Path=/api/v1/auth, Max-Age=2592000) cookies. Secure follows COOKIE_SECURE.
A non-secret HttpOnly `strativa_session` marker at Path=/ allows request
interception to recognize a refresh-only session without widening refresh-cookie scope.
Cookie presence is not authorization. Legacy cookie names are expired.

Silent refresh uses a shared promise and a Web Locks cross-tab lock. A non-secret
localStorage rotation epoch is checked inside the lock so queued tabs do not
replay a rotated token. No tokens are stored in browser storage. Expired sessions
clear the query cache and redirect to `/login?next=<path-and-query>`.

Login/signup preserve safe same-origin next paths, including invitations. The
signup display name is derived from the email local part and the workspace name
is `<display_name>'s Workspace`. Login 401 messages stay generic; throttling and
field validation have separate states. The existing auth layout is retained.

### Derived onboarding wizard

There are no onboarding endpoints or persisted backend wizard state. Entry selects
the validated `last_workspace` membership, otherwise the first membership, and
queries profiles with `limit=1&archived=false`. Zero active profiles re-offers
onboarding; leaving setup is allowed. Members without profile:create see an
explanation instead of forms.

One registry enables basics, type, identity and goals under global `/onboarding/*`
URLs. Audience and brand-voice components remain disabled and have no API hooks.
Logo upload is flag-disabled because no corresponding backend contract exists.
The experience cards now select one of the eight ProfileType values; maturity is
not an input. Identity retains positioning/topics/expertise and removes the
unsupported primary_niche field (the intentional identity-screen visual change).
The required profile name is derived from the basics workspace name, avoiding an
additional identity field. Goals use growth/authority/lead_gen/sales, with
selection-order priorities and each card's default description.

Accessibility correction: the shared muted-text token changes from #64748b to
#607086. Axe found 4.29:1 contrast on the existing muted surface; the adjusted
token measures 4.55:1 and meets AA for small text. This slight color adjustment
is an additional intentional visual difference; layout and typography are unchanged.

Basics patches auth-owned display_name and workspace-owned name. A draft keyed
by user and workspace lives in sessionStorage, survives reload, and is cleared
after one final create-profile POST succeeds. Validation errors return to the
owning step/input. Success navigates to the created profile. Business context is
never an onboarding step. No Phase 3 persistence is enabled.

### Frozen design notes

The existing designed screens are frozen: layout, typography, spacing and copy
change only where listed here. Deviations from the original design:

- **Muted-text token (accessibility, global).** `--color-text-muted` changes from
  `#64748b` to `#607086` in `app/globals.css`. Reason: axe rule `color-contrast`
  (WCAG 2 AA, 4.5:1 for small text) failed on the onboarding screens, because
  `#64748b` on the muted surface `#f3f3f4` measures 4.29:1. Measured with the new
  value: 4.55:1 on `#f3f3f4`, 4.59:1 on `#f4f4f5`, 4.84:1 on `#fafafa`, 5.05:1 on
  `#ffffff`. A single token change was chosen over per-element class changes, so
  it applies to every use of the token, including `/login` and `/signup`, which
  shift by a barely visible amount (no layout change). The Playwright axe checks
  on Basics, Profile type, Identity and Goals pass with it.
- **Wizard content.** `primary_niche` removed; the experience cards are the eight
  profile types; Goals options are growth/authority/lead_gen/sales; Audience and
  Brand Voice screens disabled; logo upload flag-disabled with its section and
  divider collapsed. See "Derived onboarding wizard".
- **Additions.** A muted "Leave setup (your draft is saved)" link above the
  wizard, using the existing secondary link style.

## Public interfaces and events later features must use

- Auth consumers use `AuthService.get_current_user`, `AuthService.get_user(user_id)`, and `AuthService.find_user_by_email(email)`; they must not read auth tables directly.
- Registration calls `WorkspaceService.create_workspace_for_owner(session, user_id, name)` and shares the caller-owned transaction. Consumers needing workspace roles use the workspace public interface; roles are not token claims.
- `UserRegistered` carries only the user ID. `WorkspaceCreated` is owned and emitted by workspace. Both are versioned outbox events committed with their state changes.
- Use shared `ProblemDetails` and core errors. AI tasks: none in Phase 1.