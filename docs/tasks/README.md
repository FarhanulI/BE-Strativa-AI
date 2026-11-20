# Tasks

A task is a bounded, owner-approved unit of work. The process, lifecycle and rules are in [../sdd.md](../sdd.md). Task IDs (`T-nnn`) are separate from requirement IDs. A task cites requirement IDs; it never replaces them.

## Index

| Task | Title | Module / phase | State | Blocker or dependency |
| --- | --- | --- | --- | --- |
| [T-001](T-001-workspace-neon-concurrency.md) | Workspace Neon TEST-branch concurrency verification | workspace / 1 | Blocked | Separate explicit owner authorization to run on Neon (SDD-D-2) |
| [T-002](T-002-phase0-reverification.md) | Phase 0 re-verification | Phase 0 modules / 0 | Accepted | Accepted 2026-11-20; 8 of 56 rows Verified. Real Redis rows wait for T-015; Neon only under separate authorization |
| [T-003](T-003-phase1-retrospective-verification.md) | Phase 1 retrospective verification gaps | auth, workspace, profile / 1 | Proposed | T-001 for WS-AC-3; owner approval |
| [T-004](T-004-d32-owner-resolution.md) | D-32 owner resolution | ai_platform / 2 | Blocked | Owner decision |
| [T-005](T-005-d20-revision-metadata.md) | D-20 revision metadata investigation | ai_platform / 2 | Blocked | New evidence (history) not available |
| [T-006](T-006-ai-platform-approval-clarification.md) | AI Platform revision 5 to 7 approval clarification | ai_platform / 2 | Implemented | Owner decision recorded 2026-11-19; awaiting acceptance |
| [T-007](T-007-web-foundation-spec-dependency.md) | web_foundation specification dependency | web_foundation / 0 | Blocked | Frontend task must provide the spec |
| [T-008](T-008-ai-platform-remaining-verification.md) | Remaining AI Platform implementation and verification gaps | ai_platform / 2 | Proposed | T-004 and T-006 for governance; feature work waits for owner approval to resume (SDD-D-3) |
| [T-009](T-009-nine-spec-approval-metadata.md) | Approval metadata for the nine non-AI-Platform specs | Phase 0 and 1 modules | Blocked | Owner confirmation |
| [T-010](T-010-frontend-scope-questions.md) | Frontend normative scope and spec cleanup questions | auth, profile / 1 | Blocked | Owner decision; frontend scope |
| [T-011](T-011-ai-platform-sync-run-path.md) | AI Platform synchronous `run` path (fake provider) | ai_platform / 2 | Proposed | Owner approval; SDD-D-7 accepted; rev 5-7 approved (T-006, 2026-11-19) |
| [T-012](T-012-sdd-process-amendment.md) | SDD process amendment: risk-tiered gates, evidence reporting, independent audit, safety tiers, eval gate (SDD-D-8) | SDD process | Accepted | Accepted 2026-11-20. SDD-D-8 supersedes SDD-D-4 in part |
| [T-013](T-013-ci-with-database-tests.md) | CI with database tests (verification infrastructure for T-002 and T-003; adds no product behavior) | none (serves Phases 0 and 1) | In Progress | T-002 accepted, T-012 accepted. First CI run pending |
| [T-014](T-014-traceability-evidence-format.md) | Traceability evidence format (report template, linked Evidence cell, `NOT RUN`) | SDD process support | Proposed | T-012 approved |
| [T-015](T-015-real-redis-queue-outbox-tests.md) | Real-Redis queue, outbox relay, lease and correlation tests | jobs_workers, events_outbox, observability_audit / 0 | Proposed | Real Redis; T-013 for CI. T-002 JOB rows wait for it |
| [T-016](T-016-auth-workspace-cycle.md) | auth and workspace cycle: cycle check (incl. function-level imports), then fix by composition-root inversion | auth, workspace, api_contract / 1 | Proposed | Baseline run first; owner review between steps 1 and 2 |
| [T-017](T-017-litellm-dependency.md) | Add and pin the LiteLLM dependency (always-stop) | ai_platform / 2 | Proposed | T-013; owner approval at each of three stops |
| [T-018](T-018-model-catalog-verification.md) | Model catalog verification from official documentation; catalog file and loader refusal of unverified entries | ai_platform / 2 | Proposed | T-017; possible spec change proposal for the `verified` fields |
| [T-019](T-019-instructions-version.md) | `instructions_version` on AI requests: proposal, then nullable migration | ai_platform / 2 | Proposed | Owner approval; must be settled before T-011 starts |
| [T-020](T-020-ai-metric-views.md) | DB-derived AI metric views (p50/p95 latency, cost, error rate by provider, model, `instructions_version`) | ai_platform / 2 | Proposed | T-019 |
| [T-021](T-021-generated-data-model.md) | Generated `data-model.md` and drift gate | db_migrations / 0 | Proposed | T-013 |

No task exists for a module that has no specification. Exception recorded for T-013: it is verification infrastructure for T-002 and T-003 and does not implement the `delivery` module.

**Hardening milestone order (Phase 2, owner-confirmed 2026-11-20):** T-012 (review only), T-002, T-013, T-014, T-015, T-016, T-017, T-018, T-001 (Neon, separately authorized; first run is the nightly CI job), T-019 (settled before T-011), T-011 and T-008, then T-020 and T-021. See [phase-2](../phases/phase-2/README.md).

## Template

Copy this for a new task. Every field is required; write `None` or `Not applicable` explicitly rather than leaving a field out.

```markdown
# T-nnn: Title

- **Module and phase:**
- **State:** Proposed | Ready | In Progress | Implemented | Verified | Accepted | Blocked
- **Requirement IDs:** (valid IDs from the spec, or "None: dependency on ...")
- **Specification references:**
- **Dependencies:**

## Objective
## Scope
## Non-goals
## Implementation expectations
## Required tests
## Verification requirements
## Acceptance criteria
## Evidence
(Dated execution records only. "None recorded" until work is executed.)
## Review and approval
(Owner approval state and date. "Not requested" until review.)
```
