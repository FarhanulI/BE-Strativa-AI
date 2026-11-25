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
| [T-006](T-006-ai-platform-approval-clarification.md) | AI Platform revision 5 to 7 approval clarification | ai_platform / 2 | Accepted | Owner decision recorded 2026-11-19; accepted by the owner 2026-11-25. The `decisions.md` section 6 row on revisions 5 to 7 is still stale and needs an owner-approved docs update |
| [T-007](T-007-web-foundation-spec-dependency.md) | web_foundation specification dependency | web_foundation / 0 | Blocked | Frontend task must provide the spec |
| [T-008](T-008-ai-platform-remaining-verification.md) | Remaining AI Platform implementation and verification gaps | ai_platform / 2 | Proposed | T-004 and T-006 for governance; feature work waits for owner approval to resume (SDD-D-3) |
| [T-009](T-009-nine-spec-approval-metadata.md) | Approval metadata for the nine non-AI-Platform specs | Phase 0 and 1 modules | Blocked | Owner confirmation |
| [T-010](T-010-frontend-scope-questions.md) | Frontend normative scope and spec cleanup questions | auth, profile / 1 | Blocked | Owner decision; frontend scope |
| [T-011](T-011-ai-platform-sync-run-path.md) | AI Platform synchronous `run` path (fake provider) | ai_platform / 2 | Accepted | Accepted by the owner 2026-11-25. Steps 1 to 10 done and committed 2026-11-24; DB suite 276 passed (local); `spec-auditor` run, no blockers; 10 criteria Verified (AC-15, AC-17 to AC-19, AC-22 to AC-27). Open items moved to T-023 (Accepted) |
| [T-012](T-012-sdd-process-amendment.md) | SDD process amendment: risk-tiered gates, evidence reporting, independent audit, safety tiers, eval gate (SDD-D-8) | SDD process | Accepted | Accepted 2026-11-20. SDD-D-8 supersedes SDD-D-4 in part |
| [T-013](T-013-ci-with-database-tests.md) | CI with database tests (verification infrastructure for T-002 and T-003; adds no product behavior) | none (serves Phases 0 and 1) | Blocked | Owner deferred 2026-11-20. Workflow committed; CI runs unverified; owner runs the DB suite manually meanwhile |
| [T-014](T-014-traceability-evidence-format.md) | Traceability evidence format (report template, linked Evidence cell, `NOT RUN`) | SDD process support | Accepted | Template created 2026-11-20; DB suite not applicable, docs only. Accepted by the owner 2026-11-25 |
| [T-015](T-015-real-redis-queue-outbox-tests.md) | Real-Redis queue, outbox relay, lease and correlation tests | jobs_workers, events_outbox, observability_audit / 0 | Accepted | Runs recorded 2026-11-20: JOB-AC-2, OUT-AC-3, OUT-AC-2 Verified; OBS-AC-3 stays Gap (API events carry no request ID; owner decision). Accepted by the owner 2026-11-25 |
| [T-016](T-016-auth-workspace-cycle.md) | auth and workspace cycle: cycle check (incl. function-level imports), then fix by composition-root inversion | auth, workspace, api_contract / 1 | Accepted | Steps 0 to 2 done 2026-11-20 (commit 7426ceb); DB suite 200 passed before and after. ADR-0003 updated. Accepted by the owner 2026-11-25 |
| [T-017](T-017-litellm-dependency.md) | Add and pin the LiteLLM dependency (always-stop) | ai_platform / 2 | Accepted | Stops 1 to 3 done 2026-11-20 (`litellm==1.109.1`); clean-install, DB-free and DB suites green (200 passed); accepted by the owner 2026-11-20 |
| [T-018](T-018-model-catalog-verification.md) | Model catalog verification from official documentation; catalog file and loader refusal of unverified entries | ai_platform / 2 | Accepted | T-017; possible spec change proposal for the `verified` fields |
| [T-019](T-019-instructions-version.md) | `instructions_version` on AI requests: proposal, then nullable migration | ai_platform / 2 | Accepted | Owner approval; must be settled before T-011 starts |
| [T-020](T-020-ai-metric-views.md) | DB-derived AI metric views (p50/p95 latency, cost, error rate by provider, model, `instructions_version`) | ai_platform / 2 | Proposed | T-019 |
| [T-021](T-021-generated-data-model.md) | Generated `data-model.md` and drift gate | db_migrations / 0 | Proposed | T-013 |
| [T-022](T-022-circuit-breaker-probe-ownership.md) | Circuit breaker probe ownership and lease (D-37; AC-64, AC-65) | ai_platform / 2 | Accepted | CP-4 applied as spec revision 11; made Ready by the owner 2026-11-24; checkpoints 2 (failing H1 tests, approved) and 3 (registry ownership and lease, DB-free gate green) done; checkpoint 3 approved 2026-11-25; checkpoint 4 approved 2026-11-25 (DB suite 305 passed, local); checkpoint 5 done: `spec-auditor` run, no blockers, should-fix items applied; AC-64 and AC-65 Implemented, not Verified; accepted by the owner 2026-11-25. Independent of T-011, whose scope and record are unchanged |
| [T-023](T-023-ai-platform-run-followups.md) | AI Platform `run` follow-ups from the T-011 audit (unexpected-exception ending, unasserted clauses, deadline edge, stale notes) | ai_platform / 2 | Accepted | Accepted by the owner 2026-11-25. Steps 1 to 6 done (steps 5 and 6 merged). DB suite 288 passed (local, 2026-11-24); `spec-auditor` run 2026-11-25, no blockers; AC-29 and AC-59 Verified on `run`. Open test gaps listed in the task Evidence |
| [T-024](T-024-ai-platform-run-cleanup-tests.md) | AI Platform `run` cleanup test gaps and edge decisions (failing cleanup, fault after settled attempts, wider content check, cancellation during cleanup, cleanup timeout, `routing_version` before routing) | ai_platform / 2 | Accepted | Accepted by the owner 2026-11-25. Made Ready by the owner 2026-11-25; decisions D-A to D-D settled to the defaults (D-A keep, D-B no bound, D-C pass `None` before routing, D-D keep silent). Follow-up to T-023 (Accepted); step 2 done and approved (DB-free 1798 passed; DB suite 296 passed, local, 2026-11-25); steps 1 to 4 done (D-C (b) change plus 12 tests; DB suite 300 passed, local, 2026-11-25); `spec-auditor` run, no blockers, should-fix items applied |

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
