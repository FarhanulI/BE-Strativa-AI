# Conformance Report: Phases 0 to 2 (SDD milestone 2, Step 1: audit)

- **Date:** 2026-11-20
- **Branch:** `feat/Ai-platform`
- **Mode:** read-only. No code, spec, test or configuration file was changed. This report is the only file added.
- **Authority:** [product-architecture.md](../product-architecture.md) is canonical. [modules.md](../modules.md) is the module inventory and phase order. Module specs under `docs/specs/` govern module detail. [decisions.md](../decisions.md) and [traceability.md](../traceability.md) are the existing SDD governance layer (SDD-D-1 to SDD-D-4).

## 1. Scope and method

Inspected: all of `app/`, `tests/`, `scripts/`, `pyproject.toml`, `justfile`, Alembic migrations 0001 to 0008, `openapi.json`, `.github/`, `.claude/`, and every file under `docs/`. Tools: static reading, `grep`, `git log`. Import edges were extracted with a regex; the only enforced boundary rule is the AST test in `tests/unit/architecture/test_module_boundaries.py`.

**Not done, and why:**

| Not done | Reason |
| --- | --- |
| Running `ruff`, `mypy`, `pytest` or `alembic check` | Audit is read-only. The DB suite needs the local container and `/run-db-suite`. No test in this report was executed by this audit. |
| Any Neon connection | Neon runs only in an explicitly authorised, separate task (standing rule, SDD-D-2). |
| Reading `.env*` files | Standing rule. Variable names were taken from the checked-in `.env.example` only. |
| The frontend (`../web`) | Outside this repository. `web_foundation` has no spec yet (modules.md). |

Severity scale: **blocker** (must be resolved before the stated work proceeds), **should-fix** (schedule it, work may continue), **note** (record, no action required now).

## 2. Summary

| Area | Blocker | Should-fix | Note |
| --- | --- | --- | --- |
| A. SDD process and governance | 2 | 3 | 2 |
| B. Module boundaries and DB access | 0 | 3 | 4 |
| C. Schema drift | 0 | 2 | 3 |
| D. Missing ADRs | 0 | 1 | 1 |
| E. Test coverage | 0 | 5 | 2 |
| F. AI quality | 1 | 4 | 2 |

No cross-module table query, cross-module internal import, or provider-name leak outside `ai_platform` was found.

## 3. Findings

### A. SDD process and governance

| ID | Severity | Finding | Recommended fix |
| --- | --- | --- | --- |
| A-1 | **blocker** (for Step 2 only) | An SDD layer already exists: `CLAUDE.md` imports `.github/copilot-instructions.md` (standing rules and SDD governance), `docs/decisions.md`, `docs/traceability.md`, `docs/modules.md` (the module map), `docs/specs/<module>/spec.md`, `docs/reports/`, and five empty `.claude/skills/sdd-*` folders. The requested scaffolding (`docs/architecture/module-map.md`, `CLAUDE.md`, a second decisions and open-questions layer) would duplicate or contradict these and create a second source of truth. | Owner decision before any scaffolding. Step 2 therefore proposes **extending** the existing layer and creating only what is genuinely missing. |
| A-2 | **blocker** (for any "Verified" claim) | `docs/traceability.md` has no rows. Under SDD rules 6 and 7, no Phase 0 to 2 requirement is `Verified`. Phase 1 is owner-declared closed (SDD-D-1) but the Workspace criterion "real Neon TEST-branch concurrency test proves no ownerless workspace" has no dated evidence (SDD-D-2). The nearest local test, `tests/db/test_auth_workspace.py::test_concurrent_owner_removals_preserve_one_owner`, runs locally and cannot satisfy that criterion (traceability rule 4). | Populate the matrix per module in an owner-approved milestone. Schedule the separately authorised Neon verification task. |
| A-3 | should-fix | The only dated evidence, `docs/reports/phase0-verification.md`, is dated 2026-10-14. Since then the DB guard changed (local mode, Neon marker, `verify_test_database`) and migrations 0005 to 0008 were added. By traceability rule 9 it cannot verify current behaviour. | Re-run Phase 0 verification under the current guard on the local container and record a new dated report. Neon re-run stays a separate task. |
| A-4 | should-fix | Stable AC/INV IDs exist only in `ai-platform` (61 ACs, INVs). Specs for core, events-outbox, jobs-workers, observability-audit, db-migrations, api-contract, auth-onboarding, workspace and profile use unnumbered bullets. SDD rule 1 ("task references the relevant AC/INV IDs") cannot be satisfied for them. | Change proposal (rule 4) to assign IDs without altering text. Never edit an Approved spec silently. |
| A-5 | should-fix | Specs for `rag` and `context_engine` (Phase 2) do not exist, and `web_foundation` is deferred to the FE task. Phase 2 cannot close without them, and SDD rule 1 blocks implementing them without an approved spec. | Author both specs in the spec step. `rag` must reuse D-23, D-29 and the `ai_platform` public surface. |
| A-6 | note | Spec statuses are not in the required Draft/Approved/Superseded form with revision and approval date (rule 5). The ai-platform header says "approved by owner (rev 4); clarifications recorded (rev 7)", which does not say whether rev 5 to 7 are approved. | Normalise the status line in a change proposal. |
| A-7 | note | D-32 is absent from the AI Platform decision table (already recorded in decisions.md section 6). | Owner to confirm the gap is intentional. |

### B. Module boundaries and cross-module DB access

Edge list (package-level, excluding `core`): `api_contract` composes `auth`, `workspace`, `profile`, `observability_audit`, `db_migrations`; `auth` and `workspace` depend on each other; `profile` and `ai_platform` depend on `workspace`; `workspace`, `profile`, `auth` and `ai_platform` depend on `events_outbox` and `observability_audit`; `jobs_workers` depends on `events_outbox`; `db_migrations/alembic/env.py` imports every module's models.

| ID | Severity | Finding | Recommended fix |
| --- | --- | --- | --- |
| B-1 | should-fix | **auth and workspace form a package-level cycle.** `workspace.access`, `.routes`, `.service` import `app.auth` (`AuthService`, `User`). `auth.routes` imports `app.workspace` (`WorkspaceAccessService`, `WorkspaceService`). It only works because `app/auth/__init__.py:register_routes` imports `app.auth.routes` lazily inside the function. The boundary test does not detect cycles. | Break the cycle through a port: `auth` exposes a post-registration hook or consumes `UserRegistered` via the outbox, and `workspace` owns workspace creation. Until then, add a cycle check to the architecture test and record the lazy import in an ADR. |
| B-2 | should-fix | **Packages export ORM entities** (`app.auth.User`, `AuthSession`, `app.workspace.Workspace`, `WorkspaceMember`, `WorkspaceInvitation`, `app.events_outbox.OutboxEvent`, `ProcessedEvent`, `app.observability_audit.AuditRecord`, `AuditLog`). That is a legal import under the boundary test but allows another module to `select()` a foreign table. Current use is benign: `workspace.access` uses `User` only as a type; `ai_platform.budget_coordinator` uses `OutboxEvent` only as a type; `db_migrations/env.py` imports models to register metadata. | Keep the exports needed for metadata registration in a dedicated registry hook. Add a test that fails when a module builds a query (`select`, `update`, `delete`, `text` with a table name) against an ORM class or table it does not own. |
| B-3 | should-fix | **The boundary test checks import depth only** (`len(parts) > 2`). It does not check import cycles, ORM-entity use, or foreign-table names inside `text()` SQL. Raw SQL exists only in `ai_platform` (`budget_repository.py`, `request_repository.py`) and touches only `ai_*` tables today, with no enforcement. | Extend the architecture tests as in B-2 and add a table-ownership assertion over the SQLAlchemy metadata. |
| B-4 | note | Cross-module foreign keys exist: `workspace_members.user_id` (CASCADE), `workspace_invitations.invited_by_user_id` (RESTRICT), `content_profiles.workspace_id` (CASCADE), `ai_requests.requested_by_user_id -> users` (SET NULL), and `ai_requests`, `ai_usage_records`, `ai_budget_periods -> workspaces` (CASCADE). A foreign key is not a query, and the specs describe the pattern, but the delete policy is not stated in one place. D-17 covers only `ai_*`. | Record a cross-module FK and delete-policy ADR (item 4 in D-2). Review whether cascading a workspace delete into `ai_usage_records` is acceptable for a cost ledger (D-17 accepted it "for now"). |
| B-5 | note | `db_migrations/alembic/env.py` imports `auth`, `workspace`, `profile`, `events_outbox`, `observability_audit` and `ai_platform`. A foundation module depends on domain modules. This is unavoidable for Alembic autogenerate, but it is a documented inversion nowhere. | Document it in the ADR for B-2 (metadata registry). |
| B-6 | note | `workspace/routes.py` runs `select(WorkspaceMember)` and `select(WorkspaceInvitation)` directly in route handlers (lines about 136 and 210) rather than through `WorkspaceService`. Same module, so no boundary violation, but it weakens the layering the spec describes. | Move to the service when the route is next touched. |
| B-7 | note | Positive finding. The one centralised permission map and `require_workspace_permission` are used by workspace and profile routes. A client-supplied `workspace_id` is not trusted. Tenant-isolation route registry covers workspace and profile routes. `ai_platform` has no HTTP routes yet, so no gap there. | None. |

### C. Schema drift against the documented data model

There is no single documented data model. The schema is specified per module (spec sections "DB schema and indexes"). Tables in migrations and ORM: `outbox_events`, `processed_events`, `audit_log`, `users`, `auth_sessions`, `workspaces`, `workspace_members`, `workspace_invitations`, `content_profiles`, `profile_business_contexts`, `profile_products`, `profile_services`, `profile_offers`, `ai_requests`, `ai_usage_records`, `ai_budget_periods`.

| ID | Severity | Finding | Recommended fix |
| --- | --- | --- | --- |
| C-1 | should-fix | **No drift gate runs by default.** The DB suite calls `command.check(config)` (alembic check) in `tests/helpers/database_setup.py`, but `scripts/check.py` runs only `pytest -m "not db"` and there is no CI. ORM versus migration drift is therefore detected only when someone runs the DB suite. This audit did not run it. | Generate `docs/architecture/data-model.md` from SQLAlchemy metadata (not hand-written) and gate it with the drift check in CI. |
| C-2 | should-fix | A hand-written `data-model.md` would become a third copy of the schema (specs, ORM, migrations). | Treat the specs as normative for intent, the generated file as the reference, and fail CI on a stale generated file. |
| C-3 | note | Spot check of `content_profiles` and its four child tables against the profile spec: columns, check constraints, composite FKs `(profile_id, workspace_id)`, and the three named indexes plus GIN on `topics` match. One small difference: item `metadata` has an ORM `default=dict` but no `server_default`, so a raw SQL insert would fail. The spec does not require a server default. | None unless raw inserts are planned. |
| C-4 | note | ai-platform spec section 2 says "Alembic head today is `0007_profile`". The head is `0008_ai_platform`. The spec text is stale, not the code. | Fix in the next spec change proposal. |
| C-5 | note | Architecture section 3 shows `ContentProfile` embedding brand, audience, market and performance intelligence. The profile spec deliberately keeps them out of `content_profiles` (invariant: later modules reference `profile_id`). This is consistent with the module-ownership rule and the product loop, not drift. | Keep recorded as a deliberate reading of section 3. |

pgvector and tsvector: extensions are enabled (0001) and the Phase 0 report shows `vector 0.8.6`, but no vector or tsvector column exists yet, as expected before `rag`.

### D. Missing ADRs for decisions visible in the code

Most of these are written down inside module specs, so the gap is findability and rationale, not absence. There is no ADR directory and no index.

| ID | Severity | Finding | Recommended fix |
| --- | --- | --- | --- |
| D-1 | should-fix | No ADR index exists. Decisions are scattered over 10 specs, `decisions.md` (D-1 to D-35 and SDD-D-1 to SDD-D-4) and the Phase 0 report. | Extend `docs/decisions.md` with a short ADR section or add `docs/architecture/adr/` that points to the spec text, as the register already does. Do not re-decide anything. |
| D-2 | note | Decisions visible in code with no stated rationale or alternatives. Candidates (each needs an owner confirmation, not an invention): (1) structlog as the logging library (no mention in docs); (2) HS256 symmetric JWT with `AUTH_JWT_SECRET` and a 15-minute access token (spec states lifetime and claims, not why symmetric); (3) the lazy import that hides the auth/workspace cycle (B-1); (4) cross-module FK and delete policy (B-4); (5) Alembic metadata registry importing every module (B-5); (6) mypy strict scope limited to `core` and `ai_platform` (E-3); (7) raw SQL with `SET TRANSACTION READ ONLY` and `IS NOT DISTINCT FROM` for budget atomicity; (8) local-container tests by default, Neon nightly (D-10 covers it). Already documented and need only an index entry: UUIDv7 IDs, Argon2 password hashing, refresh-token family rotation, Redis Streams jobs with DLQ, SKIP LOCKED outbox claim, `If-Match` optimistic concurrency, micro-USD integer cost, unit naming instead of "token", RFC 7807 errors, citext. | Record the eight as ADR stubs marked "proposed, needs owner confirmation". |

### E. Test coverage gaps for Phases 0 to 2

There are 705 test functions (581 under `tests/unit`, 124 under `tests/db`; parametrised cases expand at run time). A count is not evidence of conformance (traceability rule 3). There is **no coverage measurement** (`pytest-cov` is not a dependency), so coverage cannot be quantified.

| ID | Severity | Finding | Recommended fix |
| --- | --- | --- | --- |
| E-1 | should-fix | **The default `check` does not run tenant-isolation or RBAC tests.** `scripts/check.py` runs `pytest -m "not db"`; the non-member-404 and role-matrix tests for every workspace and profile route live in `tests/db`. There is no CI workflow (`.github/` contains only instruction files). Nothing automatic enforces the workspace-authorisation rule. | Add CI that runs the local-container DB suite, and run it before every merge. Add the nightly Neon-test-branch job only in an authorised task. |
| E-2 | should-fix | **jobs_workers has no real-Redis tests.** The jobs-workers spec requires Redis integration tests (enqueue, claim, ack, redelivery after consumer failure, DLQ after exhaustion). `tests/unit/jobs_workers/test_queue.py` has 4 tests using `AsyncMock`, and `compose.test-db.yaml` has no Redis. The only real-Redis evidence is the manual `scripts/demo_ping.py` run of 2026-10-14. | Add a Redis service to the test compose file and the integration tests the spec lists. |
| E-3 | should-fix | **Static typing is limited.** `mypy` `strict = true` covers only `app.core` and `app.ai_platform`. Auth, workspace, profile, events_outbox, jobs_workers, observability_audit, api_contract and db_migrations are not type-checked (for example `register_routes(app)` in `app/auth/__init__.py` is unannotated). | Widen `packages` module by module, starting with `events_outbox` and `workspace`, or record the limit as an ADR. |
| E-4 | should-fix | **Events outbox relay and event worker behaviour is untested.** The events-outbox spec requires "relay publishes correlation metadata and retries with bounded backoff" and "expired leases can be reclaimed". I found no test for `relay.py`, `event_worker.py` or `mark_delivery_failed`, and `tests/db/test_outbox_claim.py` has one test (concurrent claim) with no lease-expiry case. The correlation check across API, outbox, worker and audit exists only as the manual demo script. | Add the relay-retry and lease-reclaim tests and an automated correlation test. |
| E-5 | should-fix | **No acceptance-criteria to test mapping.** The matrix is empty (A-2), so it is unknown which spec criteria have no test. Examples that I could not match to a test by search: the observability-audit "one correlation ID across API, outbox, worker and audit"; auth "passwords and tokens absent from logs" (a redaction unit test exists, a full-flow test may too: `test_login_logout_all_audit_and_secret_redaction`, not verified as equivalent). | Fill the matrix (A-2). Mark unmapped criteria `unmapped`, not guessed. |
| E-6 | note | `ai_platform` has the densest coverage (24 unit files, 6 DB files) and arch tests for AC-2, AC-11 and provider isolation. Spec groups 17.5 (async, jobs, retention, authorization, privacy) and 17.6 (real-provider smoke test) cannot be tested yet because the orchestrator, adapter, jobs and routes are not implemented (see F-4). | None now. |
| E-7 | note | `tests/db` tests mutate a shared database and rely on `tests/helpers/audit_teardown.py` because `audit_log` rejects UPDATE/DELETE. Teardown correctness is itself tested (`test_audit_teardown_helper.py`). | None. |

### F. AI quality gaps

Phase 2 status inferred from the code and `git log`: the provider boundary types, `FakeAiProvider`, strict output validator, message builder, Router (selection, failure policy, circuit breaker), catalog, pricing, budget repository and coordinator, usage service and the request repository (steps 3a to 5b-1) exist. **Not present in `app/ai_platform`:** an orchestrator (`run`, `submit`), the embedding service, a real LiteLLM provider adapter, HTTP routes, `execute_request` and other jobs, the cron CLI, and a catalog data file. This is "in progress", not a defect, but it bounds what can be evaluated.

| ID | Severity | Finding | Recommended fix |
| --- | --- | --- | --- |
| F-1 | **blocker** (for the first real-provider call) | **Model identifiers are unverified.** Spec 20.4 records the owner-selected Gemini IDs (standard and high tiers) as "not verified", and the Perplexity embedding facts as verified only for format and identifiers (2026-11-09), with rate limits, LiteLLM decoding and usage field names marked not verified. No catalog data file is committed, so no catalog has been verified against the official documentation. D-27 additionally bars any real user data. | Complete the catalog step with source URL and date per entry, as 20.4 requires. Keep synthetic text only until the privacy review is recorded. |
| F-2 | should-fix | **Prompt versions are not recorded.** `ai_requests` stores `output_schema_name` and `output_schema_version`; `ai_usage_records` stores `provider`, `model`, `catalog_version`, `price_version` and `routing_version`. Neither stores a prompt or instruction version or hash, although D-6 says domain modules own and version prompts. Without it, a quality change cannot be traced to a prompt change, and evals cannot be attributed. | Change proposal for spec 4.1 and 5.1: accept an opaque `instructions_version` from the caller and persist it. Needs owner approval (SDD rule 4); do not edit the Approved spec directly. |
| F-3 | should-fix | **No eval harness or golden sets.** `docs/evals/` does not exist; "AI output evals" are listed only under Phase 9 `delivery`. Strict output-schema validation and AC-60 (catalog fitness) are checks of form and cost, not of output quality. No domain AI task exists yet, so nothing is unprotected today, but the first prompt will land without a quality gate. | Define the eval contract now (dataset format, metrics, pass thresholds, synthetic-data rule, spend budget inside the 20 USD cap), and require it in the `brief` and `signal_synthesizer` specs. |
| F-4 | should-fix | **LiteLLM is not a declared dependency** (absent from `pyproject.toml` and `uv.lock`) although the spec requires provider abstraction through LiteLLM and a boundary architecture test exists. No version is pinned and the spec asks for checks "against the installed LiteLLM version". | Add and pin LiteLLM in the adapter step, with a test that exercises the adapter against `FakeAiProvider` contract tests. |
| F-5 | should-fix | **Latency and cost are recorded but not measured as metrics.** Per-call `latency_ms`, units, and `cost_micro_usd` are stored in `ai_usage_records`, and `catalog.latency_p50_ms` is a static configured value. There is no metrics emission (no OpenTelemetry or Prometheus; observability has structlog and `trace_id` only), no p50 or p95 calculation, no comparison of observed latency to the catalog value, and no alert. The Router's deadline logic (`failure_policy`) trusts the static figure. | Define the required AI metrics (latency percentiles per task and model, cost per task, validation-failure rate, repair rate, fallback rate, budget refusals) in the `observability_audit` spec change, and implement them with the orchestrator. |
| F-6 | note | Positive findings. Provider and model choice sits behind the Router (provider identifiers are confined to `ai_platform` and enforced by architecture tests). Output validation is strict (`extra="forbid"`, frozen models, strict ints). Prompt text and user content are excluded from logs and events by design, and the event envelope rejects keys matching `token|secret|...`. The registry keeps task and capability separate. Cost is integer micro-USD. | None. |
| F-7 | note | The real-provider spend cap (20 USD total, D-11) and the D-27 privacy gate are specified. This audit did not verify whether the cap is enforced in code or only by process, because the code that would enforce it (real-provider test harness) is not in the repository yet. | Verify when the real-provider smoke test (AC in 17.6) is implemented. |

## 4. Recommended order

1. Owner decision on A-1 (extend the existing layer, do not duplicate). Nothing in Step 2 proceeds without it.
2. Spec-level change proposals, in one batch for owner review: A-4 (IDs), A-5 (`rag`, `context_engine` specs), F-2 (prompt version), F-5 (AI metrics), A-6 and C-4 (status and stale text).
3. Verification work that needs no feature code: E-1 (CI), E-2 (Redis tests), E-4 (relay tests), B-1 to B-3 (architecture tests), A-3 (re-run Phase 0 verification locally).
4. Separately authorised: the Neon verification task (A-2).
5. Resume Phase 2 implementation (F-1, F-4, orchestrator, embedding service) only after the owner lifts the SDD-D-3 pause.

## 5. Out of scope and unverified

- Whether `alembic check` is currently clean, and whether the 705 tests pass. Not run.
- Anything about the frontend repository, `../api`, or the log files in the parent directory.
- Security review of auth and workspace beyond what boundary analysis exposed.
