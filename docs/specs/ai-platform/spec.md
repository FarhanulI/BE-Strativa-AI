# AI Platform Module Specification

Status: draft for review. Authored 2026-11-01 from `docs/product-architecture.md` and `docs/modules.md` (the sources of truth) and from the real Phase 0/1 code. It is a new specification, not a restoration of any earlier `ai_platform` spec.

Items marked **(provisional — OQ-n)** use a working value so that the spec stays testable. The value is not a decision. See section 19. Acceptance criteria that depend on a provisional value say so.

## Backend

## 1. Purpose

`ai_platform` is the only module that talks to AI providers. Business modules request an **AI task** by name. `ai_platform` turns the request into one or more provider calls and returns output that is validated against a registered schema. It enforces and records cost, and it never lets a business module choose a provider or model.

It provides:

- the AI Orchestrator (task execution, sync and async),
- the AI Router (provider/model selection, fallback),
- provider abstraction through LiteLLM,
- the task registry and the capability model (task ≠ capability),
- strict output-schema enforcement,
- cost metering and budget enforcement (per workspace and system-wide),
- the text embedding service used by `rag`,
- multimodal-ready interfaces.

It does not build context (that is `context_engine`), retrieve knowledge (`rag`), own domain output schemas, or bill anyone.

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
| | Supporting: §5, §58 P23, §62 | Workspace-centric authorization, workspace as tenant boundary, and the simple/deterministic/traceable/testable preference. |
| `modules.md` | Phase 2 `ai_platform` line | "AI Orchestrator, AI Router, provider abstraction (LiteLLM), task vs capability registry, strict output-schema enforcement, token cost accounting, multimodal-ready interfaces". |
| `modules.md` | Module rules | A spec must include the sections listed in this document. Modules communicate only through public interfaces or outbox events. |
| `modules.md` | Phase 0 `observability_audit` line | AI usage and cost tracking is listed there. The `observability_audit` spec defers "AI token/cost accounting before AI tasks exist". This module therefore owns the ledger and uses `observability_audit` for logs and audit. |

### Context-engine boundary (§46)

- `ai_platform` accepts a caller-built list of `AiContextBlock` values. Each block has text and an optional opaque `source_id` for lineage.
- `ai_platform` never queries `rag`, never reads profile or intelligence data, and never decides what context is relevant.
- Token budgeting of the context belongs to `context_engine`. `ai_platform` only rejects a request whose estimated input does not fit any eligible model, with `ai_input_too_large`. It does not trim or summarize input.

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
| Jobs | `app.jobs_workers`: `JobEnvelope(job_id, job_type, job_version, payload, metadata, attempt)`, `JobRegistry.register(type, version, handler)`, `JobQueue(redis, stream="jobs", dead_letter_stream="jobs:dead", max_attempts=5)`, `JobQueue.enqueue`, `EventWorker`, `OutboxRelay`. Retry backoff is `min(300, 2**attempt)` s. |
| Audit/logs | `app.observability_audit`: `AuditRecord`, `append_audit(session, record)` (caller transaction, no commit), `configure_logging`, `redact_sensitive_values`. `AuditRecord.details` rejects the same sensitive-key family, and the log redactor replaces such keys with `[REDACTED]`. |
| RBAC | `app.workspace`: `WorkspaceContext(user_id, workspace_id, role)`, `WorkspaceRole`, `WorkspacePermission`, `ROLE_PERMISSIONS` (the single extension point), `WorkspaceAccessService.authorize`, `require_workspace_permission`. Non-member gets 404, member lacking permission gets 403. |
| API | `app.api_contract.app.create_app`; features expose `register_routes(app)`; routes live under `/api/v1/workspaces/{workspace_id}/...`; tenant-isolation harness `tests/helpers/tenant_isolation.py` (`WORKSPACE_SCOPED_ROUTES`). |
| Boundary test | `tests/unit/architecture/test_module_boundaries.py` rejects any import of `app.<other_module>.<submodule>`. Only package-root exports can be used across modules. |

**Consequence of the key-name regex.** Provider "tokens" are the billing unit of LLM providers, but the word `token` is rejected in event payload keys and audit details and is redacted in logs. This spec therefore calls them **units**. `input_units` and `output_units` are used in DB columns, events, logs, audit details, API fields and Python names. The provider adapter is the only place that maps provider usage fields onto these names.

## 3. Owned entities

- `AiRequest`: one logical request to run an AI task (sync or async). It is the unit of idempotency and of lease/heartbeat.
- `AiUsageRecord`: one row per provider call attempt (generation, repair, embedding). It is the cost ledger and carries the routing record.
- `AiBudgetPeriod`: per-scope, per-month budget counters (spent, reserved, limit, threshold flags). Scopes are `workspace` and `system`.
- Non-persistent contracts:
  - `AiTaskDefinition`, `AiTaskRegistry`, `AiCapability`, `AiModality`, and the quality/latency/cost classes.
  - `OutputSchemaRegistry`.
  - `ModelCatalog` (in-repo versioned data: models, capabilities, modalities, quality tier, context window, price per unit, latency estimate).
  - `AiRouter`, `AiOrchestrator`, `EmbeddingService`, `ProviderClient` (internal).
  - `AiCallContext`, `AiTaskRequest`, `AiTaskResult`.
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
| `output_schema_name` | text not null | |
| `output_schema_version` | int not null | |
| `mode` | text not null | `sync` \| `async` |
| `status` | text not null | `queued` \| `running` \| `succeeded` \| `failed` |
| `idempotency_key` | uuid null | caller-supplied; required for `async` |
| `request_fingerprint` | char(64) not null | SHA-256 over the canonical request. The same key with a different fingerprint is a `Conflict`. |
| `input_payload` | jsonb null | present only for `async` (the worker needs it). **Content.** Never logged, evented or put in errors. |
| `output_payload` | jsonb null | validated output; present for `async`, and for `sync` only when `persist_result=True`. **Content.** |
| `content_purged_at` | timestamptz null | reserved for the retention policy (OQ-4). No purge job is built in this phase. |
| `error_code` | text null | one of the fixed codes in 5.4 |
| `attempt_count` | int not null default 0 | job executions started |
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
- `ck_ai_requests_nonneg`: `input_units >= 0 AND output_units >= 0 AND cost_micro_usd >= 0 AND attempt_count >= 0`.
- `ck_ai_requests_async_key`: `mode <> 'async' OR idempotency_key IS NOT NULL`.
- `ck_ai_requests_running_lease`: `status <> 'running' OR (lease_owner IS NOT NULL AND lease_expires_at IS NOT NULL)`.
- `ck_ai_requests_terminal_completed`: `status NOT IN ('succeeded','failed') OR completed_at IS NOT NULL`.

Indexes:

- `uq_ai_requests_workspace_idempotency`: unique `(workspace_id, idempotency_key)` WHERE `idempotency_key IS NOT NULL AND workspace_id IS NOT NULL`.
- `uq_ai_requests_system_idempotency`: unique `(idempotency_key)` WHERE `scope = 'system' AND idempotency_key IS NOT NULL`.
- `ix_ai_requests_workspace_id_id`: `(workspace_id, id)`, for cursor listing in UUIDv7 order.
- `ix_ai_requests_running_lease`: `(lease_expires_at)` WHERE `status = 'running'` (reaper).
- `ix_ai_requests_queued_at`: `(queued_at)` WHERE `status = 'queued'` (reaper).

### 4.2 `ai_usage_records`

| Column | Type | Notes |
| --- | --- | --- |
| `id` | uuid PK | UUIDv7 |
| `request_id` | uuid not null | FK `ai_requests.id` ON DELETE CASCADE |
| `attempt_no` | int not null | 1-based sequence of calls within the request |
| `scope`, `workspace_id` | as in 4.1 | denormalized for aggregation. Same check constraint. |
| `task` | text not null | |
| `call_kind` | text not null | `generation` \| `repair` \| `embedding` |
| `provider` | text not null | e.g. catalog provider id |
| `model` | text not null | catalog model id |
| `catalog_version` | text not null | |
| `price_version` | text not null | |
| `routing_version` | text not null | |
| `route_rank` | int not null | 1 = the Router's first choice |
| `candidate_snapshot` | jsonb not null | ordered list of `{model, eligible, reason_code}` (ids and codes only, no content) |
| `status` | text not null | `reserved` \| `succeeded` \| `failed` \| `abandoned` |
| `error_code` | text null | |
| `finish_reason` | text null | `stop` \| `length` \| `content_filter` \| other provider value |
| `input_units`, `output_units` | bigint null | null until settled |
| `reserved_micro_usd` | bigint not null | amount reserved against the budgets |
| `cost_micro_usd` | bigint not null default 0 | settled actual cost |
| `schema_valid` | boolean null | null for `embedding` and for calls that did not reach validation |
| `validation_error_count` | int null | |
| `validation_error_types` | jsonb null | Pydantic error type names only (for example `missing`), never values or text |
| `latency_ms` | int null | |
| `period_start` | date not null | UTC month of `started_at` (**provisional — OQ-2**) |
| `started_at` | timestamptz not null | |
| `finished_at` | timestamptz null | |
| `created_at` | timestamptz not null | |

Constraints:

- `uq_ai_usage_records_request_attempt`: unique `(request_id, attempt_no)`.
- `ck_ai_usage_records_scope_workspace`: same rule as 4.1.
- `ck_ai_usage_records_status`, `ck_ai_usage_records_call_kind`: value lists.
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
| `period_start` | date not null | first day of the budget month (**provisional — OQ-2**) |
| `limit_micro_usd` | bigint not null | copied from config at row creation: 25,000,000 for workspace, 100,000,000 for system |
| `reserved_micro_usd` | bigint not null default 0 | in-flight worst-case estimates |
| `spent_micro_usd` | bigint not null default 0 | settled actual cost |
| `warning_notified_at` | timestamptz null | set once when 80 % is first crossed |
| `exhausted_notified_at` | timestamptz null | set once when 100 % is first reached |
| `created_at`, `updated_at` | timestamptz not null | |

Constraints:

- `ck_ai_budget_periods_scope_workspace`: same rule as 4.1.
- `ck_ai_budget_periods_nonneg`: `limit_micro_usd >= 0 AND reserved_micro_usd >= 0 AND spent_micro_usd >= 0`.

Indexes:

- `uq_ai_budget_periods_workspace_period`: unique `(workspace_id, period_start)` WHERE `scope = 'workspace'`.
- `uq_ai_budget_periods_system_period`: unique `(period_start)` WHERE `scope = 'system'`.

Rows are created lazily with `INSERT ... ON CONFLICT DO NOTHING` followed by the conditional update in 12.3.

### 4.4 Not stored

- No prompt/completion text on `ai_usage_records`, and none on `ai_requests` unless the rules in 4.1 apply.
- No provider API keys (environment only).
- No model catalog table (the catalog is versioned in-repo data).
- No circuit-breaker state (it is in-process, see section 10).

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
    def for_worker(cls, *, workspace_id: UUID | None, request_id: str) -> AiCallContext: ...
    @classmethod
    def system(cls, *, request_id: str) -> AiCallContext: ...

class AiContextBlock(BaseModel):      # extra="forbid", frozen
    text: str
    source_id: str | None = None      # opaque lineage reference (§43), never interpreted

class AiTaskRequest(BaseModel):       # extra="forbid", frozen
    task: AiTaskName
    instructions: str                 # task prompt text built by the calling domain module
    context: list[AiContextBlock] = []
    parts: list[AiPart] = []          # multimodal input (13); empty for text-only tasks
    output_schema_version: int | None = None   # None = registry default
    max_output_units: int | None = None        # may only lower the task default
    quality_floor: QualityClass | None = None  # may only raise the task's class
    persist_result: bool = False               # sync only
```

`AiTaskRequest` has no field that can name a provider or model (INV-2).

The `AiCallContext` constructors are the only way to build a context:

- `from_workspace` accepts a `WorkspaceContext` that came from `require_workspace_permission` or `WorkspaceAccessService.authorize`. A bare `workspace_id` taken from client input is never accepted.
- `for_worker` is for workers and event handlers. Its `workspace_id` must come from persisted data (an event envelope or a DB row), never from client input.
- `system` is for platform work with no workspace.

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
    async def run(self, ctx: AiCallContext, request: AiTaskRequest,
                  *, idempotency_key: UUID | None = None) -> AiTaskResult: ...
    async def submit(self, ctx: AiCallContext, request: AiTaskRequest,
                     *, idempotency_key: UUID) -> AiRequestStatus: ...
    async def get_status(self, ctx: AiCallContext, request_id: UUID) -> AiRequestStatus: ...
    async def get_output(self, ctx: AiCallContext, request_id: UUID) -> BaseModel: ...
```

- `run` executes in the caller's await. It is intended for workers and for tasks with latency class `interactive` (OQ-6). It writes `ai_requests` and `ai_usage_records` in its own short transactions (see "Transaction ownership").
- `submit` persists the request (`status=queued`, `mode=async`, `input_payload`) and an `ai.request_queued` outbox event in one transaction. The job is created by the event consumer (sections 7, 8). It returns the existing request when the same `idempotency_key` and fingerprint is replayed, and raises `Conflict` for a key reuse with a different fingerprint.
- `get_status` and `get_output` raise `NotFound` when `request.workspace_id != ctx.workspace_id`. They never reveal that the request exists.
- `get_output` raises `Conflict` if the request is not `succeeded`, and raises `NotFound` if the content has been purged.

**Transaction ownership (deliberate deviation from "caller owns the session").** `ProfileService` and similar services use the caller's session and never commit. `ai_platform` cannot, for three reasons:

- A provider call must not run inside a long caller transaction holding row locks.
- Budget reservations must be visible to concurrent calls immediately.
- Money that was spent must persist even if the caller later rolls back.

The orchestrator is therefore constructed with an `async_sessionmaker` (the same pattern as `workspace.register_jobs(registry, session_factory)` and `EventWorker(sessions, ...)`) and opens its own short transactions. Each transaction is only a reservation, a settlement, or a request-state change. No provider call happens inside a DB transaction.

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
    async def embed_texts(self, ctx: AiCallContext, texts: Sequence[str],
                          *, idempotency_key: UUID | None = None) -> EmbeddingBatch: ...
```

- The service rejects an empty batch, a batch larger than 128 texts, an empty text, or a text whose estimated input exceeds the model limit of 8,191 units, all with `ValidationFailed` (`ai_input_too_large` or `validation_failed`).
- The model is requested with `dimensions=1024`.
- There is no fallback to another embedding model (INV-12). Vectors from different models or dimensions are not comparable.
- `embedding_model` and `embedding_version` are what `rag` persists per chunk (§54).
- If `Settings.embedding_dim` is set and is not 1024, `ai_platform` startup validation raises `ConfigurationError`.
- It is a platform call (`EMBED_TEXT`). It is metered like any other call. It is synchronous inside the caller's worker. `rag` owns the embedding job.

### 5.4 Errors (all `DomainError` subclasses; fixed `detail` strings, never provider or user text)

| Class | Base / status | `code` | When |
| --- | --- | --- | --- |
| `AiBudgetExceeded` | `RateLimited` / 429 | `ai_budget_exceeded` | Workspace or system budget cannot cover the call. |
| `AiNoRoute` | `ExternalServiceError` / 502 | `ai_no_route` | No catalog model passes the Router's filters (not because of budget). |
| `AiProviderUnavailable` | `ExternalServiceError` / 502 | `ai_provider_unavailable` | All attempted candidates failed transiently. |
| `AiOutputInvalid` | `ExternalServiceError` / 502 | `ai_output_invalid` | Schema enforcement failed finally (section 11). |
| `AiContentRefused` | `ExternalServiceError` / 502 | `ai_content_refused` | Provider refused or filtered. No fallback. |
| `AiInputTooLarge` | `ValidationFailed` / 422 | `ai_input_too_large` | Estimated input fits no eligible model (or the embedding limit). |
| `AiModalityNotSupported` | `ValidationFailed` / 422 | `ai_modality_not_supported` | A part's modality is outside the task definition or no catalog model supports it. |
| `AiTaskNotReady` | `DomainError` / 503 | `ai_task_not_ready` | The task's output schema is not registered. |

The persisted `error_code` values on `ai_requests` and `ai_usage_records` are:

- `provider_timeout`
- `provider_rate_limited`
- `provider_unavailable`
- `provider_auth_failed`
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

def build_ai_platform(settings: Settings, sessions: async_sessionmaker, *, clock: Clock,
                      provider: ProviderClient | None = None) -> AiPlatform: ...
def register_jobs(registry: JobRegistry, ai: AiPlatform) -> None: ...
def register_event_handlers(ai: AiPlatform) -> Mapping[str, EventHandler]: ...
def register_routes(app) -> None: ...
```

- `AiBudgetService` and `AiUsageService` take a workspace-scoped `AiCallContext`. Callers must already have passed the `ai:usage_read` check (section 15).
- A domain module registers the output schema it owns with `OutputSchemaRegistry.register(...)` at startup. This is how a task becomes ready. `AiTaskRegistry` is owned by `ai_platform`.
- `FakeAiProvider` and `ScriptedResponse` are exported from the package root for other modules' tests (the boundary test forbids `app.ai_platform.testing`-style deep imports).

### 5.6 What is NOT exposed

- LiteLLM, any provider SDK type, the model catalog, router internals, circuit-breaker state, and provider/model identifiers in results or exceptions.
- Any way to choose, pin, exclude or prefer a provider or model per call. A per-call model override does not exist.
- Any way to mutate budgets, price tables or routing rules.
- ORM classes of `ai_*` tables. Other modules must not query these tables. Reads go through the services above.
- Raw provider responses, prompts or completions, other than the validated output for the owning domain module.
- API-key material of any kind.

## 6. OpenAPI endpoints

`ai_platform` does not expose an endpoint to run tasks. Business modules own their user-facing endpoints, authorize the user, and call the orchestrator. A generic "run AI" endpoint would let clients bypass domain authorization and domain output shapes.

It exposes two **read-only** endpoints so that workspace OWNER/ADMIN can see the effect of budget enforcement. Prefix: `/api/v1/workspaces/{workspace_id}/ai`. Both use `require_workspace_permission(WorkspacePermission.AI_USAGE_READ)` and are registered in the tenant-isolation harness.

| Method and path | Permission | Behavior |
| --- | --- | --- |
| `GET /budget` | `ai:usage_read` | Current-month budget status for this workspace. |
| `GET /usage?period=YYYY-MM&group_by=task\|model\|day` | `ai:usage_read` | Aggregated usage for one month; default is the current month, default group is `task`. Past months with data are allowed. A future month returns 422. |

`GET /budget` response `AiBudgetStatus`:

- `currency` (the constant `"USD"`)
- `period_start`
- `limit_micro_usd`
- `spent_micro_usd`
- `reserved_micro_usd`
- `remaining_micro_usd` (`max(0, limit - spent - reserved)`)
- `percent_used` (integer, `floor(100 * (spent + reserved) / limit)`)
- `state`: `ok` (< 80), `warning` (80–99), `exhausted` (≥ 100)

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
- No payload carries content (prompts, completions, user text, schema output).
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
- Budget events are emitted for both modes, exactly once per scope, period and threshold (INV-15).

**Events in.** `ai_platform` consumes only its own `ai.request_queued`, through `handle_once` with consumer name `ai_platform.request_queued`. The handler enqueues the `ai_platform.execute_request` job. This is the §53 pattern: persist canonical data, emit an event, and a worker picks it up. It also makes enqueue failure recoverable, because the outbox relay retries. `ai_platform` consumes no other module's events in this phase:

- `workspace.deleted` is a soft delete. New calls for a workspace that no longer exists fail at the caller's `WorkspaceAccessService.authorize`.
- Usage rows are accounting history and are retained.
- Data deletion and export are Phase 9 `security_compliance`.

## 8. Jobs

Handlers are registered with `JobRegistry.register(job_type, version, handler)`. Job payloads and metadata contain identifiers only (no content, no keys). `metadata` carries `request_id` and `traceparent` so the worker's `RequestContext` and log correlation continue the originating request.

### 8.1 `ai_platform.execute_request` v1

- **Payload:** `{"request_id": "<uuid>"}`. The handler loads `workspace_id`, the task and the input from the `ai_requests` row. It never trusts a workspace from the payload.
- **Idempotency key:** `ai_requests.id`. The job runs at-least-once and the effect is exactly-once at the request level:
  - A `succeeded` or `failed` request makes the job a no-op.
  - The claim is a single conditional `UPDATE ai_requests SET status='running', lease_owner=:worker, lease_expires_at=:now+180s, attempt_count=attempt_count+1 WHERE id=:id AND (status='queued' OR (status='running' AND lease_expires_at < :now))`. Zero rows means the job returns without effect.
- **Lease:** 180 s. **Heartbeat:** every 60 s, an `UPDATE ... SET heartbeat_at=:now, lease_expires_at=:now+180s WHERE id=:id AND lease_owner=:worker AND status='running'`. All times come from the injected `Clock`.
- **Lost lease:** if the heartbeat updates 0 rows, another worker owns the request. The handler cancels its in-flight provider call, performs no further settlement or state change, and returns.
- **Duplicate delivery:** `JobQueue.run_once` reclaims messages idle for more than 60 s (`xautoclaim min_idle_time=60_000`), shorter than the 180 s lease. A long AI call can therefore be delivered to a second consumer. That consumer fails the claim above, returns normally and is acknowledged. It does not raise, so it does not consume `max_attempts`. If the first worker actually died, the lease expires after at most 180 s and the reaper (8.2) re-enqueues.
- **Retry policy:** two layers.
  - *Provider and schema failures* are handled inside the handler by the Router and the repair policy (sections 10, 11). They end in a terminal `failed` request and the handler returns normally. The queue never retries them, so a provider failure is never paid for twice.
  - *Infrastructure failures* (database or Redis errors, crashes) raise, and `JobQueue` applies its existing policy: `max_attempts=5`, backoff `min(300, 2**attempt)` s, dead letter on `jobs:dead` with `failure_code` the exception class name.
- **Completion:** in one transaction the handler stores `output_payload` (or `error_code`), sets the terminal status and `completed_at`, clears the lease, and publishes `ai.request_completed` or `ai.request_failed`.

### 8.2 `ai_platform.reap_stale_requests` v1

- **Payload:** `{"bucket": "<UTC minute ISO-8601>"}`. **Idempotency key:** the bucket. Re-running a bucket re-evaluates the same predicates and is safe.
- **Effects:**
  - `running` requests whose `lease_expires_at` passed more than 180 s ago:
    - If `attempt_count < 5`, the reaper re-enqueues `execute_request`.
    - Otherwise it marks the request `failed` with `error_code = execution_abandoned` and emits `ai.request_failed`.
  - `queued` requests older than 5 minutes: re-enqueue `execute_request`. This is a backstop for a lost job message.
  - `ai_usage_records` still `reserved` for more than 360 s (2 × lease), whose request is no longer holding a live lease: mark them `abandoned`. The amount reserved is **charged to `spent` as the cost** (never undercount) and the reservation is released (INV-14).
- **Scheduling:** `jobs_workers` has no scheduler today. See OQ-1.

### 8.3 What is not a job here

- The embedding pipeline job is owned by `rag` (§54). It calls `EmbeddingService.embed_texts` from inside its handler.
- Sync `run` calls are not jobs.

## 9. AI tasks used and the task registry

Business modules request only these names. The task registry is an in-code, versioned list. Every entry is validated at startup (`AiTaskNotReady` if its schema is missing at call time).

Classes (initial configuration defaults, tunable in config, pinned by tests):

| Class | Values | Meaning |
| --- | --- | --- |
| Quality | `basic` < `standard` < `high` | The minimum catalog `quality_tier` a model needs. |
| Latency | `interactive`, `standard`, `batch` | Total deadline for the request: 20 s, 60 s, 300 s. They also drive ranking (section 10). |
| Cost | `low`, `medium`, `high` | Ceiling on the estimated worst-case cost of a single provider call: 20,000 / 100,000 / 500,000 micro-USD. |

Capabilities (§45) say what a task needs from a model. `retrieval_grounding` means "the task consumes caller-supplied, source-tagged context blocks". `ai_platform` does not retrieve.

| Task | Capabilities | Output schema (name, v1) | Quality | Latency | Cost | Modalities in → out |
| --- | --- | --- | --- | --- | --- | --- |
| `ANALYZE_MARKET_TRENDS` | text_generation, reasoning, retrieval_grounding, structured_output | `MarketTrendAnalysis` | standard | batch | medium | text → text |
| `GENERATE_CONTENT_BRIEF` | text_generation, reasoning, retrieval_grounding, structured_output | `ContentBriefDraft` | high | standard | high | text → text |
| `GENERATE_CHANNEL_EXECUTION` | text_generation, retrieval_grounding, structured_output | `ChannelExecutionDraft` | standard | standard | medium | text → text |
| `GENERATE_CONTENT_DRAFT` | text_generation, retrieval_grounding, structured_output | `ContentDraftOutput` | high | standard | high | text → text |
| `GENERATE_HOOK_VARIATIONS` | text_generation, structured_output | `HookVariationSet` | standard | interactive | low | text → text |
| `ANALYZE_PERFORMANCE` | text_generation, reasoning, retrieval_grounding, structured_output | `PerformanceAnalysis` | high | batch | medium | text → text |
| `EXTRACT_AUDIENCE_SIGNALS` | text_generation, retrieval_grounding, structured_output | `AudienceSignalExtraction` | standard | batch | low | text → text |
| `SYNTHESIZE_SIGNALS` | text_generation, reasoning, structured_output | `SignalSynthesisResult` | standard | batch | medium | text → text |

The first eight rows are the example tasks listed in §44. The `GENERATE_CONTENT_BRIEF` capability set is the one given as the example in §45 (Text Generation, Retrieval, Reasoning, Structured Output).

Platform task (not in §44; added because §54 requires an embedding path):

| Task | Capabilities | Output | Notes |
| --- | --- | --- | --- |
| `EMBED_TEXT` | embedding | `EmbeddingBatch` (not a Pydantic task schema) | internal, used by `EmbeddingService` only. Pinned to `text-embedding-3-small` at 1024 dimensions. No fallback. Cannot be requested through `AiTaskRequest`. |

Schema ownership:

- The schema **names** and version numbers above are reserved by `ai_platform`.
- The schema **bodies** are owned by the domain module that owns the output (`brief`, `signal_synthesizer`, and so on). Those modules do not exist yet.
- Until a module registers its schema, the task raises `AiTaskNotReady`. It fails closed and never falls back to unvalidated text.
- `ai_platform` ships test-only schemas under the fake provider for its own acceptance tests. They are not exported as product tasks.
- Who owns the prompt templates is OQ-5.

Adding a task is a change to the registry and a spec change. A module cannot register a task at runtime.

## 10. AI Router rules

The Router is a pure, deterministic function of `(task definition, request, catalog, health snapshot, budget snapshot)`. It performs no I/O. The same inputs always give the same ordered candidate list. This keeps routing testable.

### 10.1 Model catalog

- Versioned in-repo data (`catalog_version`, `price_version`).
- Each model has: `provider`, `model`, `enabled`, `capabilities`, `input_modalities`, `output_modalities`, `quality_tier`, `context_window_units`, `max_output_units`, `supports_json_schema`, `latency_p50_ms` (static estimate), and integer prices `input_micro_usd_per_million_units` and `output_micro_usd_per_million_units`.
- The catalog is the only place in the codebase that may contain provider or model names (INV-3). Its initial contents are OQ-3.
- Provider API keys are read from environment variables (LiteLLM's conventional names) as `SecretStr` and are never logged.

### 10.2 Selection, in order

1. **Capability and modality filter.** Keep models that are `enabled` and support every capability the task requires. Every modality present in the request (input) and required by the task (output) must be supported. A rejected model gets reason code `capability` or `modality`.
2. **Context fit.** Estimated input units, using LiteLLM's counter plus a configurable safety margin (default 10 %), plus the call's `max_output_units`, must fit `context_window_units`. Reason code `context`. If every model fails only here, raise `AiInputTooLarge`.
3. **Quality floor.** `quality_tier >= max(task.quality, request.quality_floor)`. A request can only raise the floor. Reason code `quality`.
4. **Cost ceiling.** The estimated worst-case cost of one call (formula in 12.2) must be ≤ the task's cost-class ceiling. Reason code `cost_class`.
5. **Availability.** Drop models whose circuit breaker is open (10.4). Reason code `unavailable`.
6. **Budget.** The estimated cost must fit the remaining workspace budget and the remaining system budget (`limit - spent - reserved`, read as a snapshot). If steps 1–5 left candidates but this step removes all of them, raise `AiBudgetExceeded`. The atomic reservation in 12.3 is still the authority. The snapshot only keeps the Router from proposing hopeless candidates.
7. **Rank.** Sort the remaining candidates lexicographically. The final key is always `model` ascending, so ties are deterministic.
   - `interactive`: (`latency_p50_ms` asc, estimated cost asc, `model` asc)
   - `standard`: (estimated cost asc, `latency_p50_ms` asc, `model` asc)
   - `batch`: (estimated cost asc, `model` asc)
8. If no candidate remains and the cause was not budget or context, raise `AiNoRoute`. For embeddings the candidate list is exactly the pinned model, or `AiNoRoute` if it is unavailable.

Quality is a floor, not an objective. Among eligible models the cheapest (or, for `interactive`, the fastest) wins. This keeps selection simple and predictable (§62).

### 10.3 Fallback and failure behavior

- LiteLLM's own retries are turned off (`num_retries=0`). The Router owns every retry so that every attempt gets a usage record and a budget reservation.
- The orchestrator tries candidates in rank order, up to `max_provider_attempts` distinct models (default 3). Each attempt is a reserve, call and settle cycle (section 12).
- **Triggers a fallback to the next candidate:** timeout, connection error, HTTP 5xx, provider rate limit, provider auth failure (the model is marked unavailable for the process lifetime and logged at error level with its code only), and schema-enforcement failure after repair (section 11).
- **Does not fall back:**
  - `content_refused`: raise `AiContentRefused`.
  - `provider_bad_request`: a programming or configuration error. Fail with `AiProviderUnavailable` and log the code.
  - `budget_exceeded`.
  - `lease_lost`.
- The request's deadline (latency class) is a hard bound across all attempts. When the remaining time is below the next candidate's `latency_p50_ms`, the orchestrator stops and fails with `provider_timeout`.
- **Final failure:** raise `AiProviderUnavailable`, or the specific error above. `ai_requests.status` becomes `failed` with the matching `error_code`. No partial output is stored or returned.

### 10.4 Circuit breaker (availability)

Per `(provider, model)`, in-process (no Redis dependency). After 5 consecutive transient failures within 60 s, the breaker opens for 30 s. It then goes half-open and lets one probe through: success closes it, failure re-opens it. These defaults are configuration. All timing uses `Clock`. State is per worker process and not shared. That is acceptable for the modular-monolith MVP, and it is not a correctness mechanism, because budgets and ledgers are in the database.

### 10.5 How the choice is recorded

Per call attempt, an `ai_usage_records` row stores:

- `provider`, `model`, `catalog_version`, `price_version`, `routing_version`,
- `route_rank` (position in the ordered list),
- `candidate_snapshot` (every considered model with `eligible` and a `reason_code`; ids and codes only).

`ai_requests.routing_version` records the rules version. The final record's id is returned as the opaque `routing_id`. Together these answer "which model served this, why, and what else was considered" without logging content.

## 11. Strict output-schema enforcement

- Every registry task except `EMBED_TEXT` has a registered output schema. A "free text" task does not exist.
- A registered schema must be a Pydantic v2 `BaseModel` with `extra="forbid"`. `OutputSchemaRegistry.register` rejects any other model, and rejects duplicate `(name, version)`.
- **Request side:** the Router prefers models with `supports_json_schema` and the adapter passes the schema as a structured-output request. Models without it are still allowed for tasks that need only `structured_output` via JSON mode, and the response is validated in the same way.
- **Validation:** the raw output is parsed and validated with `model_validate_json(..., strict=True)`. There is no coercion, no extra keys, and no partial acceptance. Validation is the only gate. Provider-side schema support never replaces it.
- **Truncation:** `finish_reason = length` is a failure with code `output_truncated`. It is not repairable. The orchestrator moves on to the next candidate.
- **Repair policy:**
  - On a validation failure, the orchestrator may make up to `max_repair_attempts` (default 1) repair calls to the same model.
  - A repair call carries the original request, the invalid output, and the validation error locations and types.
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
- Catalog prices are the authority, versioned with `price_version`. LiteLLM's cost helper is not used for money (OQ-3).
- **Reservation estimate** for a generation call = `ceil(estimated_input_units × in_price / 1e6) + ceil(max_output_units × out_price / 1e6)`. `max_output_units` is the lower of the request's value, the task default and the model's maximum. Embedding estimate = `ceil(estimated_input_units × in_price / 1e6)`.

### 12.3 Budgets

- **Workspace budget:** default **25 USD** (25,000,000 micro-USD) per workspace per month.
- **System budget:** **100 USD** (100,000,000 micro-USD) across all AI calls (workspace and system scope) in the same month (**provisional — OQ-2**).
- The period is the UTC calendar month of the reservation (**provisional — OQ-2**).
- Every workspace-scoped call counts against both its workspace budget and the system budget. A system-scope call counts against the system budget only.
- There is no per-workspace override in this phase (OQ-8).

**Concurrency-safe enforcement.** Reservation is one short transaction:

1. Ensure both period rows exist (`INSERT ... ON CONFLICT DO NOTHING`).
2. Reserve against the workspace row with a single conditional statement: `UPDATE ai_budget_periods SET reserved_micro_usd = reserved_micro_usd + :est, updated_at = :now WHERE id = :id AND spent_micro_usd + reserved_micro_usd + :est <= limit_micro_usd RETURNING ...`.
3. Do the same on the system row. The lock order is always workspace row, then system row.
4. If either statement returns zero rows, the transaction rolls back (which also undoes the first reservation) and `AiBudgetExceeded` is raised before any provider call.
5. On success, insert the `reserved` usage record in the same transaction.

Because the check and the increment are one atomic statement under the row lock, N concurrent callers can never reserve more than the limit, regardless of process count.

**Settlement** (one transaction): conditionally flip the usage record `reserved → succeeded|failed` (`WHERE status='reserved' RETURNING`, so settlement and release happen at most once). Then `reserved -= est` and `spent += actual_cost` on both rows. Then evaluate the thresholds.

If actual cost exceeds the reserved estimate, which should not happen because the output is capped, the actual cost is still recorded in full and `spent` may exceed `limit`. The next reservation is then refused. Spend is never silently dropped.

**Thresholds** are evaluated inside the settlement and reservation transaction, on `(spent + reserved) / limit`:

| Level | Behavior |
| --- | --- |
| < 80 % | Normal. |
| ≥ 80 % | The first time `(spent + reserved) × 100 >= 80 × limit`, `UPDATE ... SET warning_notified_at = :now WHERE id = :id AND warning_notified_at IS NULL RETURNING`. If a row is returned, publish `ai.budget_threshold_reached` in that transaction, append an `AuditRecord` (`action="ai.budget.threshold_reached"`, system actor) and emit a structured warning log. Calls continue unchanged. |
| ≥ 100 % | A reservation that would take `spent + reserved + est` above the limit is refused with `AiBudgetExceeded` (HTTP 429, code `ai_budget_exceeded`). The first refusal sets `exhausted_notified_at` once, publishes `ai.budget_exhausted` and appends an audit record. Calls already in flight finish and settle. Exemptions are OQ-7. |

- Refusals write no `ai_usage_records` row, because no call was made. They are counted in a structured log event (`ai_budget_refused`) with scope, task and period only.
- The next period starts with new rows and zero counters. There is no carry-over.

**Reconciliation.** For any period row with `reserved_micro_usd = 0`, `spent_micro_usd` equals the sum of `cost_micro_usd` over `ai_usage_records` of that scope, workspace and period (INV-13). The test suite includes this check.

### 12.4 Logging, audit, privacy

- Log events: `ai_call_started`, `ai_call_finished`, `ai_budget_refused`, `ai_budget_threshold`. The only fields are:
  - ids and codes: `request_id`, `workspace_id`, `task`, `provider`, `model`, `route_rank`, `status`, `error_code`,
  - counts: `input_units`, `output_units`, `latency_ms`, `cost_micro_usd`.
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

Minimal and read-only. It is justified because budget enforcement (80 % warning, 100 % refusal) would otherwise be invisible to the people it affects, and because it is the end-to-end check that cost accounting reaches users.

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
- **New permission** `ai:usage_read` (`WorkspacePermission.AI_USAGE_READ`) is added to `app.workspace.access.ROLE_PERMISSIONS`, the single registered extension point. OWNER: yes. ADMIN: yes. MEMBER: no (**provisional — OQ-5**).
- **Failure shapes** follow the workspace convention: non-member 404, member without permission 403.
- **Usage scoping.** Every read is `WHERE workspace_id = ctx.workspace_id`. Single-request reads (`get_status`, `get_output`) also match the request id and return `NotFound` on mismatch.
- **Reads by id are scoped.** A request id from another workspace is indistinguishable from a missing one.
- **Worker integrity.** Jobs carry only `request_id`. Workspace, task and input come from the persisted row. The `ai.request_queued` consumer is idempotent through `handle_once`.
- **System scope.** System-scope rows are not readable through any workspace endpoint. The budget and usage services reject a system context for workspace reads.
- **Provider secrets.** Keys come from environment variables as `SecretStr`. They are never persisted, logged, evented, put in a job payload, or put in an error.
- **Content handling.**
  - Content exists only in `ai_requests.input_payload` / `output_payload` for async requests and `persist_result` calls.
  - Content is never copied to logs, events, audit details, job payloads, usage rows or errors.
  - Retention is OQ-4.

## 16. Invariants

1. **INV-1.** Only code under `app/ai_platform/` imports `litellm` or any provider SDK. An architecture test fails on any other import.
2. **INV-2.** `AiTaskRequest`, `AiTaskResult`, `AiRequestStatus` and the exported exceptions contain no field, attribute or message that names a provider or model, and no per-call model override exists.
3. **INV-3.** No module outside `ai_platform` contains a provider or model identifier from the catalog (architecture test scanning `app/` outside the catalog file). The catalog file is the only place where such names appear.
4. **INV-4.** Every call to a provider goes through `AiOrchestrator` → `AiRouter` → `ProviderClient`. There is no code path from a public interface to a provider that skips the Router.
5. **INV-5.** The Router is deterministic: the same inputs always yield the same ordered candidates and the same `candidate_snapshot`.
6. **INV-6.** No provider call happens inside a database transaction that holds budget row locks.
7. **INV-7.** Every provider call attempt has exactly one `ai_usage_records` row. A row never goes from a terminal status back to `reserved`.
8. **INV-8.** A successful `run` or a `succeeded` async request always returns or stores an instance of the registered output schema that passed `strict=True` validation. Invalid output is never returned or stored.
9. **INV-9.** Total calls per request never exceed `max_provider_attempts × (1 + max_repair_attempts)`.
10. **INV-10.** For any budget row, `spent_micro_usd + reserved_micro_usd` exceeds `limit_micro_usd` only through the settlement of a call whose actual cost exceeded its reservation. A reservation never pushes it over the limit (verified under concurrency).
11. **INV-11.** A workspace-scoped call is reserved against both its workspace row and the system row in one transaction. The two reservations succeed or fail together.
12. **INV-12.** An embedding call uses `text-embedding-3-small` at 1024 dimensions. A result always reports `embedding_version = "v1-d1024"`, 1024-length vectors and the pinned model. There is no fallback model for embeddings.
13. **INV-13.** For any budget row with `reserved_micro_usd = 0`, `spent_micro_usd` equals the sum of `cost_micro_usd` of the matching usage records.
14. **INV-14.** Cost never undercounts. A cost is rounded up, and an abandoned reservation is charged at its estimate.
15. **INV-15.** `ai.budget_threshold_reached` is published at most once per `(scope, workspace_id, period_start)`, and `ai.budget_exhausted` at most once, even under concurrent settlements.
16. **INV-16.** An async request is executed to a terminal state at most once. Duplicate or concurrent job deliveries produce no second provider call and no second settlement.
17. **INV-17.** At most one worker holds a live lease on a request. The lease is 180 s and the heartbeat interval is 60 s. A worker that loses its lease performs no further state change.
18. **INV-18.** No `ai.*` event field name matches `token` (case-insensitive), nor any other pattern rejected by the event envelope. No `ai.*` event, audit detail, log field, job payload or error message contains prompt, completion, user text or output content.
19. **INV-19.** Every read of usage, budget or request data is scoped by the caller's workspace. A cross-workspace request id behaves as not found.
20. **INV-20.** Provider API keys never appear in logs, errors, events, audit details, job payloads or the database.
21. **INV-21.** Every table has `tenant_scope` metadata. All workspace-scoped rows carry `workspace_id`. `workspace_id` is null only when `scope = 'system'`.
22. **INV-22.** All time-dependent behavior (leases, heartbeats, breaker timing, deadlines, budget period) uses the injected `Clock`.
23. **INV-23.** Registry tasks without a registered schema fail closed with `AiTaskNotReady`. There is no unvalidated-text fallback.
24. **INV-24.** The spend of real-provider tests is capped at 20 USD in total (section 17, AC-34).

## 17. Acceptance criteria

Fake-provider tests (AC-1 to AC-33) run on a Postgres test database (marker `db`, with the existing session-scoped migration and rollback fixtures, plus committed-data fixtures for concurrency tests) and need no network and no provider key. The target database is OQ-9. The real-provider smoke test (AC-34 to AC-37) is a separate suite.

### 17.1 Architecture and contract (DB-free)

1. **AC-1.** An architecture test fails if anything outside `app/ai_platform/` imports `litellm` (INV-1).
2. **AC-2.** An architecture test fails if a catalog provider or model identifier appears in `app/` outside the catalog file (INV-3).
3. **AC-3.** Unit test: `AiTaskRequest` rejects unknown fields (including `model` and `provider`). Reflection over `AiTaskRequest`, `AiTaskResult`, `AiRequestStatus` and the exception classes finds no field or message naming a provider or model (INV-2).
4. **AC-4.** The module-boundary test passes with `ai_platform` imported only through `app.ai_platform`, and the package exports every name listed in section 5.
5. **AC-5.** The task registry contains exactly the eight §44 tasks with the capabilities, schema names and classes in section 9, plus the internal `EMBED_TEXT`. A test pins the table. `EMBED_TEXT` cannot be built through `AiTaskRequest`.
6. **AC-6.** Every `ai.*` event model is registered once in `DEFAULT_EVENT_REGISTRY`, forbids extra fields, and no field name matches `token`. `publish` accepts each of them (INV-18).
7. **AC-7.** Settings validation: `Settings(embedding_dim=1024)` is accepted, any other positive `embedding_dim` makes `build_ai_platform` raise `ConfigurationError`, and an unset value is accepted. Provider key values never appear in `repr`, logs or errors.

### 17.2 Router and fallback

8. **AC-8.** With a fake catalog, the Router filters by capability, modality, context fit, quality floor, cost ceiling and availability, with the reason codes in 10.2. A `quality_floor` below the task class has no effect.
9. **AC-9.** Ranking follows 10.2 step 7 for each latency class, with deterministic tie-breaks. The same inputs produce byte-identical `candidate_snapshot` across runs (INV-5).
10. **AC-10.** If the first candidate times out or returns 5xx or rate-limited, the call falls back to the next candidate. The ledger has one `failed` row for the first candidate and a `succeeded` row for the second, with correct `route_rank`.
11. **AC-11.** A `content_refused` outcome is not retried on another model. `AiContentRefused` is raised.
12. **AC-12.** Fallback is bounded at `max_provider_attempts` distinct models. When all fail, `AiProviderUnavailable` is raised and the request is `failed`.
13. **AC-13.** The circuit breaker opens after 5 consecutive failures in 60 s, closes via a half-open probe, and is driven only by `FakeClock`.
14. **AC-14.** A request with an image part for a text-only task raises `AiModalityNotSupported`. With a fake image-capable catalog entry and a fake task that declares image input, the Router selects that model (interface-ready behavior).

### 17.3 Schema enforcement

15. **AC-15.** A valid fake response yields an instance of the registered schema.
16. **AC-16.** An invalid response (missing field, wrong type, extra key, string-for-int) fails `strict` validation. One repair call is made to the same model (`call_kind='repair'`), and it is recorded and budget-reserved.
17. **AC-17.** If the repair is valid the request succeeds. If it is invalid the candidate fails and the Router tries the next. If all candidates fail, `AiOutputInvalid` is raised, no output is stored, `ai_requests.error_code='output_invalid'`, and the ledger has a row for every call, with the money spent kept.
18. **AC-18.** `finish_reason='length'` is recorded as `output_truncated`, is not repaired, and falls back.
19. **AC-19.** A task with an unregistered schema raises `AiTaskNotReady` and makes no provider call (INV-23).
20. **AC-20.** The total number of calls never exceeds 6 with defaults (INV-9). Test with a provider that always returns invalid output.

### 17.4 Cost and budget (local Postgres)

21. **AC-21.** After a successful call, `ai_usage_records` has one row with units, integer micro-USD cost equal to the independently computed `ceil` formula, `price_version`, route fields and `period_start`. `ai_requests` totals equal the sum of its rows.
22. **AC-22.** Concurrency: with a workspace limit that allows exactly K calls and N ≫ K concurrent callers using separate committed sessions, exactly K succeed, N−K raise `AiBudgetExceeded`, and `reserved + spent ≤ limit` at all times (INV-10).
23. **AC-23.** Concurrency on the system budget: workspaces A and B each have room, but the system budget allows K total. Exactly K calls succeed across both workspaces, and a failed system reservation leaves the workspace `reserved` unchanged (INV-11).
24. **AC-24.** Defaults: a new workspace period row has `limit_micro_usd = 25_000_000` and the system row `100_000_000`. A new month starts at zero (using `FakeClock`).
25. **AC-25.** 80 % behavior: crossing 80 % publishes exactly one `ai.budget_threshold_reached` and one audit record, even when several settlements cross concurrently. Calls continue (INV-15).
26. **AC-26.** 100 % behavior: the next reservation is refused with HTTP-mapped `ai_budget_exceeded` (429), no provider call occurs, no usage row is written, and `ai.budget_exhausted` is published once. The in-flight call at the moment of crossing still settles.
27. **AC-27.** Reconciliation: after a mixed workload (successes, failures, repairs, fallbacks), every period row with `reserved = 0` equals the sum of its usage records (INV-13).
28. **AC-28.** A reservation is released or settled at most once, and a double settle attempt is a no-op. A reaped `reserved` record becomes `abandoned`, is charged its estimate and releases the reservation (INV-7, INV-14).

### 17.5 Async, jobs, authorization, privacy

29. **AC-29.** `submit` persists the row and `ai.request_queued` in one transaction. The `handle_once` consumer enqueues exactly one job even if the event is delivered twice. The same idempotency key and fingerprint returns the same request. The same key with a different fingerprint raises `Conflict`.
30. **AC-30.** Job handling: the request ends `succeeded` or `failed`, `ai.request_completed` or `ai.request_failed` is published once, and a re-delivered job is a no-op with no second provider call (INV-16). A job racing a live lease returns without effect.
31. **AC-31.** Lease and heartbeat with `FakeClock`: the claim sets a 180 s lease. A 60 s heartbeat extends it. After 180 s without a heartbeat another worker can claim, and the old worker's later heartbeat updates 0 rows and aborts without settling (INV-17). The reaper re-enqueues or fails per section 8.2.
32. **AC-32.** Authorization and privacy:
    - A tenant-isolation test registers both endpoints and a non-member gets 404 (`WORKSPACE_SCOPED_ROUTES`).
    - OWNER and ADMIN get 200 and MEMBER gets 403 (provisional — OQ-5).
    - `get_status` and `get_output` with another workspace's request id raise `NotFound`.
    - System-scope rows are absent from workspace reports.
    - Captured logs, events, audit rows, job payloads and error responses of a full run (success, schema failure, budget refusal) contain none of the test prompt, completion or output strings and no `token`-named key (INV-18, INV-19, INV-20).
33. **AC-33.** `embed_texts` with the fake provider returns vectors of length 1024, `embedding_model="text-embedding-3-small"`, `embedding_version="v1-d1024"`, and records usage. Empty batches, oversize batches and oversize texts are rejected, and there is no fallback model (INV-12).

### 17.6 Real-provider smoke test (separate, small)

Marker `ai_live`. It is excluded from `scripts/check.py` and from `just test-db`, and it only runs when `AI_LIVE_TESTS=1` and a provider key is present in the ignored `.env.test.local`. It runs against the test database. Keys never appear in output.

34. **AC-34.** *Spend cap (INV-24).* The suite is designed to cost far below 1 USD in total:
    - at most 3 provider calls,
    - `max_output_units ≤ 300`,
    - texts of at most a few sentences.

    A session fixture sums `ai_usage_records.cost_micro_usd` for the session and aborts the remaining tests if it passes 2 USD. The 20 USD total across all test runs is enforced by the provider-side spend limit on the dedicated test key (OQ-10). The suite documents the key it expects and never uses a production key.
35. **AC-35.** One real `embed_texts` call over 3 short strings returns 3 vectors of length 1024, `embedding_version="v1-d1024"`, usage > 0 and cost > 0 in the ledger.
36. **AC-36.** One real task call through the Router (a cheap `interactive` task using a test-only schema) returns a strictly valid output, writes a ledger row whose recorded cost matches the catalog formula within the provider-reported units, and increments the workspace budget.
37. **AC-37.** The same run's captured logs contain no prompt or completion text and no key (INV-18, INV-20). The test fails if the output contains the sentinel strings used in the prompt.

## 18. Non-goals

- Billing, plans, invoices, quotas by plan, payment, or charging users. (`billing_usage` is a later, conditional phase.) Cost metering and budget enforcement are the only monetary scope here.
- Per-workspace budget overrides, a budget admin UI, or a system-level usage endpoint (OQ-8; `admin_ops` is Phase 9).
- Context assembly, retrieval, ranking, and token budgeting of context (`context_engine`, `rag`).
- Storing embeddings or chunks, and the embedding job itself (`rag`).
- Domain output schema bodies and domain prompt content (the owning modules; OQ-5).
- Real image, video or audio adapters, models or tasks. Media storage (`content_asset`).
- Streaming partial output to clients (OQ-11).
- Fine-tuning, model evaluation harnesses and AI output evals (`delivery`, Phase 9).
- Human-in-the-loop review of outputs (`human_feedback`, `brief`, and so on).
- A distributed circuit breaker, a multi-region router, or Kafka.
- A generic public "run AI task" HTTP endpoint.
- Purging stored content (OQ-4), and data export or deletion workflows (`security_compliance`).
- Content in languages other than English. Content is always English.

## 19. Open Questions

None of these is decided. Each lists options and a recommendation. Where the body of the spec needs a value to stay testable, it carries a **provisional** marker pointing here.

**OQ-1. How is the reaper job scheduled?**
`jobs_workers` has no scheduler. The workspace invitation-expiry job is the same case, and its spec says "no scheduler infrastructure is added here". The reaper (8.2) is what makes lost job messages and dead workers recoverable.
- (a) An external cron or platform scheduler enqueues the job each minute.
- (b) A ticker loop inside the AI worker process enqueues it.
- (c) Add a small generic scheduler to `jobs_workers` (separate task).
- *Recommendation:* (c) as a separate small task, used by both reaper and invitation expiry. Until then use (a). This does not change this spec's interfaces.

**OQ-2. What exactly is the budget period, and is the system budget monthly?**
The fixed decisions give 25 USD per workspace per month and a 100 USD system budget, without stating the system period or the month boundary.
- (a) Both use the UTC calendar month.
- (b) Rolling 30 days.
- (c) System budget is a lifetime or all-time cap.
- *Recommendation:* (a). It is simple, deterministic with `Clock`, and matches the monthly workspace wording. Section 4, 12 and AC-24 use it provisionally.

**OQ-3. What is the initial model catalog, and where do prices come from?**
Sources fix only the embedding model. They name no chat providers or models, and no prices.
- Catalog contents: (a) one chat provider and a small/large pair; (b) two providers to make fallback real from day one.
- Price authority: (a) in-repo catalog prices with `price_version` (deterministic, testable); (b) LiteLLM's cost helper (less maintenance, less deterministic).
- *Recommendation:* two providers, with at least two quality tiers, so the fallback path is exercised. Use in-repo catalog prices, verified against each provider's published pricing at implementation time. The owner chooses providers, models and the smoke-test model.

**OQ-4. How long is stored input/output content retained?**
Async requests store `input_payload` and `output_payload`. The sources set a "no content in logs, events, errors" rule and say nothing about database retention.
- (a) Keep until a Phase 9 purge job exists.
- (b) Purge content after N days (N = 7, 30 or 90) with a job, keeping metadata.
- (c) Never keep input after the call (the worker would need a different handoff).
- *Recommendation:* (b) with a short window (the owner picks N), implemented in this phase or soon after. `content_purged_at` is already in the schema, so adding it later needs no migration.

**OQ-5. Who owns prompt templates, and may MEMBER read AI usage?**
(5a) *Prompt ownership.* The task registry here owns task names and schema names, and the calling domain modules build `instructions`.
- Options: (a) domain modules own and version their prompt text; (b) `ai_platform` owns a versioned template per task, and domain modules pass variables.
- *Recommendation:* (a). Prompts encode domain knowledge, and (b) would pull domain logic into the platform. `ai_platform` stays prompt-agnostic.

(5b) *Usage visibility.* The spec uses `ai:usage_read` for OWNER and ADMIN (provisional).
- Options: (a) OWNER+ADMIN; (b) all members; (c) OWNER only.
- *Recommendation:* (a). Cost visibility is a management concern, and members are not told others' usage.

**OQ-6. May `run` be called from an API request path?**
`run` is synchronous. §53 says long or non-critical AI work should not block API requests.
- (a) Allowed only for `interactive` latency-class tasks (20 s deadline); everything else must use `submit`.
- (b) Allowed for any task.
- (c) Never from request paths; always `submit`.
- *Recommendation:* (a), enforced by the orchestrator (`run` on a non-interactive task from an `actor_type="user"` context raises a programming-error `ValidationFailed`).

**OQ-7. Are there exemptions at 100 % budget?**
The spec refuses all new calls at 100 % and lets in-flight calls finish.
- (a) No exemptions.
- (b) System-scope calls (such as embedding GLOBAL knowledge) are exempt from the workspace budget but not from the system budget (they already only use the system budget).
- (c) Allow a small overage grace.
- *Recommendation:* (a) for workspace budgets. Spend is never exempt from the system budget. Revisit when `admin_ops` exists.

**OQ-8. How do budget limits change per workspace?**
No override mechanism exists. Limits are copied from config when a period row is created.
- (a) Config only. Changing a limit for a workspace needs a config change plus a manual row update.
- (b) A `workspace_ai_budget_overrides` table written by `admin_ops` in Phase 9.
- (c) A workspace-OWNER-editable limit.
- *Recommendation:* (a) now and (b) in Phase 9. (c) edges toward plans and billing.

**OQ-9. What database do the fake-provider tests run on?**
The request says "local Postgres". The existing `db`-marked tests and `scripts/test_db.py` require `APP_ENV=test` and `NEON_BRANCH_NAME=test` and are described as running against the Neon test branch. The guard compares labels, not hosts. The `vector` extension is installed by migration `0001`.
- (a) A local Postgres 16+ with pgvector, using `.env.test.local` with the `test` selectors as labels. This passes the guard, but the label is then not evidence of a Neon branch.
- (b) Add an explicit local-database mode to the guard (a separate change in `db_migrations`).
- (c) Keep using the Neon test branch.
- *Recommendation:* (b) as a small separate task, with (a) as the interim route. Do not weaken the existing guard.

**OQ-10. How is the 20 USD total real-provider cap enforced across test runs?**
Code can bound one session but cannot see earlier sessions.
- (a) A provider-side hard spend limit on a dedicated test key, plus the in-test fixture limit (2 USD per session).
- (b) A persisted counter file or table of cumulative test spend.
- (c) Manual discipline.
- *Recommendation:* (a). It is the only control the code cannot bypass. (b) can sit on top.

**OQ-11. Is streaming of partial output in scope for this phase?**
`web_foundation` lists streaming and job-status utilities, which suggests a future need.
- (a) Not now. Async results arrive through job status and events.
- (b) Add a streaming `run_stream` interface now (interactive tasks only).
- *Recommendation:* (a). Strict schema validation needs the full output, and structured-output tasks are not naturally streamable.

**OQ-12. Should `ai_platform` become a hard dependency of `rag` startup?**
`rag` needs `EmbeddingService`. With `REDIS_URL` and provider keys optional, workers can start without them.
- (a) Missing provider key raises `ConfigurationError` only when a call is made (consistent with core's "fail at point of use").
- (b) Fail at worker startup if the `rag` embedding job is registered and no embedding key is set.
- *Recommendation:* (a), with a readiness-style check helper that `rag` may call at startup. This matches the existing core configuration philosophy.

## Frontend

To be added by the FE task. The UI slice in section 14 defines its minimum scope.

## Public interfaces and events later features must use

- Import everything from `app.ai_platform`: the types in 5.1–5.5, `AiCallContext`, `AiTaskRequest`, `AiOrchestrator`, `EmbeddingService`, `AiBudgetService`, `AiUsageService`, `AiTaskRegistry`, `OutputSchemaRegistry`, the `Ai*` errors, `FakeAiProvider`, `EMBEDDING_MODEL`, `EMBEDDING_DIMENSIONS`, `EMBEDDING_VERSION`, `build_ai_platform`, `register_jobs`, `register_event_handlers` and `register_routes`.
- Request AI work by task name only. Never pass or reference a provider or model. Register the output schema you own with `OutputSchemaRegistry.register` at startup.
- Build `AiCallContext` from a verified `WorkspaceContext` (`from_workspace`) or from persisted data in workers (`for_worker`). Never from client input.
- Events (all v1): `ai.request_queued`, `ai.request_completed`, `ai.request_failed`, `ai.budget_threshold_reached`, `ai.budget_exhausted`. IDs, counts, codes and micro-USD amounts only. No content, no `token`-named keys.
- Jobs: `ai_platform.execute_request` v1 and `ai_platform.reap_stale_requests` v1, with lease 180 s and heartbeat 60 s. `rag` owns its embedding job and calls `EmbeddingService.embed_texts`.
- Endpoints: `GET /api/v1/workspaces/{workspace_id}/ai/budget` and `GET /api/v1/workspaces/{workspace_id}/ai/usage`, permission `ai:usage_read`.
- AI tasks: the eight §44 tasks in section 9, plus the internal `EMBED_TEXT`.
