# AI Platform Module Specification

Status: reviewed; decisions applied (rev 2); awaiting final owner approval. Authored 2026-11-01 from `docs/product-architecture.md` and `docs/modules.md` (the sources of truth) and from the real Phase 0/1 code. Revised 2026-11-02 to apply the owner's decisions (section 20) and the review fixes, and revised again (rev 2) to apply the owner's delta decisions: 30-day retention, cron-triggered jobs, Gemini-only chat with billing modes, lease fencing, budget reconciliation, error classification, config-driven budget limits and the sync request lifecycle. It is a new specification, not a restoration of any earlier `ai_platform` spec.

Items marked **(provisional — OQ-n)** use a working value so that the spec stays testable. The value is not a decision. See section 19. Acceptance criteria that depend on a provisional value say so. Section 20 lists the decided items and the one prerequisite task (P-2).

## Backend

## 1. Purpose

`ai_platform` is the only module that talks to AI providers. Business modules request an **AI task** by name. `ai_platform` turns the request into one or more provider calls and returns output that is validated against a registered schema. It enforces and records cost, and it never lets a business module choose a provider or model.

It provides:

- the AI Orchestrator (task execution, sync and async),
- the AI Router (provider/model selection, fallback),
- provider abstraction through LiteLLM (Gemini for chat, OpenAI only for text embeddings),
- the task registry and the capability model (task ≠ capability),
- strict output-schema enforcement,
- cost metering and budget enforcement (a per-workspace budget and a separate system budget),
- the text embedding service used by `rag`,
- multimodal-ready interfaces.

It does not build context (that is `context_engine`), retrieve knowledge (`rag`), own domain output schemas or domain prompts, or bill anyone.

## 2. Architecture references

| Source | Section | What this spec takes from it |
| --- | --- | --- |
| `product-architecture.md` | §44 AI Architecture | AI is infrastructure. Chain is Business service → AI Orchestrator → AI Router → AI Provider → Model. Business services request a task and never name Gemini/OpenAI/Claude. Router selects on complexity, quality, latency, cost, modality, availability. The eight example tasks form the registry (section 9). |
| | §45 AI Task ≠ AI Capability | The registry keeps tasks and capabilities as separate concepts. Each task declares capabilities (sections 5, 9). |
| | §46 Context Engine | `ai_platform` receives already-built context and does not assemble it (see "Context-engine boundary" below). |
| | §47 Multimodal Architecture | Text, image, video, audio and multimodal shapes exist in the interfaces. No multimodal complexity is pushed into domain modules (section 13). |
| | §53 Asynchronous Processing | AI-heavy work runs in background workers: persist canonical data, emit event / queue job, worker processes, persist result (sections 7, 8). |
| | §54 Asynchronous Embedding Pipeline | `ai_platform` supplies the embedding call and the `embedding_model` / `embedding_version` values that `rag` stores (section 5). |
| | §55 Modular Monolith Boundaries | `ai_platform` is a listed module. Interaction is through public service interfaces and outbox events only. No cross-module table queries or deep imports. |
| | §58 Principle 22 | AI provider selection belongs to the AI Router, not business logic. |
| | §61 item 15 | "Is the AI provider abstracted behind the AI Router?" The answer must always be yes (invariants INV-1 to INV-4). |
| | Supporting: §5, §37, §58 P23, §62 | Workspace-centric authorization; GLOBAL vs tenant knowledge (why a system scope exists); workspace as tenant boundary; the simple/deterministic/traceable/testable preference. |
| `modules.md` | Phase 2 `ai_platform` line | "AI Orchestrator, AI Router, provider abstraction (LiteLLM), task vs capability registry, strict output-schema enforcement, token cost accounting, multimodal-ready interfaces". |
| `modules.md` | Module rules | A spec must include the sections listed in this document. Modules communicate only through public interfaces or outbox events. |
| `modules.md` | Phase 0 `observability_audit` line | AI usage and cost tracking is listed there. The `observability_audit` spec defers "AI token/cost accounting before AI tasks exist". This module therefore owns the ledger and uses `observability_audit` for logs and audit. |

### Context-engine boundary (§46)

- `ai_platform` accepts a caller-built list of `AiContextBlock` values. Each block has text and an optional opaque `source_id` for lineage.
- `ai_platform` never queries `rag`, never reads profile or intelligence data, and never decides what context is relevant.
- Token budgeting of the context belongs to `context_engine`. `ai_platform` only rejects a request whose estimated input does not fit any eligible model, with `ai_input_too_large`. It does not trim or summarize input.
- Context text is **untrusted data** (section 11.1).

### Real interfaces this spec relies on

| Concern | Real interface (Phase 0/1 code) |
| --- | --- |
| IDs | `app.core.UUID7`, `UUID7Factory(clock).new()`, `new_uuid7(now)` |
| Time | `app.core.Clock`, `SystemClock`, `FakeClock` (`advance`, `set`). No direct `datetime.now()`. |
| Errors | `app.core.DomainError` and subclasses `NotFound` (404), `Conflict` (409), `ValidationFailed` (422), `Forbidden` (403), `RateLimited` (429), `ExternalServiceError` (502); `ConfigurationError` (maps to 503 `service_unavailable`); `ProblemDetails`. |
| Pagination | `CursorParams`, `CursorPage[T]`. |
| Request context | `RequestContext(request_id, user_id, workspace_id, actor_type: user\|system\|worker)`, `get_request_context`. |
| Config | `Settings` (`embedding_dim: int \| None`, `redis_url`, secrets as `SecretStr`); `Settings` has `extra="ignore"`. |
| DB | `app.db_migrations.Base`, `TENANT_SCOPED`, `GLOBAL`, `async_session_factory`, `database_session`; naming convention `ix_/uq_/ck_/fk_/pk_`; every table sets `info["tenant_scope"]`; Alembic head today is `0007_profile`. |
| Outbox | `app.events_outbox`: `DomainEvent` (`event_type`, `event_version`, `aggregate_type`, `aggregate_id`, `workspace_id`, `occurred_at`; `extra="forbid"`), `DEFAULT_EVENT_REGISTRY.register`, `publish(session, event, metadata=...)`, `EventEnvelope`, `handle_once(session, consumer_name=, event=, handler=)`. The envelope validator rejects payload/metadata keys matching `password\|token\|secret\|authorization\|credential\|api[_-]?key\|private[_-]?key`. |
| Jobs | `app.jobs_workers`: `JobEnvelope(job_id, job_type, job_version, payload, metadata, attempt)`, `JobRegistry.register(type, version, handler)`, `JobQueue(redis, stream="jobs", dead_letter_stream="jobs:dead", max_attempts=5)`, `JobQueue.enqueue`, `EventWorker`, `OutboxRelay`. Retry backoff is `min(300, 2**attempt)` s. There is no scheduler today and none is added: periodic jobs are triggered by an external cron through the `app.ai_platform.cron` CLI (8.5, D-2). |
| Audit/logs | `app.observability_audit`: `AuditRecord`, `append_audit(session, record)` (caller transaction, no commit), `configure_logging`, `redact_sensitive_values`, `check_database`/`check_redis` (status-string helpers). `AuditRecord.details` rejects the same sensitive-key family, and the log redactor replaces such keys with `[REDACTED]`. |
| RBAC | `app.workspace`: `WorkspaceContext(user_id, workspace_id, role)`, `WorkspaceRole`, `WorkspacePermission`, `ROLE_PERMISSIONS` (the single extension point), `WorkspaceAccessService.authorize`, `require_workspace_permission`. Non-member gets 404, member lacking permission gets 403. |
| API | `app.api_contract.app.create_app`; features expose `register_routes(app)`; routes live under `/api/v1/workspaces/{workspace_id}/...`; tenant-isolation harness `tests/helpers/tenant_isolation.py` (`WORKSPACE_SCOPED_ROUTES`). |
| Boundary test | `tests/unit/architecture/test_module_boundaries.py` rejects any import of `app.<other_module>.<submodule>`. Only package-root exports can be used across modules. |

**Consequence of the key-name regex.** Provider "tokens" are the billing unit of LLM providers, but the word `token` is rejected in event payload keys and audit details and is redacted in logs. This spec therefore calls them **units**. `input_units` and `output_units` are used in DB columns, events, logs, audit details, API fields and Python names. The provider adapter is the only place that maps provider usage fields onto these names.

## 3. Owned entities

- `AiRequest`: one logical request to run an AI task (sync or async). It is the unit of idempotency (async only) and of lease/heartbeat.
- `AiUsageRecord`: one row per provider call attempt (generation, repair, embedding). It is the cost ledger and carries the routing record.
- `AiBudgetPeriod`: per-scope, per-month budget counters (spent, reserved, limit, notification flags). Scopes are `workspace` and `system`. The two scopes are separate budgets (D-1).
- Non-persistent contracts:
  - `AiTaskDefinition`, `AiTaskRegistry`, `AiCapability`, `AiModality`, and the quality/latency/cost classes.
  - `OutputSchemaRegistry`.
  - `ModelCatalog` (in-repo versioned data: models, capabilities, modalities, quality tier, context window, price per unit, latency estimate, billing mode).
  - `AiRouter`, `AiOrchestrator`, `EmbeddingService`, `ProviderClient` (internal).
  - `AiCallContext`, `AiTaskRequest`, `AiTaskResult`.
  - `AiPlatformConfig` (environment-driven budget limits and retention, 5.5, 12.3).
  - `FakeAiProvider` (test support, exported from the package root).

`ai_platform` owns no vector tables. `rag` stores embeddings in its own tables.

## 4. DB schema and indexes

One reversible Alembic revision `0008_ai_platform` (`down_revision = "0007_profile"`). Conventions follow `db_migrations`: UUIDv7 primary keys generated through `UUID7Factory`; `timestamptz` everywhere; `info["tenant_scope"]` set on every table; explicit index names `ix_<table>_<columns>` / `uq_<table>_<columns>`; check constraints named per the naming convention; all money is stored as **integer micro-USD** (`bigint`, 1 USD = 1,000,000) so there is no floating-point drift.

All three tables are `tenant_scoped`. `workspace_id` is nullable only for `scope = 'system'` rows. These are platform-level calls with no workspace, for example embedding GLOBAL knowledge (§37). A check constraint ties the two together. Workspace-facing queries always filter `workspace_id = ctx.workspace_id`, so system rows are never visible to them.

### 4.1 `ai_requests`

| Column | Type | Notes |
| --- | --- | --- |
| `id` | uuid PK | UUIDv7 |
| `scope` | text not null | `workspace` \| `system` |
| `workspace_id` | uuid null | FK `workspaces.id` ON DELETE CASCADE (same pattern as `content_profiles`) |
| `requested_by_user_id` | uuid null | FK `users.id` ON DELETE SET NULL; null for system/worker |
| `actor_type` | text not null | `user` \| `system` \| `worker` |
| `task` | text not null | registry task name |
| `output_schema_name` | text null | null only for `EMBED_TEXT` |
| `output_schema_version` | int null | null only for `EMBED_TEXT` |
| `mode` | text not null | `sync` \| `async` |
| `status` | text not null | `queued` \| `running` \| `succeeded` \| `failed`. `queued` is used by async requests only. Sync requests are created `running` (4.5). |
| `idempotency_key` | uuid null | caller-supplied on `submit`; present exactly when `mode = 'async'`. Sync requests (`run`, `embed_texts`) have no idempotency key (F-1). |
| `request_fingerprint` | char(64) null | SHA-256 over the canonical request; present exactly when `mode = 'async'`. The same key with a different fingerprint is a `Conflict`. |
| `input_payload` | jsonb null | present only for `async` (the worker needs it). **Content.** Never logged, evented or put in errors. Nulled by the purge job (8.3). |
| `output_payload` | jsonb null | validated output; present for `async`, and for `sync` only when `persist_result=True`. **Content.** Nulled by the purge job (8.3). |
| `content_purged_at` | timestamptz null | set by `ai_platform.purge_expired_content` (8.3) |
| `error_code` | text null | one of the fixed codes in 5.4 |
| `attempt_count` | int not null default 0 | job executions started |
| `lease_epoch` | int not null default 0 | lease fencing counter. Every successful claim increments it and the claiming worker keeps the value it received (8.1). Async only; stays 0 for sync requests. |
| `lease_owner` | text null | worker identity |
| `lease_expires_at` | timestamptz null | |
| `heartbeat_at` | timestamptz null | |
| `routing_version` | text null | router rules version used |
| `input_units` | bigint not null default 0 | sum over settled calls |
| `output_units` | bigint not null default 0 | |
| `cost_micro_usd` | bigint not null default 0 | |
| `correlation_request_id` | text not null | from `RequestContext.request_id` (jobs propagate it in metadata) |
| `queued_at`, `started_at`, `completed_at` | timestamptz null | |
| `created_at`, `updated_at` | timestamptz not null | |

Constraints:

- `ck_ai_requests_scope`: `scope IN ('workspace','system')`.
- `ck_ai_requests_scope_workspace`: `(scope = 'workspace') = (workspace_id IS NOT NULL)`.
- `ck_ai_requests_status`, `ck_ai_requests_mode`, `ck_ai_requests_actor_type`: value lists.
- `ck_ai_requests_nonneg`: `input_units >= 0 AND output_units >= 0 AND cost_micro_usd >= 0 AND attempt_count >= 0 AND lease_epoch >= 0`.
- `ck_ai_requests_async_key`: `(mode = 'async') = (idempotency_key IS NOT NULL)`.
- `ck_ai_requests_async_fingerprint`: `(mode = 'async') = (request_fingerprint IS NOT NULL)`.
- `ck_ai_requests_schema_name`: `task = 'EMBED_TEXT' OR (output_schema_name IS NOT NULL AND output_schema_version IS NOT NULL)`.
- `ck_ai_requests_running_lease`: `mode <> 'async' OR status <> 'running' OR (lease_owner IS NOT NULL AND lease_expires_at IS NOT NULL)`. Sync requests hold no lease.
- `ck_ai_requests_sync_no_lease`: `mode = 'async' OR (lease_owner IS NULL AND lease_expires_at IS NULL AND lease_epoch = 0)`.
- `ck_ai_requests_terminal_completed`: `status NOT IN ('succeeded','failed') OR completed_at IS NOT NULL`.
- `ck_ai_requests_purged`: `content_purged_at IS NULL OR (input_payload IS NULL AND output_payload IS NULL)`.

Indexes:

- `uq_ai_requests_workspace_idempotency`: unique `(workspace_id, idempotency_key)` WHERE `idempotency_key IS NOT NULL AND workspace_id IS NOT NULL`.
- `uq_ai_requests_system_idempotency`: unique `(idempotency_key)` WHERE `scope = 'system' AND idempotency_key IS NOT NULL`.
- `ix_ai_requests_workspace_id_id`: `(workspace_id, id)`, for cursor listing in UUIDv7 order.
- `ix_ai_requests_running_lease`: `(lease_expires_at)` WHERE `status = 'running' AND mode = 'async'` (reaper).
- `ix_ai_requests_sync_running`: `(started_at)` WHERE `status = 'running' AND mode = 'sync'` (reaper, 8.2).
- `ix_ai_requests_queued_at`: `(queued_at)` WHERE `status = 'queued'` (reaper).
- `ix_ai_requests_purge_candidates`: `(completed_at)` WHERE `content_purged_at IS NULL AND status IN ('succeeded','failed') AND (input_payload IS NOT NULL OR output_payload IS NOT NULL)` (purge job).

### 4.2 `ai_usage_records`

| Column | Type | Notes |
| --- | --- | --- |
| `id` | uuid PK | UUIDv7 |
| `request_id` | uuid not null | FK `ai_requests.id` ON DELETE CASCADE |
| `attempt_no` | int not null | 1-based sequence of calls within the request |
| `scope`, `workspace_id` | as in 4.1 | denormalized for aggregation. Same check constraint. |
| `task` | text not null | |
| `call_kind` | text not null | `generation` \| `repair` \| `embedding` |
| `provider` | text not null | catalog provider id |
| `model` | text not null | catalog model id |
| `catalog_version` | text not null | |
| `price_version` | text not null | |
| `billing_mode` | text not null | `free_tier` \| `paid`, copied from the catalog entry used (10.1). All calls of one request have the same value (INV-29). |
| `routing_version` | text not null | |
| `route_rank` | int not null | 1 = the Router's first choice |
| `candidate_snapshot` | jsonb not null | ordered list of `{model, eligible, reason_code}` (ids and codes only, no content) |
| `status` | text not null | `reserved` \| `succeeded` \| `failed` \| `abandoned` |
| `error_code` | text null | |
| `finish_reason` | text null | `stop` \| `length` \| `content_filter` \| other provider value |
| `input_units`, `output_units` | bigint null | null until settled |
| `reserved_micro_usd` | bigint not null | amount reserved against the call's one budget row |
| `cost_micro_usd` | bigint not null default 0 | settled actual cost |
| `schema_valid` | boolean null | null for `embedding` and for calls that did not reach validation |
| `validation_error_count` | int null | |
| `validation_error_types` | jsonb null | Pydantic error type names only (for example `missing`), never values or text |
| `latency_ms` | int null | |
| `period_start` | date not null | first day of the UTC month of `started_at` |
| `started_at` | timestamptz not null | |
| `finished_at` | timestamptz null | |
| `created_at` | timestamptz not null | |

Constraints:

- `uq_ai_usage_records_request_attempt`: unique `(request_id, attempt_no)`.
- `ck_ai_usage_records_scope_workspace`: same rule as 4.1.
- `ck_ai_usage_records_status`, `ck_ai_usage_records_call_kind`, `ck_ai_usage_records_billing_mode`: value lists.
- `ck_ai_usage_records_nonneg`: `reserved_micro_usd >= 0 AND cost_micro_usd >= 0 AND COALESCE(input_units,0) >= 0 AND COALESCE(output_units,0) >= 0`.
- `ck_ai_usage_records_settled`: `status = 'reserved' OR finished_at IS NOT NULL`.

Indexes:

- `ix_ai_usage_records_workspace_started`: `(workspace_id, started_at)`, for the workspace usage view.
- `ix_ai_usage_records_scope_started`: `(scope, started_at)` WHERE `scope = 'system'`.
- `ix_ai_usage_records_reserved`: `(started_at)` WHERE `status = 'reserved'` (reaper).

### 4.3 `ai_budget_periods`

| Column | Type | Notes |
| --- | --- | --- |
| `id` | uuid PK | UUIDv7 |
| `scope` | text not null | `workspace` \| `system` |
| `workspace_id` | uuid null | same rule and FK as 4.1 |
| `period_start` | date not null | first day of the UTC calendar month (D-3) |
| `limit_micro_usd` | bigint not null | the configured limit last seen by a reservation, refusal or settlement on this row, kept for display and history. It is **not** the enforcement value: every reservation receives the current configured limit as a parameter (12.3, D-9). Defaults 25,000,000 (workspace) and 100,000,000 (system). |
| `reserved_micro_usd` | bigint not null default 0 | in-flight worst-case estimates |
| `spent_micro_usd` | bigint not null default 0 | settled actual cost |
| `warning_notified_at` | timestamptz null | set once when settled `spent` first reaches 80 % of `limit` |
| `exhausted_notified_at` | timestamptz null | set once, at the first refusal for this row in this period |
| `reconcile_mismatch_bucket` | timestamptz null | UTC hour bucket of the last reconciliation run that reported a mismatch for this row (8.4). It only makes the mismatch report idempotent per bucket. |
| `created_at`, `updated_at` | timestamptz not null | |

Constraints:

- `ck_ai_budget_periods_scope_workspace`: same rule as 4.1.
- `ck_ai_budget_periods_nonneg`: `limit_micro_usd >= 0 AND reserved_micro_usd >= 0 AND spent_micro_usd >= 0`.

Indexes:

- `uq_ai_budget_periods_workspace_period`: unique `(workspace_id, period_start)` WHERE `scope = 'workspace'`.
- `uq_ai_budget_periods_system_period`: unique `(period_start)` WHERE `scope = 'system'`.

Rows are created lazily with `INSERT ... ON CONFLICT DO NOTHING` followed by the conditional update in 12.3. A new UTC month gets new rows with zero counters. There is no carry-over (D-3).

### 4.4 Not stored

- No prompt/completion text on `ai_usage_records`, and none on `ai_requests` except the content columns in 4.1, which are purged after 30 days (`AI_ASYNC_CONTENT_RETENTION_DAYS`, 8.3).
- No provider API keys (environment only).
- No model catalog table (the catalog is versioned in-repo data).
- No circuit-breaker state (it is in-process, see section 10).

### 4.5 Sync request lifecycle (I)

Sync calls (`run`, `embed_texts`) leave an `ai_requests` row, so every routed call is traceable and its `ai_usage_records` have a parent.

- **Validation before routing.** Rejections that need no catalog and no budget raise before any row is written, and leave nothing behind: an unknown or unready task (`AiTaskNotReady`), a scope the task does not allow, the user-path restriction (D-7), a part modality outside the task definition (`AiModalityNotSupported`), and embedding batch or text limit violations.
- **Creation.** From the Router onward, the orchestrator first inserts the row in its own short transaction: `mode='sync'`, `status='running'`, `started_at = now`, with `idempotency_key`, `request_fingerprint`, `input_payload` and the lease columns NULL and `lease_epoch = 0`. No event is published.
- **Statuses.** `running` then `succeeded` or `failed`, with `completed_at`. `queued` is never used for sync. `output_payload` is stored only when `persist_result=True`.
- **Refused or unroutable call.** A call that fails at routing or reservation (`no_route`, `input_too_large`, `provider_not_configured`, `budget_exceeded`) ends the row `failed` with that `error_code` and `completed_at`. It leaves one metadata-only `ai_requests` row, no `ai_usage_records` row and no reservation. A budget refusal still publishes `ai.budget_exhausted` once, when it is the row's first refusal (12.3).
- **Stale rows.** A sync row still `running` after `sync_stale_after` (420 s: the longest latency-class deadline, 300 s, plus a 120 s margin) belongs to a crashed caller. The reaper (8.2) marks it `failed` with `execution_abandoned` and abandons its `reserved` usage records, charging the estimate. No lease is involved.

## 5. Public interface

The package root `app.ai_platform` is the only import surface. The signatures below are the contract, not an implementation. Names are exported from `app/ai_platform/__init__.py`.

### 5.1 Context and request types

```python
class AiModality(StrEnum):            # text | image | video | audio
class AiCapability(StrEnum):          # text_generation, reasoning, retrieval_grounding,
                                      # structured_output, embedding, image_understanding,
                                      # image_generation, video_generation,
                                      # audio_transcription, audio_generation
class AiTaskName(StrEnum):            # the 8 tasks in section 9 (+ EMBED_TEXT, internal)

@dataclass(frozen=True)
class AiCallContext:
    workspace_id: UUID | None
    user_id: UUID | None
    actor_type: Literal["user", "system", "worker"]
    request_id: str                   # correlation id, as in RequestContext
    @classmethod
    def from_workspace(cls, ctx: WorkspaceContext, *, request_id: str) -> AiCallContext: ...
    @classmethod
    def for_worker(cls, *, workspace_id: UUID, request_id: str) -> AiCallContext: ...
    @classmethod
    def system(cls, *, request_id: str) -> AiCallContext: ...

class AiContextBlock(BaseModel):      # extra="forbid", frozen
    text: str                         # UNTRUSTED DATA (11.1)
    source_id: str | None = None      # opaque lineage reference (§43), never interpreted

class AiTaskRequest(BaseModel):       # extra="forbid", frozen
    task: AiTaskName
    instructions: str                 # trusted task prompt text, owned and versioned by the calling domain module (D-6)
    context: list[AiContextBlock] = []
    parts: list[AiPart] = []          # multimodal input (13); empty for text-only tasks
    output_schema_version: int | None = None   # None = registry default
    max_output_units: int | None = None        # may only lower the task default
    quality_floor: QualityClass | None = None  # may only raise the task's class
    persist_result: bool = False               # sync only
```

`AiTaskRequest` has no field that can name a provider or model (INV-2). `instructions` is trusted. Everything in `context` and any `TextPart` in `parts` is untrusted (11.1).

The `AiCallContext` constructors are the only way to build a context. The budget row a call uses is determined by the context (see 12.3):

- `from_workspace` accepts a `WorkspaceContext` that came from `require_workspace_permission` or `WorkspaceAccessService.authorize`. A bare `workspace_id` taken from client input is never accepted. The call is **workspace scope** and uses the workspace budget.
- `for_worker` is for workers and event handlers. Its `workspace_id` is required and must come from persisted data (an event envelope or a DB row), never from client input. The call is always workspace scope. `None` is rejected, so a worker cannot reach system scope through this constructor.
- `system` is for platform work with no workspace. The call is **system scope** and uses the system budget. It may be used only for `EMBED_TEXT` (D-15, section 9). Only code under `app/ai_platform/` and `app/rag/` may construct a system context. An architecture test rejects any other module that calls `AiCallContext.system` or constructs `AiCallContext` directly (INV-31).

### 5.2 Orchestrator

```python
class AiTaskResult(BaseModel):
    request_id: UUID
    task: AiTaskName
    output: BaseModel                  # validated instance of the registered output schema
    output_schema_name: str
    output_schema_version: int
    usage: AiUsageSummary              # input_units, output_units, cost_micro_usd, call_count
    routing_id: UUID                   # opaque; the final AiUsageRecord id. No provider/model name.

class AiRequestStatus(BaseModel):
    request_id: UUID
    task: AiTaskName
    status: Literal["queued", "running", "succeeded", "failed"]
    error_code: str | None
    usage: AiUsageSummary
    # deliberately no output: the domain module that owns the schema reads it via get_output

class AiOrchestrator(Protocol):
    async def run(self, ctx: AiCallContext, request: AiTaskRequest) -> AiTaskResult: ...
    async def submit(self, ctx: AiCallContext, request: AiTaskRequest,
                     *, idempotency_key: UUID) -> AiRequestStatus: ...
    async def get_status(self, ctx: AiCallContext, request_id: UUID) -> AiRequestStatus: ...
    async def get_output(self, ctx: AiCallContext, request_id: UUID) -> BaseModel: ...
```

- `run` executes in the caller's await. It takes **no idempotency key** (F-1). Each call is a new request. It writes `ai_requests` and `ai_usage_records` in its own short transactions (see "Transaction ownership"). The sync request lifecycle is defined in 4.5.
- **Request-path restriction (D-7).** `run` with `ctx.actor_type == "user"` (a user request path) is allowed only for tasks whose latency class is `interactive`. For any other task it raises `ValidationFailed` with the fixed detail `This AI task must be submitted asynchronously`, before any reservation or provider call. Workers (`actor_type="worker"`) and system contexts may call `run` for any task.
- `submit` is the only operation with idempotency. It persists the request (`status=queued`, `mode=async`, `input_payload`, `request_fingerprint`) and an `ai.request_queued` outbox event in one transaction. The job is created by the event consumer (sections 7, 8). It returns the existing request when the same `idempotency_key` and fingerprint is replayed, and raises `Conflict` for a key reuse with a different fingerprint. Before persisting, `submit` makes an **advisory budget pre-check** (D-14): it runs the Router with the current budget snapshot and raises `AiBudgetExceeded` (no row, no event, nothing reserved) only when the budget step (10.2 step 7) is what removes the last candidate. A replay of an existing key returns the stored request without a pre-check. Any other Router outcome is ignored at `submit` and surfaces at execution. The pre-check is not the authority: the atomic reservation at execution (12.3) is, so an accepted request can still end `failed` with `error_code = budget_exceeded`.
- `get_status` and `get_output` raise `NotFound` when `request.workspace_id != ctx.workspace_id`. They never reveal that the request exists.
- `get_output` raises `Conflict` if the request is not `succeeded`, and raises `NotFound` if the content has been purged (8.3).

**Transaction ownership (deliberate deviation from "caller owns the session").** `ProfileService` and similar services use the caller's session and never commit. `ai_platform` cannot, for three reasons:

- A provider call must not run inside a long caller transaction holding row locks.
- Budget reservations must be visible to concurrent calls immediately.
- Money that was spent must persist even if the caller later rolls back.

The orchestrator is therefore constructed with an `async_sessionmaker` (the same pattern as `workspace.register_jobs(registry, session_factory)` and `EventWorker(sessions, ...)`) and opens its own short transactions. Each transaction is only a reservation (or refusal), a settlement, or a request-state change. No provider call happens inside a DB transaction.

### 5.3 Embeddings

```python
EMBEDDING_MODEL: Final = "text-embedding-3-small"
EMBEDDING_DIMENSIONS: Final = 1024
EMBEDDING_VERSION: Final = "v1-d1024"

class EmbeddingBatch(BaseModel):
    vectors: list[list[float]]         # len == len(texts); each len == 1024
    embedding_model: str               # "text-embedding-3-small"
    embedding_version: str             # "v1-d1024"
    dimensions: int                    # 1024
    usage: AiUsageSummary

class EmbeddingService(Protocol):
    async def embed_texts(self, ctx: AiCallContext, texts: Sequence[str]) -> EmbeddingBatch: ...
```

- The service rejects an empty batch, a batch larger than 128 texts, an empty text, or a text whose estimated input exceeds the model limit of 8,191 units, all with `ValidationFailed` (`ai_input_too_large` or `validation_failed`).
- The model is OpenAI `text-embedding-3-small`, requested with `dimensions=1024`.
- There is no fallback to another embedding model (INV-12). Vectors from different models or dimensions are not comparable.
- `embedding_model` and `embedding_version` are what `rag` persists per chunk (§54).
- If `Settings.embedding_dim` is set and is not 1024, `ai_platform` startup validation raises `ConfigurationError`.
- It is a platform call (`EMBED_TEXT`). It is metered like any other call. A workspace context spends the workspace budget. A system context (for example GLOBAL knowledge) spends the system budget (12.3). It takes no idempotency key. It runs synchronously inside the caller's worker. `rag` owns the embedding job.
- If the OpenAI key is absent, `embed_texts` raises `AiProviderNotConfigured` (a `ConfigurationError`) at call time (D-13).

### 5.4 Errors (all `DomainError` subclasses unless noted; fixed `detail` strings, never provider or user text)

| Class | Base / status | `code` | When |
| --- | --- | --- | --- |
| `AiBudgetExceeded` | `RateLimited` / 429 | `ai_budget_exceeded` | The call's budget row (workspace or system, by scope) cannot cover the call. |
| `AiNoRoute` | `ExternalServiceError` / 502 | `ai_no_route` | No catalog model passes the Router's filters (not because of budget or missing provider keys). |
| `AiProviderUnavailable` | `ExternalServiceError` / 502 | `ai_provider_unavailable` | All attempted candidates failed transiently. |
| `AiOutputInvalid` | `ExternalServiceError` / 502 | `ai_output_invalid` | Schema enforcement failed finally (section 11). |
| `AiContentRefused` | `ExternalServiceError` / 502 | `ai_content_refused` | Provider refused or filtered. No fallback. |
| `AiInputTooLarge` | `ValidationFailed` / 422 | `ai_input_too_large` | Estimated input fits no eligible model (or the embedding limit). |
| `AiModalityNotSupported` | `ValidationFailed` / 422 | `ai_modality_not_supported` | A part's modality is outside the task definition or no catalog model supports it. |
| `AiTaskNotReady` | `DomainError` / 503 | `ai_task_not_ready` | The task's output schema is not registered. |
| `AiProviderNotConfigured` (subclass of core `ConfigurationError`, which is not a `DomainError`) | 503 `service_unavailable` | n/a | No eligible model remains only because its provider key is not configured (D-13). In an async job this ends the request `failed` with `provider_not_configured` and is not raised to the queue (8.1). |

`ValidationFailed` with the detail `This AI task must be submitted asynchronously` (D-7) is raised for a user-path `run` of a non-interactive task.

The persisted `error_code` values on `ai_requests` and `ai_usage_records` are:

- `provider_timeout`
- `provider_rate_limited`
- `provider_unavailable`
- `provider_auth_failed`
- `provider_not_configured`
- `provider_bad_request`
- `content_refused`
- `output_truncated`
- `output_invalid`
- `budget_exceeded`
- `no_route`
- `input_too_large`
- `lease_lost`
- `execution_abandoned`

### 5.5 Usage, budget, registries, wiring

```python
class AiBudgetService(Protocol):
    async def get_status(self, ctx: AiCallContext) -> AiBudgetStatus: ...        # workspace ctx only

class AiUsageService(Protocol):
    async def get_workspace_usage(self, ctx: AiCallContext, *, period_start: date,
                                  group_by: Literal["task", "model", "day"]) -> AiUsageReport: ...

class AiTaskRegistry:                      # read-only for other modules
    def get(self, task: AiTaskName) -> AiTaskDefinition: ...
    def list(self) -> list[AiTaskDefinition]: ...

class OutputSchemaRegistry:
    def register(self, name: str, version: int, model: type[BaseModel]) -> None: ...
    def get(self, name: str, version: int | None = None) -> type[BaseModel]: ...

def check_ai_providers(settings: Settings, *,
                       capability: Literal["generation", "embedding"]) -> Literal["ok", "not_configured"]: ...

def build_ai_platform(settings: Settings, sessions: async_sessionmaker, *, clock: Clock,
                      provider: ProviderClient | None = None,
                      config: AiPlatformConfig | None = None) -> AiPlatform: ...
def register_jobs(registry: JobRegistry, ai: AiPlatform) -> None: ...
def register_event_handlers(ai: AiPlatform) -> Mapping[str, EventHandler]: ...
def register_routes(app) -> None: ...
```

- `AiBudgetService` and `AiUsageService` take a workspace-scoped `AiCallContext`. Callers must already have passed the `ai:usage_read` check (section 15).
- A domain module registers the output schema it owns with `OutputSchemaRegistry.register(...)` at startup. This is how a task becomes ready. `AiTaskRegistry` is owned by `ai_platform`.
- `check_ai_providers` (D-13) is a presence-only readiness helper in the style of `check_database`/`check_redis`. It never calls a provider, performs no network access and reveals no key material. `capability="embedding"` is `ok` only when the OpenAI key is present. `capability="generation"` is `ok` when at least one enabled catalog provider with a generation-capable model has its key present (today only Gemini). `rag` may call it at startup. `ai_platform` itself never fails at startup for a missing key.
- Provider API keys are read as `SecretStr` from LiteLLM's conventional environment variables (`OPENAI_API_KEY`, `GEMINI_API_KEY`).
- `AiPlatformConfig` (`pydantic-settings`, env prefix `AI_`, owned by `ai_platform`, not core `Settings`) holds the budget limits (12.3), the content retention (8.3) and the job tuning values. `build_ai_platform` builds it from the environment when none is passed and raises `ConfigurationError` on an invalid value.
- `FakeAiProvider` and `ScriptedResponse` are exported from the package root for other modules' tests (the boundary test forbids `app.ai_platform.testing`-style deep imports). The fake records the exact provider request it received so tests can assert its shape (11.1).

### 5.6 What is NOT exposed

- LiteLLM, any provider SDK type, the model catalog, router internals, circuit-breaker state, and provider/model identifiers in results or exceptions.
- Any way to choose, pin, exclude or prefer a provider or model per call. A per-call model override does not exist.
- Tool or function calling. No request type, option or provider parameter lets a caller define or enable tools in this phase (11.1).
- Any way to mutate budgets, price tables or routing rules.
- ORM classes of `ai_*` tables. Other modules must not query these tables. Reads go through the services above.
- Raw provider responses, prompts or completions, other than the validated output for the owning domain module.
- API-key material of any kind.
- Idempotency keys on `run` and `embed_texts`.

### 5.7 Notes for dependent modules

- **`rag`.** The embedding job must treat `AiBudgetExceeded` as "defer and retry later", not as a dead-letter failure. The `rag` spec defines the exact behavior (delay, attempt accounting). Workspace-scope embeddings (WORKSPACE/PROFILE knowledge) draw on the workspace budget. GLOBAL knowledge embeddings draw on the system budget. A missing OpenAI key surfaces as `ConfigurationError` at call time. System-scope embeddings use `AiCallContext.system`, which only `rag` and `ai_platform` may build (D-15). `rag` may call `check_ai_providers(settings, capability="embedding")` at startup.
- **Domain modules** own and version their prompts and their output schemas (D-6). They authorize the user for their own action before calling. On a user request path they may call `run` only for `interactive` tasks; everything else uses `submit` (D-7). An async request refused for budget ends `failed` with `error_code = budget_exceeded`.
- **`context_engine`** supplies the context blocks. It must not rely on `ai_platform` to trim them.

## 6. OpenAPI endpoints

`ai_platform` does not expose an endpoint to run tasks. Business modules own their user-facing endpoints, authorize the user, and call the orchestrator. A generic "run AI" endpoint would let clients bypass domain authorization and domain output shapes.

It exposes two **read-only** endpoints so that workspace OWNER/ADMIN can see the effect of budget enforcement. Prefix: `/api/v1/workspaces/{workspace_id}/ai`. Both use `require_workspace_permission(WorkspacePermission.AI_USAGE_READ)` and are registered in the tenant-isolation harness.

| Method and path | Permission | Behavior |
| --- | --- | --- |
| `GET /budget` | `ai:usage_read` | Current-month budget status for this workspace (the workspace budget only). |
| `GET /usage?period=YYYY-MM&group_by=task\|model\|day` | `ai:usage_read` | Aggregated usage for one UTC month; default is the current month, default group is `task`. Past months with data are allowed. A future month returns 422. |

`GET /budget` response `AiBudgetStatus`:

- `currency` (the constant `"USD"`)
- `period_start`
- `limit_micro_usd`
- `spent_micro_usd`
- `reserved_micro_usd`
- `remaining_micro_usd` (`max(0, limit - spent - reserved)`)
- `percent_used` (integer, `floor(100 * spent / limit)`, settled spend only)
- `state`: `exhausted` if `spent >= limit` or the row's `exhausted_notified_at` is set (at least one call was refused this period); else `warning` if `spent * 100 >= 80 * limit`; else `ok`

`limit_micro_usd` is the current configured workspace limit for the current period (D-9) and the row's stored limit for past periods. A workspace with no row yet this month reports the configured limit and zero counters. The `state` rule after a mid-month limit raise is provisional — OQ-4.

`GET /usage` response `AiUsageReport`:

- `period_start`
- `totals` (`call_count`, `failed_call_count`, `input_units`, `output_units`, `cost_micro_usd`)
- `groups`: a list of `{key, call_count, failed_call_count, input_units, output_units, cost_micro_usd}`

Groups are bounded (task ≤ 9, model ≤ catalog size, day ≤ 31), so there is no cursor. Both endpoints:

- follow the shared RFC 7807 error contract,
- never return prompt or completion content, or a per-call record,
- return provider/model identifiers only inside the `model` grouping, for OWNER/ADMIN.

There is no system-wide usage endpoint (no admin surface exists before `admin_ops`). System usage is readable through `AiUsageService` for system actors only.

## 7. Events in/out

Events are `DomainEvent` subclasses registered in `DEFAULT_EVENT_REGISTRY` in `app/ai_platform/events.py`. They are published with `publish(session, event)` inside the transaction that changes the state they describe. Payload fields are shown without the base fields (`aggregate_type`, `aggregate_id`, `workspace_id`, `occurred_at`). The rules are:

- No payload key contains the word `token`.
- No payload carries content (prompts, completions, user text, context text, schema output).
- No payload carries a provider API key or URL.
- Every payload key passes the envelope's sensitive-key regex (INV-18).

| Event type (v1) | Aggregate | `workspace_id` | Payload fields |
| --- | --- | --- | --- |
| `ai.request_queued` | `ai_request` / request id | request's workspace (null for system) | `task: str`, `output_schema_name: str`, `output_schema_version: int` |
| `ai.request_completed` | `ai_request` / request id | request's workspace | `task: str`, `output_schema_name: str`, `output_schema_version: int`, `attempts: int` (calls), `input_units: int`, `output_units: int`, `cost_micro_usd: int` |
| `ai.request_failed` | `ai_request` / request id | request's workspace | `task: str`, `error_code: str`, `attempts: int`, `cost_micro_usd: int` |
| `ai.budget_threshold_reached` | `ai_budget` / budget period id | workspace (null for system) | `scope: "workspace"\|"system"`, `period_start: date`, `threshold_percent: 80`, `limit_micro_usd: int`, `spent_micro_usd: int`, `reserved_micro_usd: int` |
| `ai.budget_exhausted` | `ai_budget` / budget period id | workspace (null for system) | same fields with `threshold_percent: 100` |

- `ai.request_queued`, `ai.request_completed` and `ai.request_failed` are emitted for `async` requests only. For `sync` calls the caller already has the result or the error, and the ledger has the facts.
- Budget events are emitted for both modes, exactly once per budget row (scope, workspace, period) and level (INV-15).
- `ai.budget_threshold_reached` is evaluated on settled `spent_micro_usd` only (F-2).
- `ai.budget_exhausted` is published on the **first refusal** for a budget row in a period (F-3). Reservations use worst-case estimates, so this can happen before settled `spent` reaches exactly 100 % of the limit. The `threshold_percent: 100` field names the level, not an exact spend ratio, and the payload carries the actual `spent` and `reserved` amounts at that moment.

**Events in.** `ai_platform` consumes only its own `ai.request_queued`, through `handle_once` with consumer name `ai_platform.request_queued`. The handler enqueues the `ai_platform.execute_request` job. This is the §53 pattern: persist canonical data, emit an event, and a worker picks it up. It also makes enqueue failure recoverable, because the outbox relay retries. `ai_platform` consumes no other module's events in this phase:

- `workspace.deleted` is a soft delete. New calls for a workspace that no longer exists fail at the caller's `WorkspaceAccessService.authorize`.
- Usage rows are accounting history and are retained.
- Data deletion and export are Phase 9 `security_compliance`.

## 8. Jobs

Handlers are registered with `JobRegistry.register(job_type, version, handler)`. Job payloads and metadata contain identifiers only (no content, no keys). `metadata` carries `request_id` and `traceparent` so the worker's `RequestContext` and log correlation continue the originating request. The periodic jobs (8.2 reap, 8.3 purge, 8.4 reconcile) are not driven by a scheduler. An external cron runs the CLI in 8.5, which enqueues the job for a UTC bucket (D-2).

### 8.1 `ai_platform.execute_request` v1

- **Payload:** `{"request_id": "<uuid>"}`. The handler loads `workspace_id`, the task and the input from the `ai_requests` row. It never trusts a workspace from the payload.
- **Idempotency key:** `ai_requests.id`. The job runs at-least-once and the effect is exactly-once at the request level:
  - A `succeeded` or `failed` request makes the job a no-op.
  - The claim is a single conditional `UPDATE ai_requests SET status='running', lease_owner=:worker, lease_epoch=lease_epoch+1, lease_expires_at=:now+180s, attempt_count=attempt_count+1 WHERE id=:id AND (status='queued' OR (status='running' AND lease_expires_at < :now)) RETURNING lease_epoch`. Zero rows means the job returns without effect. The worker keeps the returned `lease_epoch` as `:epoch` for the whole execution.
- **Lease:** 180 s. **Heartbeat:** every 60 s, `UPDATE ... SET heartbeat_at=:now, lease_expires_at=:now+180s WHERE id=:id AND lease_owner=:worker AND lease_epoch=:epoch AND status='running'`. All times come from the injected `Clock`.
- **Lease fencing (E-1).** Every state change by the worker is conditioned on `lease_owner = :worker AND lease_epoch = :epoch AND status = 'running'`:
  - the heartbeat;
  - the reservation transaction and the settlement transaction, each of which opens with the fence statement `UPDATE ai_requests SET updated_at = :now WHERE id = :id AND lease_owner = :worker AND lease_epoch = :epoch AND status = 'running'` and continues (usage record, budget row, request totals) only if it returned one row;
  - the completion (terminal status, `output_payload` or `error_code`, `completed_at`, lease cleared).
  A statement that affects 0 rows means the worker no longer owns the request. The worker rolls back, cancels its in-flight provider call, performs no further state change and returns. The epoch strictly increases with every claim, so a stale worker can never heartbeat, settle or complete after another worker claimed the request, even when both use the same worker identity. A fenced worker does not settle its own `reserved` usage record. The reaper abandons it and charges its estimate (8.2, INV-14).
- **Lost lease:** if the heartbeat updates 0 rows, the worker treats the lease as lost under the fencing rule above.
- **Duplicate delivery:** `JobQueue.run_once` reclaims messages idle for more than 60 s (`xautoclaim min_idle_time=60_000`), shorter than the 180 s lease. A long AI call can therefore be delivered to a second consumer. That consumer fails the claim above, returns normally and is acknowledged. It does not raise, so it does not consume `max_attempts`. If the first worker actually died, the lease expires after at most 180 s and the reaper (8.2) re-enqueues. The next claim increments `lease_epoch`.
- **Retry policy:** two layers.
  - *Provider and schema failures* are handled inside the handler by the Router and the repair policy (sections 10, 11). They end in a terminal `failed` request and the handler returns normally. The queue never retries them, so a provider failure is never paid for twice.
  - *Infrastructure failures* (database or Redis errors, crashes) raise, and `JobQueue` applies its existing policy: `max_attempts=5`, backoff `min(300, 2**attempt)` s, dead letter on `jobs:dead` with `failure_code` the exception class name.
- **Missing credentials (H).** If routing finds that no eligible model's provider key is configured (`AiProviderNotConfigured`), the handler makes no reservation and no call, ends the request `failed` with `error_code = provider_not_configured`, publishes `ai.request_failed` (`attempts: 0`, `cost_micro_usd: 0`) and returns normally. The queue does not retry it and no `max_attempts` is consumed. Once the key is configured, the caller submits a new request.
- **Budget refusal at execution:** the request ends `failed` with `error_code = budget_exceeded` (no call was made) and `ai.request_failed` is published. It is terminal and is not retried by the queue.
- **Completion:** in one fenced transaction the handler stores `output_payload` (or `error_code`), sets the terminal status and `completed_at`, clears the lease, and publishes `ai.request_completed` or `ai.request_failed`.

### 8.2 `ai_platform.reap_stale_requests` v1

- **Payload:** `{"bucket": "<UTC minute ISO-8601>"}`. **Idempotency key:** the bucket. Re-running a bucket, or running it concurrently, re-evaluates the same predicates. Every effect is a single conditional statement, so the outcome is the same.
- **Effects:**
  - `running` async requests whose `lease_expires_at` passed more than 180 s ago:
    - If `attempt_count < 5`, the reaper re-enqueues `execute_request`.
    - Otherwise it marks the request `failed` with `error_code = execution_abandoned` and emits `ai.request_failed`. That update is conditioned on the `lease_epoch` and `lease_expires_at` the reaper read, so it cannot overwrite a newer claim.
  - `queued` requests older than 5 minutes: re-enqueue `execute_request`. This is a backstop for a lost job message.
  - Stale `reserved` usage records are marked `abandoned`. The amount reserved is **charged to `spent` as the cost** (never undercount) and the reservation is released (INV-14). The settlement flip is `WHERE status = 'reserved'`, so a record is abandoned at most once. The age thresholds are chosen so that no live call can still hold the record, because every call is bounded by its request deadline (at most 300 s):
    - **Async requests:** reserved for more than 360 s (2 × the lease). The condition does not depend on the request's lease, so it also covers the record of a fenced worker (8.1) whose request is now owned by a newer claim.
    - **Sync requests (I):** the request has `mode = 'sync'` and no lease. The record is reserved for more than `sync_stale_after` = 420 s (the longest latency-class deadline, 300 s, plus a 120 s margin). Config validation rejects any value that is not greater than the longest deadline. The same job also marks the sync request itself (still `running` for more than `sync_stale_after`) `failed` with `error_code = execution_abandoned`, with no event.
- **Triggering:** by the cron CLI (8.5) once per minute. Handlers are called directly in tests.

### 8.3 `ai_platform.purge_expired_content` v1 (D-5)

- **Purpose:** stored async input and output content is purged 30 days after the request completed. Retention is `content_retention_days`, configured by `AI_ASYNC_CONTENT_RETENTION_DAYS` (default 30, read by `AiPlatformConfig`, 5.5). Tests use `FakeClock` at 30 days.
- **Payload:** `{"bucket": "<UTC hour ISO-8601>"}`. **Idempotency key:** the bucket.
- **Effect:** for requests with `status IN ('succeeded','failed')`, `completed_at < now - content_retention_days` and `content_purged_at IS NULL` that still hold `input_payload` or `output_payload`, one conditional `UPDATE` sets `input_payload = NULL`, `output_payload = NULL` and `content_purged_at = :now`. The job processes at most a configured batch size (default 500) per execution, ordered by `completed_at`, using the `ix_ai_requests_purge_candidates` index. A re-run, a re-delivery of the same bucket or a concurrent run finds nothing left to change and is a no-op.
- **Never touched:** all metadata (`ai_requests` columns other than the two content columns and `content_purged_at`) and every `ai_usage_records` and `ai_budget_periods` row. Non-terminal (`queued`/`running`) requests are never purged. Rows with no content are left alone.
- **Observability:** one structured log event with the count only. No event, no audit record, no content.
- **Triggering:** by the cron CLI (8.5) once per hour.
- After purge, `get_output` raises `NotFound` and `get_status` still works.
- **Operational note.** Database backups and WAL / point-in-time-recovery retention are outside application control. Purged content remains recoverable from any backup or recovery window that predates the purge. The backup and WAL retention of the database must be reviewed against the privacy policy before production. This spec does not claim that content is unrecoverable after the purge.

### 8.4 `ai_platform.reconcile_budgets` v1 (E-2)

- **Payload:** `{"bucket": "<UTC hour ISO-8601>"}`. **Idempotency key:** the bucket.
- **Check:** for every `ai_budget_periods` row of the current and the previous UTC month with `reserved_micro_usd = 0`, compare `spent_micro_usd` with `SUM(cost_micro_usd)` over the `ai_usage_records` of the same scope, workspace and `period_start`. Rows with `reserved_micro_usd > 0` are skipped and counted. The comparison is one SQL statement, so it runs on one snapshot. A settlement changes the usage row and the budget row in one transaction, so a concurrent settlement cannot cause a false mismatch.
- **No silent repair (INV-30).** The job never changes `spent_micro_usd`, `reserved_micro_usd`, `limit_micro_usd` or any `ai_usage_records` row.
- **On a mismatch:** one conditional statement `UPDATE ai_budget_periods SET reconcile_mismatch_bucket = :bucket WHERE id = :id AND reconcile_mismatch_bucket IS DISTINCT FROM :bucket RETURNING id`. Only if a row is returned, in the same transaction:
  - `append_audit` writes an `AuditRecord` (`action="ai.budget.reconciliation_mismatch"`, system actor) whose details hold only `budget_period_id`, `scope`, `period_start`, `bucket`, `spent_micro_usd`, `recomputed_micro_usd` and `usage_row_count`;
  - one structured warning log `ai_budget_reconcile_mismatch` carries the same ids and counts.
  A re-run of the same bucket, or a concurrent run, writes nothing more. A row that is still mismatched is reported again by the next hour's bucket.
- **Summary:** one structured log `ai_budget_reconciled` with `rows_checked`, `rows_skipped` and `mismatch_count`. No event is published.
- **Triggering:** by the cron CLI (8.5) once per hour.

### 8.5 Cron CLI (D-2)

An external cron runs `python -m app.ai_platform.cron <reap|reconcile|purge>`. The CLI lives inside `ai_platform` and enqueues the matching job through `JobQueue.enqueue`:

| Argument | Job enqueued | Bucket | Recommended cadence |
| --- | --- | --- | --- |
| `reap` | `ai_platform.reap_stale_requests` v1 | UTC minute | every minute |
| `reconcile` | `ai_platform.reconcile_budgets` v1 | UTC hour | hourly |
| `purge` | `ai_platform.purge_expired_content` v1 | UTC hour | hourly |

- The CLI needs only the Redis configuration. It reads the bucket from the `Clock`, opens no database session and needs no provider key.
- It prints and logs only the job type and the bucket. It exits 0 once the job is enqueued, and non-zero on an unknown argument or an enqueue failure.
- The same bucket can be enqueued more than once (overlapping cron runs, retries). The jobs are idempotent per bucket and safe under concurrent runs (8.2, 8.3, 8.4).
- A generic in-process scheduler in `jobs_workers` is a documented future option. It would enqueue the same jobs and replace the cron trigger without changing them. It is not a prerequisite.

### 8.6 What is not a job here

- The embedding pipeline job is owned by `rag` (§54). It calls `EmbeddingService.embed_texts` from inside its handler.
- Sync `run` calls are not jobs.

## 9. AI tasks used and the task registry

Business modules request only these names. The task registry is an in-code, versioned list. Every entry is validated at startup (`AiTaskNotReady` if its schema is missing at call time).

Classes (initial configuration defaults, tunable in config, pinned by tests):

| Class | Values | Meaning |
| --- | --- | --- |
| Quality | `basic` < `standard` < `high` | The minimum catalog `quality_tier` a model needs. |
| Latency | `interactive`, `standard`, `batch` | Total deadline for the request: 20 s, 60 s, 300 s. They also drive ranking (section 10). `interactive` is the only class a user request path may `run` directly (D-7). |
| Cost | `low`, `medium`, `high` | Ceiling on the estimated worst-case cost of a single provider call: 20,000 / 100,000 / 500,000 micro-USD. |

Capabilities (§45) say what a task needs from a model. `retrieval_grounding` means "the task consumes caller-supplied, source-tagged context blocks". `ai_platform` does not retrieve.

| Task | Capabilities | Output schema (name, v1) | Quality | Latency | Cost | Modalities in → out | Allowed scopes (D-15) |
| --- | --- | --- | --- | --- | --- | --- | --- |
| `ANALYZE_MARKET_TRENDS` | text_generation, reasoning, retrieval_grounding, structured_output | `MarketTrendAnalysis` | standard | batch | medium | text → text | workspace |
| `GENERATE_CONTENT_BRIEF` | text_generation, reasoning, retrieval_grounding, structured_output | `ContentBriefDraft` | high | standard | high | text → text | workspace |
| `GENERATE_CHANNEL_EXECUTION` | text_generation, retrieval_grounding, structured_output | `ChannelExecutionDraft` | standard | standard | medium | text → text | workspace |
| `GENERATE_CONTENT_DRAFT` | text_generation, retrieval_grounding, structured_output | `ContentDraftOutput` | high | standard | high | text → text | workspace |
| `GENERATE_HOOK_VARIATIONS` | text_generation, structured_output | `HookVariationSet` | standard | interactive | low | text → text | workspace |
| `ANALYZE_PERFORMANCE` | text_generation, reasoning, retrieval_grounding, structured_output | `PerformanceAnalysis` | high | batch | medium | text → text | workspace |
| `EXTRACT_AUDIENCE_SIGNALS` | text_generation, retrieval_grounding, structured_output | `AudienceSignalExtraction` | standard | batch | low | text → text | workspace |
| `SYNTHESIZE_SIGNALS` | text_generation, reasoning, structured_output | `SignalSynthesisResult` | standard | batch | medium | text → text | workspace |

The first eight rows are the example tasks listed in §44. The `GENERATE_CONTENT_BRIEF` capability set is the one given as the example in §45 (Text Generation, Retrieval, Reasoning, Structured Output).

Platform task (not in §44; added because §54 requires an embedding path):

| Task | Capabilities | Output | Allowed scopes | Notes |
| --- | --- | --- | --- | --- |
| `EMBED_TEXT` | embedding | `EmbeddingBatch` (not a Pydantic task schema) | workspace, system | internal, used by `EmbeddingService` only. Pinned to OpenAI `text-embedding-3-small` at 1024 dimensions. No fallback. Cannot be requested through `AiTaskRequest`. |

Schema and prompt ownership:

- The schema **names** and version numbers above are reserved by `ai_platform`.
- The schema **bodies** and the **prompt text** are owned and versioned by the domain module that owns the output (`brief`, `signal_synthesizer`, and so on) (D-6). Those modules do not exist yet.
- Until a module registers its schema, the task raises `AiTaskNotReady`. It fails closed and never falls back to unvalidated text.
- `ai_platform` ships test-only schemas under the fake provider for its own acceptance tests. They are not exported as product tasks.

A system-scope call for any task not listing `system` in its allowed scopes is rejected before any row is written (D-15). Widening system scope to another task is a spec change. Adding a task is a change to the registry and a spec change. A module cannot register a task at runtime.

## 10. AI Router rules

The Router is a pure, deterministic function of `(task definition, request, catalog, provider-configuration snapshot, health snapshot, budget snapshot)`. It performs no I/O. The same inputs always give the same ordered candidate list. This keeps routing testable.

### 10.1 Model catalog

- Versioned in-repo data (`catalog_version`, `price_version`).
- Chat provider: **Gemini**, through LiteLLM (D-4). **OpenAI** is used only for `text-embedding-3-small` (1024 dimensions, `v1-d1024`). No OpenAI chat model and no Anthropic adapter is enabled. The catalog format and the adapter mapping accept further providers and models later, as a change inside `ai_platform` only, with no change to domain modules or to `AiTaskRequest`. With a single enabled chat provider, fallback happens only between enabled Gemini models of the same billing mode. If only one model is eligible there is no fallback.
- Each model has: `provider`, `model`, `enabled`, `capabilities`, `input_modalities`, `output_modalities`, `quality_tier`, `context_window_units`, `max_output_units`, `supports_json_schema`, `latency_p50_ms` (static estimate), and integer prices `input_micro_usd_per_million_units` and `output_micro_usd_per_million_units`, plus `price_source_url` and `price_checked_on` (date), and `billing_mode`: `free_tier` or `paid`.
- **Prices are not written in this spec.** They are stored in the in-repo catalog under a `price_version`. They are *to be filled at implementation, with source URL and date*, and must be verified against each provider's official pricing page at that time. Free-tier quotas and limits are not written here either. Which specific Gemini models fill each quality tier is OQ-1. Tests use a synthetic fake catalog with synthetic prices.
- The catalog file, the provider adapter and the module configuration are the only places in the codebase that may contain provider or model identifiers (INV-3).
- Provider API keys are read from environment variables (`OPENAI_API_KEY`, `GEMINI_API_KEY`) as `SecretStr` and are never logged.

### 10.2 Selection, in order

1. **Capability and modality filter.** Keep models that are `enabled` and support every capability the task requires. Every modality present in the request (input) and required by the task (output) must be supported. A rejected model gets reason code `capability` or `modality`.
2. **Provider configured.** Drop models whose provider key is absent. Reason code `not_configured`. If this step is the only reason the list becomes empty, the call raises `ConfigurationError` (D-13), not `AiNoRoute`.
3. **Context fit.** Estimated input units, using LiteLLM's counter plus a configurable safety margin (default 10 %), plus the call's `max_output_units`, must fit `context_window_units`. Reason code `context`. If every model fails only here, raise `AiInputTooLarge`.
4. **Quality floor.** `quality_tier >= max(task.quality, request.quality_floor)`. A request can only raise the floor. Reason code `quality`.
5. **Cost ceiling.** The estimated worst-case cost of one call (formula in 12.2) must be ≤ the task's cost-class ceiling. Reason code `cost_class`.
6. **Availability.** Drop models whose circuit breaker is open (10.4). Reason code `unavailable`.
7. **Budget.** The estimated cost must fit the remaining budget of the one row the call uses (`limit - spent - reserved`, read as a snapshot): the workspace row for a workspace-scope call, the system row for a system-scope call. If steps 1–6 left candidates but this step removes all of them, raise `AiBudgetExceeded`. The atomic reservation in 12.3 is still the authority. The snapshot only keeps the Router from proposing hopeless candidates.
8. **Rank.** Sort the remaining candidates lexicographically. The final key is always `model` ascending, so ties are deterministic.
   - `interactive`: (`latency_p50_ms` asc, estimated cost asc, `model` asc)
   - `standard`: (estimated cost asc, `latency_p50_ms` asc, `model` asc)
   - `batch`: (estimated cost asc, `model` asc)
9. **Billing-mode lock.** Keep only candidates whose `billing_mode` equals that of the first-ranked candidate. The rest get reason code `billing_mode`. The request never uses a candidate of the other billing mode, so a `free_tier` request never falls back to a `paid` candidate, and the reverse (INV-29).
10. If no candidate remains and the cause was not budget, context or missing provider keys, raise `AiNoRoute`. For embeddings the candidate list is exactly the pinned model, or `AiNoRoute` if it is unavailable.

Quality is a floor, not an objective. Among eligible models the cheapest (or, for `interactive`, the fastest) wins. This keeps selection simple and predictable (§62).

### 10.3 Fallback and failure behavior

- LiteLLM's own retries are turned off (`num_retries=0`). The Router owns every retry so that every attempt gets a usage record and a budget reservation.
- The orchestrator tries candidates in rank order, up to `max_provider_attempts` distinct models (default 3). Each attempt is a reserve, call and settle cycle (section 12).
- **Error classification (E-3).** Every failed attempt falls into exactly one class below. Only the Router retries, and it never retries the same model within one request, except for the repair call in section 11.

| Provider failure kind | Persisted `error_code` | Retry or fallback behavior | Bound |
| --- | --- | --- | --- |
| Timeout (no response within the call timeout or the request deadline) | `provider_timeout` | Failed attempt. Fall back to the next candidate. Counts toward the circuit breaker. If the remaining request deadline is below the next candidate's `latency_p50_ms`, stop and fail the request with `provider_timeout`. | One attempt per model; at most `max_provider_attempts` (3) distinct models; the request deadline (20/60/300 s) |
| Connection error (DNS, TCP, TLS) | `provider_unavailable` | Failed attempt. Fall back to the next candidate. Counts toward the circuit breaker. | As above |
| HTTP 5xx | `provider_unavailable` | Failed attempt. Fall back to the next candidate. Counts toward the circuit breaker. | As above |
| Rate limit or quota exhausted (HTTP 429, quota or resource exhausted) | `provider_rate_limited` | Failed attempt. Fall back to the next candidate of the **same billing mode**. Never from a `free_tier` candidate to a `paid` one (INV-29). Counts toward the circuit breaker. | As above |
| Auth failure (HTTP 401/403, invalid key) | `provider_auth_failed` | Failed attempt. Fall back to the next candidate. The model is marked unavailable for the process lifetime and logged at error level with its code only. | As above |
| Bad request (provider rejects the request) | `provider_bad_request` | Failed. **No fallback** (a programming or configuration error). Raise `AiProviderUnavailable` and log the code. | 1 attempt |
| Content refusal or filter | `content_refused` | Failed. **No fallback.** Raise `AiContentRefused`. | 1 attempt |
| Truncation (`finish_reason = length`) | `output_truncated` | Failed attempt. Not repaired. Fall back to the next candidate. | One attempt per model |
| Invalid output (strict validation fails, section 11) | `output_invalid` | Up to `max_repair_attempts` (1) repair call to the same model, then fall back to the next candidate. After all candidates, raise `AiOutputInvalid`. | At most `max_provider_attempts × (1 + max_repair_attempts)` = 6 calls |
| Missing credentials (no eligible model has its provider key) | `provider_not_configured` | No reservation, no call, no fallback. Sync: raise `AiProviderNotConfigured` (`ConfigurationError`). Async: the request ends `failed`, `ai.request_failed` is published and the job returns normally (8.1). | 0 calls |

- A quota-exhausted response is an ordinary failed attempt with `provider_rate_limited`. It never moves a `free_tier` request to a `paid` candidate.
- `budget_exceeded`, `no_route`, `input_too_large`, `lease_lost` and `execution_abandoned` never fall back to another candidate.

- The request's deadline (latency class) is a hard bound across all attempts. When the remaining time is below the next candidate's `latency_p50_ms`, the orchestrator stops and fails with `provider_timeout`.
- **Final failure:** raise `AiProviderUnavailable`, or the specific error above. `ai_requests.status` becomes `failed` with the matching `error_code`. No partial output is stored or returned.

### 10.4 Circuit breaker (availability)

Per `(provider, model)`, in-process (no Redis dependency). After 5 consecutive transient failures within 60 s, the breaker opens for 30 s. It then goes half-open and lets one probe through: success closes it, failure re-opens it. These defaults are configuration. All timing uses `Clock`. State is per worker process and not shared. That is acceptable for the modular-monolith MVP, and it is not a correctness mechanism, because budgets and ledgers are in the database.

### 10.5 How the choice is recorded

Per call attempt, an `ai_usage_records` row stores:

- `provider`, `model`, `catalog_version`, `price_version`, `billing_mode`, `routing_version`,
- `route_rank` (position in the ordered list),
- `candidate_snapshot` (every considered model with `eligible` and a `reason_code`; ids and codes only).

`ai_requests.routing_version` records the rules version. The final record's id is returned as the opaque `routing_id`. Together these answer "which model served this, why, and what else was considered" without logging content.

## 11. Strict output-schema enforcement

- Every registry task except `EMBED_TEXT` has a registered output schema. A "free text" task does not exist.
- A registered schema must be a Pydantic v2 `BaseModel` with `extra="forbid"`. `OutputSchemaRegistry.register` rejects any other model, and rejects duplicate `(name, version)`.
- **Request side:** the Router prefers models with `supports_json_schema` and the adapter passes the schema as a structured-output request (`response_format`). Models without it are still allowed for tasks that need only `structured_output` via JSON mode, and the response is validated in the same way.
- **Validation:** the raw output is parsed and validated with `model_validate_json(..., strict=True)`. There is no coercion, no extra keys, and no partial acceptance. Validation is the only gate. Provider-side schema support never replaces it.
- **Truncation:** `finish_reason = length` is a failure with code `output_truncated`. It is not repairable. The orchestrator moves on to the next candidate.
- **Repair policy:**
  - On a validation failure, the orchestrator may make up to `max_repair_attempts` (default 1) repair calls to the same model.
  - A repair call carries the original request (with the same untrusted-context handling as 11.1), the invalid output, and the validation error locations and types.
  - Every repair call is a full, recorded, budget-reserved call (`call_kind='repair'`).
  - Repair output is validated with the same strict rules.
  - If a repair fails, the candidate counts as failed and the Router falls back to the next candidate, which starts with a fresh first attempt.
  - The hard cap is `max_provider_attempts × (1 + max_repair_attempts)` calls per request (default 6).
- **What is recorded on failure:** `schema_valid=false`, `validation_error_count` and `validation_error_types` on the call record. Locations and values are not recorded.
- **Final failure** (all candidates exhausted by schema failures):
  - `run` raises `AiOutputInvalid`.
  - For async requests the status is `failed` with `error_code = output_invalid` and `ai.request_failed` is published.
  - No output is stored, returned, logged or put in an event or error message.
  - The money spent on failed calls stays in the ledger.
- **Version pinning:** the result records `output_schema_name` and `output_schema_version`. A caller may pin a version. A request for an unregistered version raises `AiTaskNotReady`.

### 11.1 Untrusted context and containment (F-4)

Context can carry text from the web, from users or from third parties (market data, audience comments, user edits). `ai_platform` therefore treats it as hostile input.

- **Untrusted data.** The text of every `AiContextBlock`, and of any `TextPart` in `parts`, is untrusted data. `instructions` is trusted because the calling domain module owns it (D-6).
- **Separation.** The adapter sends `instructions` in the instruction channel (system/developer message) and the context in a separate data section: its own message, enclosed in clearly delimited blocks. Each block carries its `source_id` as metadata. The delimiter includes a per-request random boundary marker, and if any context text contains that marker, a new marker is generated. The instruction channel states that the data section is reference data and not instructions. Context text never appears in the instruction channel.
- **No tools.** `ai_platform` exposes no tool or function calling in this phase. The adapter never sends `tools`, `functions`, `tool_choice` or equivalent parameters. Structured output uses `response_format` only. A model cannot be induced to act: its only effect is the text it returns.
- **Containment.** Strict schema validation (above) is the containment. Anything that does not validate against the registered schema is rejected, repaired or failed, never passed on. This also applies to repair calls.
- **No leakage.** Untrusted text is never copied into logs, events, audit details, job payloads, usage rows, error messages or `candidate_snapshot` (INV-18, INV-24).

## 12. Cost and budget accounting

### 12.1 Per-call usage records

Every provider call attempt writes exactly one `ai_usage_records` row (section 4.2). The row is created in the **reservation** transaction with `status='reserved'` and finished in the **settlement** transaction.

| Outcome | Settled status | Cost |
| --- | --- | --- |
| Success, valid output | `succeeded` | from provider-reported units × catalog price |
| Call returned but invalid output | `failed` (`output_invalid` / `output_truncated`) | provider-reported units × price (the provider charged) |
| Provider error with reported usage | `failed` | reported units × price |
| Provider error without usage (timeout, connection, 5xx) | `failed` | 0 |
| Process died before settlement | `abandoned` (by the reaper) | the reserved estimate (conservative) |

Units come from the provider response and are mapped to `input_units` and `output_units` at the adapter boundary. If a successful response has no usage, the adapter falls back to LiteLLM's counter on the request and response and flags this in the structured log with `usage_source="estimated"`. The per-request totals on `ai_requests` are the sums over its settled records.

### 12.2 Cost computation

- Costs are integers: `cost = ceil(units × price_per_million / 1_000_000)` for input and output separately, then summed. Rounding up means the ledger never undercounts.
- Catalog prices are the authority, versioned with `price_version` (D-4). LiteLLM's cost helper is not used for money. `billing_mode` does not change the computation: the catalog price of the model is used either way.
- **Reservation estimate** for a generation call = `ceil(estimated_input_units × in_price / 1e6) + ceil(max_output_units × out_price / 1e6)`. `max_output_units` is the lower of the request's value, the task default and the model's maximum. Embedding estimate = `ceil(estimated_input_units × in_price / 1e6)`.

### 12.3 Budgets

Two separate budgets exist (D-1). Neither draws on the other.

- **Workspace budget:** default **25 USD** per workspace per UTC calendar month, configured by `AI_WORKSPACE_MONTHLY_BUDGET_USD` (default `25`). It is used only by workspace-scope calls of that workspace.
- **System budget:** default **100 USD** per UTC calendar month, configured by `AI_SYSTEM_MONTHLY_BUDGET_USD` (default `100`). It is a **separate budget used only by system-scope calls** (for example embedding GLOBAL knowledge). Workspace-scope calls never reserve against it, settle against it or modify its row.
- **Conversion (G).** Both values are read by `AiPlatformConfig` as `Decimal`, never `float`, and converted to integer micro-USD as `int(value * Decimal(1_000_000))`. A value that is negative, not finite, not a number, or has more than 6 decimal places is rejected with `ConfigurationError` when the config is built. The defaults give 25,000,000 and 100,000,000 micro-USD.
- The period is the UTC calendar month of the reservation (D-3). A new month starts at zero. There is no carry-over.
- **Limit source (D-9, G).** Limits come from configuration only in this phase. There is no per-workspace override. The limit in force is the **current configured limit**. Every reservation and every settlement receives it as the parameter `:limit`. The row's `limit_micro_usd` stores the last limit seen, for display and history, and is never used to decide a reservation. A configuration change applies to the next reservation immediately and never invalidates an existing reservation: in-flight calls still settle. Lowering the limit below `spent + reserved` refuses new reservations until the period ends. Raising it admits new reservations at once.
- **One row per call.** Scope is fixed by the `AiCallContext` (5.1) and the task's allowed scopes (9). A workspace-scope call uses exactly its workspace row. A system-scope call uses exactly the system row. It never touches any workspace row.

**Concurrency-safe enforcement.** Reservation is one short transaction:

1. Ensure the call's budget row exists (`INSERT ... (limit_micro_usd) VALUES (:limit) ON CONFLICT DO NOTHING`).
2. Reserve with a single conditional statement: `UPDATE ai_budget_periods SET reserved_micro_usd = reserved_micro_usd + :est, limit_micro_usd = :limit, updated_at = :now WHERE id = :id AND spent_micro_usd + reserved_micro_usd + :est <= :limit RETURNING ...`.
3. If a row is returned, insert the `reserved` usage record in the same transaction and commit.
4. If zero rows are returned, the call is **refused**. In the same transaction, `UPDATE ... SET limit_micro_usd = :limit WHERE id = :id`, then `UPDATE ... SET exhausted_notified_at = :now WHERE id = :id AND exhausted_notified_at IS NULL RETURNING`. If the second statement returns a row, publish `ai.budget_exhausted` and append an `AuditRecord`. Commit that transaction, then raise `AiBudgetExceeded`. No usage record is written and no provider call is made.

Because the check and the increment are one atomic statement under the row lock, N concurrent callers can never reserve more than the limit in force, regardless of process count. There is a single row per call, so there is no lock ordering between budget rows.

**Settlement** (one transaction; for async requests it opens with the fence in 8.1): conditionally flip the usage record `reserved → succeeded|failed` (`WHERE status='reserved' RETURNING`, so settlement and release happen at most once). Then `reserved -= est`, `spent += actual_cost` and `limit_micro_usd = :limit` on the call's budget row. Then evaluate the warning threshold against `:limit`.

If actual cost exceeds the reserved estimate, which should not happen because the output is capped, the actual cost is still recorded in full and `spent` may exceed the limit. The next reservation is then refused. Spend is never silently dropped.

**Thresholds and refusal:**

| Level | Behavior |
| --- | --- |
| Settled `spent` < 80 % of the limit | Normal. |
| Settled `spent` ≥ 80 % (F-2) | Evaluated **only in the settlement transaction, on settled `spent_micro_usd`** (not on `spent + reserved`), against the current configured limit. After the `spent` update: `UPDATE ... SET warning_notified_at = :now WHERE id = :id AND warning_notified_at IS NULL AND spent_micro_usd * 100 >= 80 * :limit RETURNING`. If a row is returned, publish `ai.budget_threshold_reached`, append an `AuditRecord` (`action="ai.budget.threshold_reached"`, system actor) and emit a structured warning log. Calls continue unchanged. Reservations alone never publish it. |
| Refusal (no exemptions, D-8) | A reservation is refused when `spent + reserved + est > :limit` (the statement in step 2). This applies to every call, in both scopes, with no exemptions. The first refusal for a budget row in a period publishes `ai.budget_exhausted` once (step 4). Because reservations use worst-case estimates, this can happen **before settled `spent` reaches exactly 100 %** of the limit (F-3). Calls already in flight finish and settle. |

- Refusals write no `ai_usage_records` row, because no call was made. They are counted in a structured log event (`ai_budget_refused`) with scope, task and period only.
- The notification flags are not reset by a limit change. That is provisional (OQ-4).

**Reconciliation.** For any period row with `reserved_micro_usd = 0`, `spent_micro_usd` equals the sum of `cost_micro_usd` over `ai_usage_records` of that scope, workspace and period (INV-13). The `ai_platform.reconcile_budgets` job (8.4) checks this in production and reports a mismatch without repairing it. The test suite includes the same check (AC-36).

### 12.4 Logging, audit, privacy

- Log events: `ai_call_started`, `ai_call_finished`, `ai_budget_refused`, `ai_budget_threshold`, `ai_content_purged`, `ai_budget_reconciled`, `ai_budget_reconcile_mismatch`. The only fields are:
  - ids and codes: `request_id`, `workspace_id`, `task`, `provider`, `model`, `route_rank`, `status`, `error_code`,
  - counts: `input_units`, `output_units`, `latency_ms`, `cost_micro_usd`, `purged_count`, `rows_checked`, `rows_skipped`, `mismatch_count`, `usage_row_count`.
- No content ever appears in a log field, an exception message or a problem response. LiteLLM's message logging and success callbacks are disabled. Exception text from providers is never propagated. It is mapped to an `error_code`.
- The audit trail records threshold crossings and exhaustion. The per-call ledger is `ai_usage_records`, not `audit_log`.

## 13. Multimodal-ready interfaces

Shapes (Pydantic, `extra="forbid"`, discriminated on `modality`):

```python
class MediaRef(BaseModel):
    kind: Literal["storage_key", "https_url"]
    value: str                        # media bytes are never passed inline or stored here

class TextPart(BaseModel):  modality: Literal["text"];  text: str
class ImagePart(BaseModel): modality: Literal["image"]; media: MediaRef; mime_type: str
class VideoPart(BaseModel): modality: Literal["video"]; media: MediaRef; mime_type: str
class AudioPart(BaseModel): modality: Literal["audio"]; media: MediaRef; mime_type: str
AiPart = Annotated[TextPart | ImagePart | VideoPart | AudioPart, Field(discriminator="modality")]
```

`AiTaskDefinition` declares `input_modalities` and `output_modalities`. A "multimodal" task is one that declares more than one modality. The capability enum already contains the image/video/audio capabilities.

| Area | Implemented now | Interface-ready only |
| --- | --- | --- |
| Text in / text out via LiteLLM (generation, structured output, repair) | Yes | |
| Text embeddings (1024 dimensions) | Yes | |
| Router modality and capability filters | Yes, including unit tests that use fake catalog entries with image/video/audio models | |
| `MediaRef`, `ImagePart`, `VideoPart`, `AudioPart` types and validation | Yes (types, strict validation, serialization) | |
| Real adapters or catalog models for image, video, audio | | Yes — none exist. The catalog ships no such model. |
| Sending a non-text part to a task whose definition is text-only | Rejected with `AiModalityNotSupported` | |
| Image generation, video generation, audio transcription/generation | | Yes — capability names reserved. No task uses them yet. |
| Media storage and delivery (S3/R2) | | Not here. `content_asset` (Phase 6) owns it. `ai_platform` receives references only. |

No domain module has to handle multimodal complexity until a feature needs it (§47). Long-running media generation fits the same `submit` / job / lease / heartbeat model (section 8) without interface changes.

## 14. UI slice

Minimal and read-only. It is justified because budget enforcement (80 % warning, refusal at the limit) would otherwise be invisible to the people it affects, and because it is the end-to-end check that cost accounting reaches users.

- One "AI usage" panel in workspace settings, visible to OWNER and ADMIN only:
  - a budget meter built from `GET /budget` (spent and reserved vs the monthly limit, with `ok`, `warning` and `exhausted` states),
  - a per-task table built from `GET /usage?group_by=task`,
  - a month selector.
- No mutation controls, no model or provider selection, and no prompt or output display.
- The panel uses the generated TypeScript client from `api_contract`. Its detailed frontend spec is added by the FE task (`web_foundation` owns the shell). Backend completion does not wait on it.
- Business features show their own "AI budget reached" message from the `ai_budget_exceeded` problem code. That belongs to each feature's UI, not to this slice.

## 15. Authorization rules

- **Workspace-centric (§5, §58 P23).** A workspace id is never trusted from a URL or body.
  - Workspace endpoints use `require_workspace_permission`. The workspace comes from a DB-verified `WorkspaceContext`.
  - Python callers build `AiCallContext` through `from_workspace(WorkspaceContext)` (already verified) or `for_worker` / `system` as defined in 5.1.
- **Business authorization stays with business modules.** `ai_platform` does not decide whether a user may generate a brief. The domain module checks its own permission (for example `profile:update`) before calling. `ai_platform` enforces tenant scoping of data, budget and usage.
- **New permission** `ai:usage_read` (`WorkspacePermission.AI_USAGE_READ`) is added to `app.workspace.access.ROLE_PERMISSIONS`, the single registered extension point. OWNER: yes. ADMIN: yes. MEMBER: no (D-6).
- **Failure shapes** follow the workspace convention: non-member 404, member without permission 403.
- **Usage scoping.** Every read is `WHERE workspace_id = ctx.workspace_id`. Single-request reads (`get_status`, `get_output`) also match the request id and return `NotFound` on mismatch.
- **Reads by id are scoped.** A request id from another workspace is indistinguishable from a missing one.
- **Worker integrity.** Jobs carry only `request_id`. Workspace, task and input come from the persisted row. The `ai.request_queued` consumer is idempotent through `handle_once`.
- **System scope.** System-scope rows are not readable through any workspace endpoint. The budget and usage services reject a system context for workspace reads. A workspace-scope call can never be moved to the system budget, and a system-scope call can never be attributed to a workspace (12.3). A system context can be built only by `ai_platform` and `rag` (D-15).
- **Provider secrets.** Keys come from environment variables as `SecretStr`. They are never persisted, logged, evented, put in a job payload, or put in an error.
- **Content handling.**
  - Content exists only in `ai_requests.input_payload` / `output_payload` for async requests and `persist_result` calls, and is purged 30 days after completion (8.3).
  - Content is never copied to logs, events, audit details, job payloads, usage rows or errors.
  - Context text is untrusted (11.1).

## 16. Invariants

1. **INV-1.** Only code under `app/ai_platform/` imports `litellm` or any provider SDK. An architecture test fails on any other import.
2. **INV-2.** `AiTaskRequest`, `AiTaskResult`, `AiRequestStatus` and the exported exceptions contain no field, attribute or message that names a provider or model, and no per-call model override exists.
3. **INV-3.** No module outside `app/ai_platform/` contains a provider or model identifier from the catalog. Inside `app/ai_platform/`, such identifiers appear only in the catalog file, the provider adapter and the module configuration (architecture test).
4. **INV-4.** Every call to a provider goes through `AiOrchestrator` → `AiRouter` → `ProviderClient`. There is no code path from a public interface to a provider that skips the Router.
5. **INV-5.** The Router is deterministic: the same inputs always yield the same ordered candidates and the same `candidate_snapshot`.
6. **INV-6.** No provider call happens inside a database transaction that holds budget row locks.
7. **INV-7.** Every provider call attempt has exactly one `ai_usage_records` row. A row never goes from a terminal status back to `reserved`.
8. **INV-8.** A successful `run` or a `succeeded` async request always returns or stores an instance of the registered output schema that passed `strict=True` validation. Invalid output is never returned or stored.
9. **INV-9.** Total calls per request never exceed `max_provider_attempts × (1 + max_repair_attempts)`.
10. **INV-10.** For any budget row, `spent_micro_usd + reserved_micro_usd` exceeds the limit in force at the time of a reservation only through the settlement of a call whose actual cost exceeded its reservation. A reservation never pushes it over the limit passed with it (verified under concurrency).
11. **INV-11.** A call reserves against exactly one budget row, chosen by scope: the workspace row for a workspace-scope call, the system row for a system-scope call. A workspace-scope call never reads, reserves against, settles against or modifies the system row, and a system-scope call never modifies a workspace row.
12. **INV-12.** An embedding call uses `text-embedding-3-small` at 1024 dimensions. A result always reports `embedding_version = "v1-d1024"`, 1024-length vectors and the pinned model. There is no fallback model for embeddings.
13. **INV-13.** For any budget row with `reserved_micro_usd = 0`, `spent_micro_usd` equals the sum of `cost_micro_usd` of the matching usage records.
14. **INV-14.** Cost never undercounts. A cost is rounded up, and an abandoned reservation is charged at its estimate.
15. **INV-15.** `ai.budget_threshold_reached` is published at most once per budget row and period, and only from a settlement transaction, when settled `spent_micro_usd` first reaches 80 % of the limit (reservations alone never trigger it). `ai.budget_exhausted` is published at most once per budget row and period, on the first refusal, even under concurrent calls.
16. **INV-16.** An async request is executed to a terminal state at most once. Duplicate or concurrent job deliveries produce no second provider call and no second settlement.
17. **INV-17.** At most one worker holds a live lease on a request. The lease is 180 s and the heartbeat interval is 60 s. A worker that loses its lease performs no further state change.
18. **INV-18.** No `ai.*` event field name matches `token` (case-insensitive), nor any other pattern rejected by the event envelope. No `ai.*` event, audit detail, log field, job payload or error message contains prompt, completion, user text, context text or output content.
19. **INV-19.** Every read of usage, budget or request data is scoped by the caller's workspace. A cross-workspace request id behaves as not found.
20. **INV-20.** Provider API keys never appear in logs, errors, events, audit details, job payloads or the database.
21. **INV-21.** Every table has `tenant_scope` metadata. All workspace-scoped rows carry `workspace_id`. `workspace_id` is null only when `scope = 'system'`.
22. **INV-22.** All time-dependent behavior (leases, heartbeats, breaker timing, deadlines, budget period, retention, job buckets) uses the injected `Clock`.
23. **INV-23.** Registry tasks without a registered schema fail closed with `AiTaskNotReady`. There is no unvalidated-text fallback.
24. **INV-24.** Context text is untrusted. It is sent only in a delimited data section separate from the instruction channel, no provider request ever includes tools, functions or `tool_choice`, and output that fails schema validation is never returned or acted on.
25. **INV-25.** Content in `ai_requests.input_payload` / `output_payload` of a terminal request is nulled once it is `AI_ASYNC_CONTENT_RETENTION_DAYS` (default 30) days past `completed_at`. The purge changes no other column except `content_purged_at`, never changes `ai_usage_records` or `ai_budget_periods`, never touches non-terminal requests, and is idempotent.
26. **INV-26.** `run` with `actor_type="user"` succeeds only for tasks whose latency class is `interactive`. Any other user-path `run` raises `ValidationFailed` before any reservation or provider call.
27. **INV-27.** The spend of real-provider tests is capped at 20 USD in total (AC-54).
28. **INV-28.** Lease fencing. Every heartbeat, reservation, settlement and completion by an async worker is conditioned on `lease_owner = :worker AND lease_epoch = :epoch`, and every claim increments `lease_epoch`. A worker whose conditional statement affects 0 rows performs no further state change, so a stale worker can never heartbeat, settle or complete after another worker claimed the request.
29. **INV-29.** Billing mode. All provider attempts of one request use candidates of one `billing_mode`. The Router never falls back from a `free_tier` candidate to a `paid` candidate and never switches billing mode. A quota-exhausted response is a failed attempt (`provider_rate_limited`).
30. **INV-30.** Budget reconciliation never changes `ai_budget_periods` counters or `ai_usage_records`. A mismatch is reported once per budget row and bucket, with ids and counts only.
31. **INV-31.** A system-scope `AiCallContext` can be built only by code under `app/ai_platform/` and `app/rag/`, and only `EMBED_TEXT` may run in system scope. `AiCallContext.for_worker` always has a workspace.

## 17. Acceptance criteria

Fake-provider tests (AC-1 to AC-53) run by default on a local Postgres container with pgvector (marker `db`, with the existing session-scoped migration and rollback fixtures, plus committed-data fixtures for concurrency tests), and nightly on the Neon test branch. They never run on dev or production. They need no network and no provider key. The local-database mode of the test guard is prerequisite P-2 (section 20). The real-provider smoke test (AC-54 to AC-57) is a separate suite. Job handlers are invoked directly in tests. No cron and no scheduler is needed.

### 17.1 Architecture and contract (DB-free unless stated)

1. **AC-1.** An architecture test fails if anything outside `app/ai_platform/` imports `litellm` (INV-1).
2. **AC-2.** An architecture test fails if a catalog provider or model identifier appears in `app/` outside `app/ai_platform/`, or inside it outside the catalog file, provider adapter and module configuration (INV-3).
3. **AC-3.** Unit test: `AiTaskRequest` rejects unknown fields (including `model`, `provider` and `tools`). Reflection over `AiTaskRequest`, `AiTaskResult`, `AiRequestStatus` and the exception classes finds no field or message naming a provider or model (INV-2). Signature reflection shows `AiOrchestrator.run` and `EmbeddingService.embed_texts` have no idempotency parameter, and only `submit` has `idempotency_key` (F-1).
4. **AC-4.** The module-boundary test passes with `ai_platform` imported only through `app.ai_platform`, and the package exports every name listed in section 5, including `check_ai_providers`, `AiProviderNotConfigured` and `AiPlatformConfig`.
5. **AC-5.** The task registry contains exactly the eight §44 tasks with the capabilities, schema names, classes and allowed scopes in section 9, plus the internal `EMBED_TEXT`. A test pins the table. `EMBED_TEXT` cannot be built through `AiTaskRequest`.
6. **AC-6.** Every `ai.*` event model is registered once in `DEFAULT_EVENT_REGISTRY`, forbids extra fields, and no field name matches `token`. `publish` accepts each of them (INV-18).
7. **AC-7.** Settings and config validation:
   - `Settings(embedding_dim=1024)` is accepted, any other positive `embedding_dim` makes `build_ai_platform` raise `ConfigurationError`, and an unset value is accepted.
   - `AiPlatformConfig` defaults are workspace limit 25,000,000 micro-USD, system limit 100,000,000 micro-USD and retention 30 days. The conversion uses `Decimal` (for example `AI_WORKSPACE_MONTHLY_BUDGET_USD=12.345678` gives 12,345,678). Negative, non-numeric, non-finite and more-than-6-decimal values raise `ConfigurationError`. `sync_stale_after` not greater than the longest latency deadline raises `ConfigurationError`.
   - Provider key values never appear in `repr`, logs or errors.
8. **AC-8.** Missing provider keys (D-13). `build_ai_platform` succeeds with no keys.
   - With the OpenAI key absent, `embed_texts` raises `AiProviderNotConfigured` (a `ConfigurationError`) at call time.
   - With the Gemini key absent, a generation call raises `AiProviderNotConfigured`, not `AiNoRoute`.
   - With a fake catalog and only one provider's key present, the Router excludes the other provider's models with reason `not_configured` and routes to the configured one.
   - `check_ai_providers` returns `ok` or `not_configured` accordingly, makes no network call and reveals no key material.
9. **AC-9.** Router path (INV-4). An architecture test shows that only the provider adapter module imports `litellm` and that the adapter is referenced only from the orchestrator's call path. A behavior test with a spy `ProviderClient` and a spy Router drives `run`, the `execute_request` handler and `embed_texts`, and asserts that every provider call is preceded by a Router decision for the same request. A provider call with no preceding Router decision fails the test.
10. **AC-10.** Tenant scope metadata (INV-21). `validate_tenant_scope` passes with `ai_requests`, `ai_usage_records` and `ai_budget_periods` registered, and each has `info["tenant_scope"] == "tenant_scoped"` (DB-free). Under the `db` marker, inserting a `scope='system'` row with a `workspace_id`, or a `scope='workspace'` row without one, violates `ck_*_scope_workspace` in all three tables.
11. **AC-11.** Clock use (INV-22). An architecture test fails on `datetime.now(`, `datetime.utcnow(`, `date.today(`, `time.time(` and `time.monotonic(` anywhere under `app/ai_platform/` except the `SystemClock` wiring in `build_ai_platform`. Time-dependent behavior (lease, heartbeat, breaker, deadlines, budget period, retention, job buckets) is exercised with `FakeClock` in AC-20, AC-32, AC-42, AC-48 and AC-49.
12. **AC-12.** System context construction (D-15, INV-31). An architecture test fails if any module other than `app/ai_platform/` and `app/rag/` calls `AiCallContext.system(` or constructs `AiCallContext(` directly. A unit test shows `AiCallContext.for_worker(workspace_id=None, ...)` is rejected, so a worker cannot reach system scope through it.

### 17.2 Router and fallback

13. **AC-13.** With a fake catalog, the Router filters by capability, modality, provider configuration, context fit, quality floor, cost ceiling, availability and budget, with the reason codes in 10.2. A `quality_floor` below the task class has no effect.
14. **AC-14.** Ranking follows 10.2 step 8 for each latency class, with deterministic tie-breaks. The same inputs produce byte-identical `candidate_snapshot` across runs (INV-5).
15. **AC-15.** If the first candidate times out or returns 5xx or rate-limited, the call falls back to the next candidate. The ledger has one `failed` row for the first candidate and a `succeeded` row for the second, with correct `route_rank`.
16. **AC-16.** Error classification (E-3). A parametrized test drives the fake provider through each row of the table in 10.3 (timeout, connection error, 5xx, rate limit or quota, auth failure, bad request, content refusal, truncation, invalid output, missing credentials). For each, it asserts the persisted `error_code`, whether a fallback happens, the raised error, and the bound on attempts. Bad request and content refusal make exactly one attempt. A missing-credentials call makes zero attempts and writes no usage row.
17. **AC-17.** Billing mode (C, INV-29). With a fake catalog holding `free_tier` models A and B and a `paid` model C, all eligible:
    - when A returns a quota-exhausted response (`provider_rate_limited`), the call falls back to B and never to C;
    - when A and B both fail, `AiProviderUnavailable` is raised, C is never called, and no `ai_usage_records` row has `billing_mode='paid'`;
    - with the candidate order reversed so a `paid` model ranks first, the request never falls back to a `free_tier` model;
    - the excluded candidates carry reason code `billing_mode` in `candidate_snapshot`, and all rows of one request share one `billing_mode`.
18. **AC-18.** A `content_refused` outcome is not retried on another model. `AiContentRefused` is raised.
19. **AC-19.** Fallback is bounded at `max_provider_attempts` distinct models. When all fail, `AiProviderUnavailable` is raised and the request is `failed`.
20. **AC-20.** The circuit breaker opens after 5 consecutive failures in 60 s, closes via a half-open probe, and is driven only by `FakeClock`.
21. **AC-21.** A request with an image part for a text-only task raises `AiModalityNotSupported`. With a fake image-capable catalog entry and a fake task that declares image input, the Router selects that model (interface-ready behavior).

### 17.3 Schema enforcement and untrusted context

22. **AC-22.** A valid fake response yields an instance of the registered schema.
23. **AC-23.** An invalid response (missing field, wrong type, extra key, string-for-int) fails `strict` validation. One repair call is made to the same model (`call_kind='repair'`), and it is recorded and budget-reserved.
24. **AC-24.** If the repair is valid the request succeeds. If it is invalid the candidate fails and the Router tries the next. If all candidates fail, `AiOutputInvalid` is raised, no output is stored, `ai_requests.error_code='output_invalid'`, and the ledger has a row for every call, with the money spent kept.
25. **AC-25.** `finish_reason='length'` is recorded as `output_truncated`, is not repaired, and falls back.
26. **AC-26.** A task with an unregistered schema raises `AiTaskNotReady` and makes no provider call (INV-23).
27. **AC-27.** The total number of calls never exceeds 6 with defaults (INV-9). Test with a provider that always returns invalid output.
28. **AC-28.** Untrusted context (F-4, INV-24). With a fake provider that records the request it received, a context block contains an injection-style sentinel string (for example an instruction to ignore previous instructions and to emit a given marker):
    - the recorded provider request has the context only in the delimited data section, never in the instruction channel, and has no `tools`, `functions` or `tool_choice` parameter;
    - a context block that contains the boundary marker causes a new marker to be generated;
    - when the scripted provider "obeys" the injection and returns output that does not fit the schema, the output is rejected (repair, then fallback, then `AiOutputInvalid`), and a scripted response that fits the schema is validated before being returned;
    - the sentinel appears in no log record, event payload, audit detail, job payload, usage row (including `candidate_snapshot`), error message or problem response.

### 17.4 Cost and budget (Postgres)

29. **AC-29.** After a successful call, `ai_usage_records` has one row with units, integer micro-USD cost equal to the independently computed `ceil` formula, `price_version`, `billing_mode`, route fields and `period_start`. `ai_requests` totals equal the sum of its rows.
30. **AC-30.** Concurrency: with a workspace limit that allows exactly K calls and N ≫ K concurrent callers using separate committed sessions, exactly K succeed, N−K raise `AiBudgetExceeded`, and `reserved + spent ≤ limit` at all times (INV-10).
31. **AC-31.** Budget separation (D-1, INV-11). With workspaces A and B and the system budget all having room:
    - a burst of workspace-scope calls for A changes only A's budget row, and B's row and the system row are byte-identical before and after;
    - a burst of system-scope calls changes only the system row, and no workspace row changes;
    - exhausting A's workspace budget does not refuse system-scope calls or B's calls, and exhausting the system budget does not refuse workspace-scope calls;
    - a system-scope call for any task other than `EMBED_TEXT` is rejected before any row is written (D-15, INV-31).
32. **AC-32.** Defaults and periods: a new workspace period row is created with the configured limit (25,000,000 by default) and the system row with 100,000,000. A new UTC month starts with new rows at zero and no carry-over (using `FakeClock` across a month boundary).
33. **AC-33.** Mid-month limit change (G, D-9). With a workspace limit L1 and some spend and one in-flight reservation:
    - lowering the configured limit to L2 below `spent + reserved`: the in-flight call still settles normally (its reservation is not invalidated), and the next reservation is refused using L2 immediately;
    - raising the configured limit to L3: the next reservation that L2 would have refused is admitted immediately;
    - after each reservation or refusal the row's `limit_micro_usd` equals the last limit passed, and the decision never uses the stored value;
    - the 80 % evaluation at settlement uses the limit passed with the settlement.
34. **AC-34.** 80 % behavior (F-2, INV-15). Reservations that bring `spent + reserved` above 80 % without any settlement publish nothing. The settlement that takes settled `spent` to 80 % publishes exactly one `ai.budget_threshold_reached` and one audit record, even when several settlements cross concurrently, and calls continue.
35. **AC-35.** Refusal behavior (F-3, INV-15, D-8). With settled `spent` below 100 % but `remaining < estimate`, the next reservation is refused with `ai_budget_exceeded` (429), no provider call occurs, no usage row is written, and `ai.budget_exhausted` is published exactly once for that row and period, with `spent` below the limit in the payload. A second refusal publishes nothing more. There are no exemptions: the same applies to system-scope and workspace-scope calls. The in-flight call at the moment of refusal still settles.
36. **AC-36.** Reconciliation invariant: after a mixed workload (successes, failures, repairs, fallbacks), every period row with `reserved = 0` equals the sum of its usage records (INV-13).
37. **AC-37.** A reservation is released or settled at most once, and a double settle attempt is a no-op. A reaped `reserved` record becomes `abandoned`, is charged its estimate and releases the reservation (INV-7, INV-14).
38. **AC-38.** No lock held across a provider call (INV-6). A spy `ProviderClient`, at the moment it is invoked, opens a separate connection and runs `SELECT ... FOR UPDATE NOWAIT` on the call's `ai_budget_periods` row and on its `ai_requests` row. Both succeed, so no lock is held. It also asserts that no session of the orchestrator's `application_name` is `idle in transaction`. The test runs for `run`, the `execute_request` handler, a repair call and a fallback call.

### 17.5 Async, jobs, retention, authorization, privacy

39. **AC-39.** `submit` persists the row and `ai.request_queued` in one transaction. The `handle_once` consumer enqueues exactly one job even if the event is delivered twice. The same idempotency key and fingerprint returns the same request. The same key with a different fingerprint raises `Conflict`. Two `run` calls with identical input create two separate requests (no deduplication).
40. **AC-40.** Advisory budget pre-check at `submit` (D-14). With a workspace whose remaining budget is below the cheapest candidate's estimate, `submit` raises `AiBudgetExceeded`, persists no `ai_requests` row, publishes no event and reserves nothing. With enough remaining budget `submit` is accepted. A replay of an existing key returns the stored request without a pre-check. When the budget is consumed between `submit` and execution, the request ends `failed` with `budget_exceeded` (the reservation is the authority). A Router outcome other than the budget step (for example no route) does not block `submit`.
41. **AC-41.** Job handling: the request ends `succeeded` or `failed`, `ai.request_completed` or `ai.request_failed` is published once, and a re-delivered job is a no-op with no second provider call (INV-16). A job racing a live lease returns without effect.
42. **AC-42.** Lease and heartbeat with `FakeClock`: the claim sets a 180 s lease and `lease_epoch = 1`. A 60 s heartbeat extends it. After 180 s without a heartbeat another worker can claim. The reaper handler, invoked directly, re-enqueues, or fails with `execution_abandoned` after 5 attempts, per 8.2.
43. **AC-43.** Lease fencing (E-1, INV-28). Worker A claims (epoch 1), the clock advances past the lease, and worker B claims (epoch 2). Then:
    - A's heartbeat, A's reservation, A's settlement and A's completion each affect 0 rows and change nothing, including when A and B use the same worker identity;
    - A cancels its provider call and performs no further state change;
    - B heartbeats, settles and completes normally with epoch 2, and the request has exactly one terminal state and one set of totals;
    - A's `reserved` usage record is reaped after 360 s, becomes `abandoned` and is charged its estimate.
44. **AC-44.** Missing credentials in an async job (H). With no usable provider key, the `execute_request` handler makes no reservation and no call, ends the request `failed` with `error_code = provider_not_configured`, publishes `ai.request_failed` once, and returns normally. The queue does not retry it (no re-enqueue, no `max_attempts` consumed, nothing on `jobs:dead`). No `ai_usage_records` row exists and no budget row changes.
45. **AC-45.** Sync request lifecycle (I). For `run` and `embed_texts`:
    - a call rejected by pre-routing validation (unready task, disallowed scope, user-path restriction, modality, embedding limits) leaves no row;
    - a routed call creates one `ai_requests` row `mode='sync'`, `status='running'` before any reservation, with no lease columns and `lease_epoch = 0`, and ends it `succeeded` or `failed` with `completed_at`;
    - a budget-refused call leaves one `failed` row with `error_code='budget_exceeded'`, no usage row and no reservation, and an unroutable call leaves a `failed` row with `no_route` or `provider_not_configured`;
    - a sync row `running` for more than 420 s with a `reserved` usage record is reaped by the reaper handler: the record becomes `abandoned` and is charged its estimate, and the row becomes `failed` with `execution_abandoned`; at 419 s nothing changes;
    - the `ck_ai_requests_running_lease` constraint accepts a `running` sync row without a lease.
46. **AC-46.** Reconciliation job (E-2, INV-30). With the `reconcile_budgets` handler run directly: a row with `reserved = 0` whose `spent` is altered by test SQL to differ from its usage sum produces exactly one audit record (`ai.budget.reconciliation_mismatch`) and one structured log, both containing only ids, scope, period, bucket and counts, and the budget and usage rows are unchanged (no repair). A consistent row produces nothing. A row with `reserved > 0` is skipped and counted. `ai_budget_reconciled` logs the counts.
47. **AC-47.** Reconciliation idempotency: running the same bucket again, or two handlers concurrently for the same bucket, writes no second audit record. The next hour's bucket reports a still-mismatched row again. The job publishes no event and a captured log contains no content.
48. **AC-48.** Cron CLI (D-2). `python -m app.ai_platform.cron reap`, `reconcile` and `purge`, run against a fake Redis with `FakeClock`, enqueue exactly the matching job (`ai_platform.reap_stale_requests`, `ai_platform.reconcile_budgets`, `ai_platform.purge_expired_content`) with the UTC minute bucket for `reap` and the UTC hour bucket for the others. Two runs in the same bucket produce the same payload. An unknown argument exits non-zero and enqueues nothing. The CLI opens no database session, and its output contains only the job type and the bucket. Two instances of each periodic handler run concurrently for one bucket leave the same final state as one run.
49. **AC-49.** Purge (D-5, INV-25). With `FakeClock` and `AI_ASYNC_CONTENT_RETENTION_DAYS` at its default 30: a terminal request completed 30 days and 1 second ago has `input_payload` and `output_payload` nulled and `content_purged_at` set by `ai_platform.purge_expired_content`. A request completed 29 days 23 hours ago is untouched. A `queued` or `running` request older than 30 days is untouched. Every other `ai_requests` column, every `ai_usage_records` row and every `ai_budget_periods` row is unchanged. Rows without content are unchanged. A different configured value changes the cutoff accordingly.
50. **AC-50.** Purge idempotency and effects: re-running the same bucket, or running the next bucket, changes nothing further. A batch limit smaller than the number of expired rows is drained over successive runs. After purge `get_output` raises `NotFound` and `get_status` still returns the final status and usage. The purge emits no event and its log record contains only a count.
51. **AC-51.** Request-path restriction (D-7, INV-26). `run` with a `from_workspace` (user) context and the `interactive` task `GENERATE_HOOK_VARIATIONS` succeeds. The same call with any non-interactive task raises `ValidationFailed` with the detail `This AI task must be submitted asynchronously`, with no usage row, no reservation and no provider call. The same non-interactive task succeeds via `for_worker` and via `submit`.
52. **AC-52.** Authorization and privacy:
    - A tenant-isolation test registers both endpoints and a non-member gets 404 (`WORKSPACE_SCOPED_ROUTES`).
    - OWNER and ADMIN get 200 and MEMBER gets 403 (D-6).
    - `get_status` and `get_output` with another workspace's request id raise `NotFound`.
    - System-scope rows are absent from workspace reports.
    - Captured logs, events, audit rows, job payloads and error responses of a full run (success, schema failure, budget refusal) contain none of the test prompt, completion or output strings and no `token`-named key (INV-18, INV-19, INV-20).
53. **AC-53.** `embed_texts` with the fake provider returns vectors of length 1024, `embedding_model="text-embedding-3-small"`, `embedding_version="v1-d1024"`, and records usage against the budget row of the context's scope. Empty batches, oversize batches and oversize texts are rejected, and there is no fallback model (INV-12).

### 17.6 Real-provider smoke test (separate, small)

Marker `ai_live`. It is excluded from `scripts/check.py` and from `just test-db`, and it only runs when `AI_LIVE_TESTS=1` and the needed provider key is present in the ignored `.env.test.local`. It runs against the test database. Keys never appear in output.

Operational prerequisites (not code, section 20.3): a dedicated Google project with billing disabled for the Gemini key; a dedicated OpenAI test key with a provider-side hard spend limit (subject to OQ-2). The tests send **synthetic text only**, never real user data. The Gemini free tier may allow the provider to use submitted content. The owner must verify Google's current terms before any real user content is ever sent to it.

54. **AC-54.** *Spend cap (INV-27, D-11).* The 20 USD total across all test runs is enforced by two controls:
    - a provider-side hard spend limit on the dedicated paid-provider test key (the one control the code cannot bypass), and a Google project with billing disabled;
    - a cumulative counter kept **outside the test database transaction**, in a git-ignored local ledger file (the implementation adds it to `.gitignore`). After each real call the fixture adds the catalog-computed cost in integer micro-USD. Before each real call the fixture aborts the test if the cumulative total plus that call's worst-case estimate would pass 20 USD, and a per-session guard aborts the remaining tests if the session total passes 2 USD.
    The suite documents the key it expects and never uses a production key. It is designed to cost far below 1 USD: at most 3 provider calls, `max_output_units ≤ 300`, and texts of at most a few sentences.
55. **AC-55.** One real `embed_texts` call over 3 short synthetic strings returns 3 vectors of length 1024, `embedding_version="v1-d1024"`, usage > 0 and cost > 0 in the ledger. This test needs an OpenAI key, a paid provider, and runs only if OQ-2 is resolved to option (a).
56. **AC-56.** One real task call through the Router with Gemini (a cheap `interactive` task using a test-only schema) returns a strictly valid output, writes a ledger row whose recorded cost matches the catalog formula for the provider-reported units, and increases the workspace budget's `spent`. A quota-exhausted response from the free tier is a failed attempt (`provider_rate_limited`) and never triggers a paid call.
57. **AC-57.** The same run's captured logs contain no prompt or completion text and no key (INV-18, INV-20). The test fails if the output contains the sentinel strings used in the prompt.

### 17.7 Invariant-to-AC mapping

| Invariant | Acceptance criteria |
| --- | --- |
| INV-1 | AC-1 |
| INV-2 | AC-3 |
| INV-3 | AC-2 |
| INV-4 | AC-9 |
| INV-5 | AC-14 |
| INV-6 | AC-38 |
| INV-7 | AC-15, AC-29, AC-37 |
| INV-8 | AC-22, AC-23, AC-24 |
| INV-9 | AC-27 |
| INV-10 | AC-30, AC-33 |
| INV-11 | AC-31 |
| INV-12 | AC-53, AC-55 |
| INV-13 | AC-36, AC-46 |
| INV-14 | AC-29, AC-37, AC-43 |
| INV-15 | AC-34, AC-35 |
| INV-16 | AC-41 |
| INV-17 | AC-42, AC-43 |
| INV-18 | AC-6, AC-28, AC-52, AC-57 |
| INV-19 | AC-52 |
| INV-20 | AC-7, AC-52, AC-57 |
| INV-21 | AC-10 |
| INV-22 | AC-11, AC-42, AC-48 |
| INV-23 | AC-26 |
| INV-24 | AC-28 |
| INV-25 | AC-49, AC-50 |
| INV-26 | AC-51 |
| INV-27 | AC-54 |
| INV-28 | AC-43 |
| INV-29 | AC-17 |
| INV-30 | AC-46, AC-47 |
| INV-31 | AC-12, AC-31 |

## 18. Non-goals

- Billing, plans, invoices, quotas by plan, payment, or charging users. (`billing_usage` is a later, conditional phase.) Cost metering and budget enforcement are the only monetary scope here.
- Per-workspace budget overrides, a budget admin UI, or a system-level usage endpoint (D-9; `admin_ops` is Phase 9).
- Context assembly, retrieval, ranking, and token budgeting of context (`context_engine`, `rag`).
- Storing embeddings or chunks, and the embedding job itself (`rag`).
- Domain output schema bodies and domain prompt content (the owning modules; D-6).
- Tool or function calling.
- Enabling an OpenAI chat model or an Anthropic adapter. The catalog format allows adding them later (10.1).
- Falling back from a `free_tier` model to a `paid` model, or switching billing mode (INV-29).
- Real image, video or audio adapters, models or tasks. Media storage (`content_asset`).
- Streaming partial output to clients (D-12).
- Fine-tuning, model evaluation harnesses and AI output evals (`delivery`, Phase 9).
- Human-in-the-loop review of outputs (`human_feedback`, `brief`, and so on).
- A distributed circuit breaker, a multi-region router, or Kafka.
- A generic public "run AI task" HTTP endpoint.
- A generic scheduler in `jobs_workers` (a documented future option, 8.5) or the cron configuration itself. The local-database test mode is prerequisite P-2.
- Controlling database backup and WAL / point-in-time-recovery retention (8.3, section 20.3).
- Data export or deletion workflows beyond the 30-day content purge (`security_compliance`).
- Content in languages other than English. Content is always English.

## 19. Open Questions

These are the open gaps. None is decided. Each lists options and a recommendation. Where the body of the spec needs a value to stay testable, it carries a **provisional** marker pointing here. Questions decided by the owner are in section 20.

**OQ-1. Which Gemini models fill each quality tier?**
D-4 fixes Gemini as the only chat provider but does not name the models. The catalog needs at least a `standard` and a `high` tier, and ideally a `basic` tier.
- (a) One cheaper and one stronger Gemini model.
- (b) A single Gemini model, with the `high` tier initially empty.
- (c) The owner names the models at implementation time.
- *Recommendation:* (a), chosen at implementation time against Google's current official documentation (model list, context windows, pricing, free-tier terms and quotas), recording source URL and date in the catalog. No prices or limits are written from memory. The smoke test uses the cheapest eligible model.

**OQ-2. How is the real embedding smoke test (AC-55) paid for?**
`text-embedding-3-small` is an OpenAI model, and OpenAI is a paid provider. Gemini is run from a Google project with billing disabled, so the embedding test is the only real call that needs a paid key.
- (a) A dedicated OpenAI test key with a provider-side hard spend limit.
- (b) Skip the real embedding test and run only the real Gemini task test.
- (c) Use the fake provider only for embeddings.
- *Recommendation:* (a). It tests the one real path whose model and dimension are fixed, and the provider-side limit keeps the 20 USD cap safe.

**OQ-3. Should usage rows survive hard deletion of a workspace or request?**
Section 7 and the retention rules say usage rows are accounting history and are retained. In 4.1 to 4.3, `ai_requests.workspace_id`, `ai_usage_records.request_id`, `ai_usage_records.workspace_id` and `ai_budget_periods.workspace_id` use `ON DELETE CASCADE`. A hard delete would remove the history.
- (a) Keep the cascade. Workspace deletion is soft today (`deleted_at`), and hard deletion and export belong to `security_compliance`, so nothing in this phase deletes these rows.
- (b) Use `SET NULL` or no foreign key on the usage and budget tables. This needs `workspace_id` and `request_id` to be nullable and the `scope_workspace` check to change.
- (c) Archive the rows to a retained table, or export them, before any hard delete.
- *Recommendation:* (a) for this phase, and let `security_compliance` choose between (b) and (c) when it defines hard deletion.

**OQ-4. What happens to the notification flags and `state` when the limit changes mid-month?**
Limits are read from configuration at each reservation (D-9). The 80 % and refusal events are once per budget row and period (INV-15). The spec provisionally never resets `warning_notified_at` or `exhausted_notified_at`, and `GET /budget` `state` still reports `exhausted` after a raise if a call was refused earlier in the month (section 6).
- (a) Never reset the flags (events stay once per period), and compute `state` from the current limit: `exhausted` when `spent + reserved >= limit`, `warning` at 80 % of `spent`, else `ok`. The flags keep only their event role.
- (b) Reset `warning_notified_at` and `exhausted_notified_at` when the limit is raised above current usage, so the events can fire again.
- (c) Keep the provisional behavior in the spec (flags never reset, flag still drives `state`).
- *Recommendation:* (a). It keeps INV-15 intact and shows the user a state that matches the limit in force.

## 20. Decisions

The owner's decisions, applied as decided. D-1 came from the review. D-2 to D-13 were Open Questions in the first draft (the former number is shown). Revision 2 changed D-2, D-4, D-5, D-9 and D-11, and added D-14 and D-15 (their "was OQ" numbers are first-draft numbers).

### 20.1 Decisions

| ID | Decision | Rationale |
| --- | --- | --- |
| D-1 (new) | The 100 USD system budget is a separate budget used only by system-scope calls (for example embedding GLOBAL knowledge). Workspace-scope calls count only against their own 25 USD workspace budget and never touch the system row. | Tenant spend cannot drain platform-level work, and a call reserves against one row, which removes double reservation and lock ordering. |
| D-2 (was OQ-1; rev 2) | No generic scheduler is built. An external cron runs `python -m app.ai_platform.cron <reap\|reconcile\|purge>`, which enqueues the matching job with a UTC bucket (minute for reap, hour for reconcile and purge). Jobs are idempotent per bucket and safe under concurrent runs. A generic scheduler in `jobs_workers` stays a documented future option, not a prerequisite. | It avoids a new platform component before it is needed, and idempotent bucketed jobs make an external trigger safe. |
| D-3 (was OQ-2) | The budget period is the UTC calendar month for both budgets, with no carry-over. | Simple, deterministic with `Clock`, and it matches the monthly wording. |
| D-4 (was OQ-3; rev 2) | Chat uses **Gemini only**, through LiteLLM. OpenAI is used **only** for `text-embedding-3-small` (1024 dimensions, `v1-d1024`). No OpenAI chat model and no Anthropic adapter is enabled, and the catalog format allows adding them later without domain changes. Each catalog model has a `billing_mode` (`free_tier` or `paid`). The Router never falls back from a `free_tier` candidate to a `paid` candidate and never switches billing mode, and a quota-exhausted response is a failed attempt (`provider_rate_limited`). Prices live in the in-repo catalog with `price_version`, are verified against the provider's official pages at implementation time, and are not written in this spec. | A single chat provider keeps the first release small, a free-to-paid switch could create spend nobody approved, and prices from memory would go stale. |
| D-5 (was OQ-4; rev 2) | Stored async input/output content is purged **30 days** after completion by `ai_platform.purge_expired_content` v1, configured by `AI_ASYNC_CONTENT_RETENTION_DAYS` (default 30). Database backup and WAL retention are outside application control and must be reviewed against the privacy policy before production. | A bounded retention window limits stored user content while keeping the metadata needed for accounting, and backups are an operational concern the code cannot enforce. |
| D-6 (was OQ-5) | Domain modules own and version their prompts. `ai:usage_read` is for OWNER and ADMIN only. | Prompts encode domain knowledge, and cost visibility is a management concern. |
| D-7 (was OQ-6) | `run()` is allowed from a user request path only for `interactive` tasks. Otherwise it raises `ValidationFailed` with a fixed message. | Long AI work must not block API requests (§53). |
| D-8 (was OQ-7) | No exemptions at 100 %. | One rule for every call keeps spend predictable. |
| D-9 (was OQ-8; rev 2) | Budget limits come from config only in this phase, as `AI_WORKSPACE_MONTHLY_BUDGET_USD` (default 25) and `AI_SYSTEM_MONTHLY_BUDGET_USD` (default 100), converted to integer micro-USD with `Decimal`, never `float`. Each reservation receives the current configured limit as a parameter, and the row stores the last limit seen for display. Per-workspace overrides are deferred to `admin_ops` (Phase 9). | An editable per-workspace limit edges toward plans and billing, and a parameter makes a config change apply at once without invalidating reservations. |
| D-10 (was OQ-9) | A separate small task in `db_migrations` adds an explicit local-database mode to the test guard without weakening the Neon checks. Fake-provider tests run on a local Postgres container by default and on the Neon test branch nightly, never on dev or production. | The existing guard is label-based and Neon-specific, and it must not be loosened. |
| D-11 (was OQ-10; rev 2) | The 20 USD real-provider cap is enforced by a provider-side hard spend limit on a dedicated paid-provider test key and a dedicated Google project with billing disabled (operational prerequisites, not code), a cumulative counter in a git-ignored local ledger file kept outside the test database transaction, and a 2 USD per-session guard. Tests send synthetic text only. | The provider-side limit is the one control the code cannot bypass, the ledger file survives test rollbacks, and free-tier terms may allow the provider to use submitted content. |
| D-12 (was OQ-11) | No streaming in this phase. | Strict schema validation needs the full output. |
| D-13 (was OQ-12) | A missing provider key raises `ConfigurationError` (`AiProviderNotConfigured`) at call time. A readiness helper (`check_ai_providers`) is exported for `rag` to call at startup. In an async job a missing key ends the request `failed` with `provider_not_configured` and is not retried. | It matches core's "fail at the point of use" configuration philosophy, and a retry cannot fix a missing key. |
| D-14 (was OQ-2 of rev 1) | `submit` makes an advisory budget pre-check and raises `AiBudgetExceeded` when the budget step removes the last candidate. The atomic reservation at execution stays the authority. | The user learns immediately instead of waiting for a failed job, while one authority prevents disagreement. |
| D-15 (was OQ-3 of rev 1) | System scope is allowed only for `EMBED_TEXT`. Widening it needs a spec change. Only code under `app/ai_platform/` and `app/rag/` may construct a system `AiCallContext`, enforced by an architecture test. | A system context has no workspace, so unrestricted use would let a feature bypass its workspace budget. |

Review fixes F-1 to F-6 are applied in sections 4, 5, 7, 11, 12, 16 and 17, and the fixed decisions listed in F-6 are unchanged. Revision 2 also applies three review items: lease fencing (E-1, 8.1, INV-28), the budget reconciliation job (E-2, 8.4, INV-30) and the error classification table (E-3, 10.3).

### 20.2 Prerequisite (a separate task, before `ai_platform` implementation)

- **P-2 (D-10).** An explicit local-database mode in the `db_migrations` test guard, with the Neon branch and endpoint checks unchanged, and a local Postgres container image that includes pgvector.

There is no scheduler prerequisite (D-2).

### 20.3 Operational prerequisites (not code)

- An external cron is configured to run the three CLI commands in 8.5 at the cadence given there.
- A dedicated Google project with billing disabled exists for the real-provider tests.
- If OQ-2 is resolved to option (a), a dedicated OpenAI test key exists with a provider-side hard spend limit.
- Before production, database backup and WAL / point-in-time-recovery retention are reviewed against the privacy policy (8.3).
- Before any real user content is sent to the Gemini free tier, the owner verifies Google's current terms on use of submitted content.

## Frontend

To be added by the FE task. The UI slice in section 14 defines its minimum scope.

## Public interfaces and events later features must use

- Import everything from `app.ai_platform`: the types in 5.1–5.5, `AiCallContext`, `AiTaskRequest`, `AiOrchestrator`, `EmbeddingService`, `AiBudgetService`, `AiUsageService`, `AiTaskRegistry`, `OutputSchemaRegistry`, the `Ai*` errors (including `AiProviderNotConfigured`), `AiPlatformConfig`, `check_ai_providers`, `FakeAiProvider`, `EMBEDDING_MODEL`, `EMBEDDING_DIMENSIONS`, `EMBEDDING_VERSION`, `build_ai_platform`, `register_jobs`, `register_event_handlers` and `register_routes`.
- Request AI work by task name only. Never pass or reference a provider or model. Register the output schema you own with `OutputSchemaRegistry.register` at startup. Own and version your prompts.
- Build `AiCallContext` from a verified `WorkspaceContext` (`from_workspace`) or from persisted data in workers (`for_worker`, which always needs a workspace). Never from client input. Only `ai_platform` and `rag` may build a system context. On a user request path use `run` only for `interactive` tasks; otherwise use `submit`. Only `submit` takes an idempotency key.
- Events (all v1): `ai.request_queued`, `ai.request_completed`, `ai.request_failed`, `ai.budget_threshold_reached`, `ai.budget_exhausted`. IDs, counts, codes and micro-USD amounts only. No content, no `token`-named keys.
- Jobs: `ai_platform.execute_request` v1 (lease 180 s, heartbeat 60 s, fenced by `lease_epoch`), `ai_platform.reap_stale_requests` v1, `ai_platform.purge_expired_content` v1 and `ai_platform.reconcile_budgets` v1. The last three are triggered by an external cron through `python -m app.ai_platform.cron <reap|reconcile|purge>`. `rag` owns its embedding job and calls `EmbeddingService.embed_texts`; it must defer and retry on `AiBudgetExceeded` (5.7).
- Endpoints: `GET /api/v1/workspaces/{workspace_id}/ai/budget` and `GET /api/v1/workspaces/{workspace_id}/ai/usage`, permission `ai:usage_read`.
- AI tasks: the eight §44 tasks in section 9, plus the internal `EMBED_TEXT`.
