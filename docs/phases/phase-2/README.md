# Phase 2: AI and Knowledge Platform

Authoritative sources: [modules.md](../../modules.md) (Phase 2), the [AI Platform spec](../../specs/ai-platform/spec.md), [traceability.md](../../traceability.md), [decisions.md](../../decisions.md), the [conformance report](../../architecture/conformance-report.md). This page is a status and planning summary and creates no requirement.

## Definition of done (owner decision, 2026-11-20)

Phase 2 is done when both hold:
1. `ai_platform` is **verified**, not just implemented: its requirements carry dated execution evidence in traceability, with Neon-named criteria excepted only where the spec names none.
2. Approved specifications exist for `rag` and `context_engine`. Implementing them is not part of this definition.

## Modules

| Module | Spec | State |
| --- | --- | --- |
| ai_platform | [spec](../../specs/ai-platform/spec.md) (rev 7; rev 4 approved, rev 5 to 7 approved 2026-11-19, T-006) | 93 rows: 66 Implemented, 26 Specified, 1 Gap. Nothing `Verified`. |
| rag | none | Needs a spec. Must reuse D-23 and D-29. |
| context_engine | none | Needs a spec. |

Implemented so far (from the commit history and code, steps 3a to 5b-1): catalog loader, pricing, task registry, Router selection, failure policy, circuit breaker, budget repository and coordinator, usage service, request repository, provider boundary types, `FakeAiProvider`, output validator, message builder.
Not in the code yet: the orchestrator, embedding service, the LiteLLM adapter and dependency, HTTP routes, jobs and the cron CLI, and a committed catalog file.

## Hardening milestone

Goal: make the existing code verifiable and safe to build on, before the orchestrator and adapter work continues. All tasks are `Proposed`. Plan approval is always required; result review is per the gate column.

| Order | Task | Finding | Gate |
| --- | --- | --- | --- |
| 0 | [T-012](../../tasks/T-012-sdd-process-amendment.md) process amendment (review only) | | always |
| 1 | [T-002](../../tasks/T-002-phase0-reverification.md) Phase 0 re-verification | A-3 | per T-002 |
| 2 | [T-013](../../tasks/T-013-ci-with-database-tests.md) CI with database tests | E-1 | always (CI actions) |
| 3 | [T-014](../../tasks/T-014-traceability-evidence-format.md) evidence format | A-2 | milestone end |
| 4 | [T-015](../../tasks/T-015-real-redis-queue-outbox-tests.md) real-Redis tests | E-2, E-4 | milestone end |
| 5 | [T-016](../../tasks/T-016-auth-workspace-cycle.md) cycle check, then fix | B-1 | always |
| 6 | [T-017](../../tasks/T-017-litellm-dependency.md) LiteLLM dependency (always-stop) | F-4 | always |
| 7 | [T-018](../../tasks/T-018-model-catalog-verification.md) catalog verification | F-1 | always |
| 8 | [T-001](../../tasks/T-001-workspace-neon-concurrency.md) Neon concurrency, first nightly CI run | A-2 | separate authorization |
| 9 | [T-019](../../tasks/T-019-instructions-version.md) `instructions_version`, settled before T-011 | F-2 | always |
| 10 | [T-011](../../tasks/T-011-ai-platform-sync-run-path.md) and [T-008](../../tasks/T-008-ai-platform-remaining-verification.md) AI Platform remaining work | | per task |
| 11 | [T-020](../../tasks/T-020-ai-metric-views.md) metric views; [T-021](../../tasks/T-021-generated-data-model.md) generated data model | F-5, C-1 | always; milestone end |

Notes:
- T-002's JOB rows stay `Gap` until T-015 provides real Redis.
- T-004 (D-32) and T-005 (D-20) remain owner-blocked and do not block T-011.
- Spec authoring for `rag` and `context_engine` has no task yet; it needs `sdd-prepare-task` and an owner decision on timing (SDD-Q-8).
- Neon runs only under the separate authorization in T-001, as a CI secret job, never through MCP.
