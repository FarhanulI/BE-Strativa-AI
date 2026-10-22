## MODULE MAP (modular monolith: Next.js + FastAPI + Neon PostgreSQL + pgvector/tsvector + Redis)

Rules:
- Each module owns its entities, tables, services, API routes, events, jobs, and tests.
- Modules communicate only through public service interfaces or domain events (transactional outbox). Never import another module's internals or query its tables.
- Every module spec must cite the architecture sections it implements and include: purpose, owned entities, DB schema and indexes, public interface, OpenAPI endpoints, events in/out, jobs, AI tasks used, UI slice, authorization rules, invariants, acceptance criteria, non-goals.
- Specs are per feature at `docs/specs/<feature>/spec.md` (Backend, Frontend, Public interfaces). Phases define build order only.

### Phase 0 — Foundation
- core: shared kernel (base entities, IDs, errors, config, clock, pagination, module-boundary rules); [spec](specs/core/spec.md)
- events_outbox: domain events, transactional outbox, event contracts (Kafka-replaceable); [spec](specs/events-outbox/spec.md)
- jobs_workers: Redis queue, background workers, retries, dead-letter handling, idempotency; [spec](specs/jobs-workers/spec.md)
- observability_audit: structured logs, tracing, metrics, audit trail, AI token/cost tracking; [spec](specs/observability-audit/spec.md)
- db_migrations: Neon conventions, SQLAlchemy 2 async, Alembic, pgvector setup, indexing standards; [spec](specs/db-migrations/spec.md)
- api_contract: OpenAPI as the contract, generated TypeScript client; [spec](specs/api-contract/spec.md)
- web_foundation: Next.js app shell, workspace switcher, design system, API client wrapper, streaming/job-status utilities
	- Its spec is `docs/specs/web-foundation/spec.md` and will be added by the FE task.

### Phase 1 — Core & Tenancy
- auth: registration, login, tokens, sessions; [spec](specs/auth-onboarding/spec.md)
- workspace: workspaces, memberships (OWNER/ADMIN/MEMBER), invitations, workspace-centric RBAC on every request; [spec](specs/workspace/spec.md)
- profile: ContentProfile (all profile types), ProfileIdentity, optional BusinessContext, maturity stage; [spec](specs/profile/spec.md)

### Phase 2 — AI & Knowledge Platform
- ai_platform: AI Orchestrator, AI Router, provider abstraction (LiteLLM), task vs capability registry, strict output-schema enforcement, token cost accounting, multimodal-ready interfaces
- rag: KnowledgeChunk (GLOBAL/WORKSPACE/PROFILE scope), async embedding pipeline, hybrid retrieval (pgvector + tsvector + SQL + temporal), ranking, lineage
- context_engine: task-specific context requirements, token budgeting, freshness, source priority, global vs tenant scope

### Phase 3 — Content Intelligence Domains
- brand_intelligence: positioning, identity, voice, tone, pillars, constraints, brand-fit evaluation
- audience_intelligence: personas, pain points, questions, objections, engagement patterns, raw audience events
- market_intelligence: trends, topic movements, competitor and platform observations, raw market events (never auto-generates content)
- performance_intelligence: explains why content worked or failed, dual-pass retrieval (SQL -> semantic -> context assembly), emits learning signals

### Phase 4 — Signals
- signal: StrategicSignal model, signal types (Market, Audience, Performance, HumanFeedback), TTL/expiration, evidence metadata
- signal_synthesizer: deduplication, clustering, thresholding, confidence calculation, configurable thresholds per intelligence type
- human_feedback: edit capture, HumanFeedbackSignal, user choices (re-align / keep custom edit / regenerate / cancel)

### Phase 5 — Strategy
- opportunity: Opportunity Engine, relevance scoring, profile/goal fit, exploration vs exploitation decision
- experiment: ContentExperiment, ExperimentVariant, configurable maturity-based exploration policy, outcome evaluation
- brief: platform-agnostic ContentBrief, human review/edit, strategy contract

### Phase 6 — Execution
- channel_execution: ChannelExecutionSpec, per-platform constraints, Brief -> many specs fan-out
- content_creation: copywriter, hook, caption, script generators, visual direction, ContentDraft
- content_asset: asset generation and assembly (image, video, audio), media storage (S3/R2)
- content_lifecycle: state machine, version history, upstream invalidation cascade/matrix, content lineage

### Phase 7 — Publish & Measure
- integrations: social platform OAuth, token storage and refresh, account linking
- publishing: scheduling, platform publishing adapters, publish status
- performance_ingestion: platform adapters, webhook buffering, polling windows (T+1h/24h/7d/30d), rate limits, retries, immutable metric snapshots
- analytics: read models and dashboards over snapshots, growth velocity, deltas

### Phase 8 — Learning
- learning: combines performance, human preference (kept separate), audience, market, and experiment results into Profile Intelligence that feeds the next opportunity

### Phase 9 — Production Hardening
- security_compliance: tenant-isolation tests, secrets management, PII handling, data export/deletion, rate limiting
- notifications: review requests, stale-content alerts, ingestion failures
- admin_ops: global knowledge management, threshold/policy configuration, feature flags
- billing_usage: plans, quotas, AI cost metering (only if commercial launch requires it)
- delivery: CI/CD, environments, load tests, AI output evals