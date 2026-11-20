# T-020: DB-derived AI metric views

- **Module and phase:** ai_platform, Phase 2
- **State:** Proposed
- **Requirement IDs:** None for the proposal (spec change proposal, [sdd.md](../sdd.md) section 7). New requirement IDs are proposed if approved.
- **Specification references:** [AI Platform spec](../specs/ai-platform/spec.md) 4.2 (`ai_usage_records`: `latency_ms`, units, `cost_micro_usd`, `status`, `error_code`, `provider`, `model`), 5.5 (usage and budget services), 15 (`ai:usage_read`, OWNER and ADMIN only, D-6); [conformance report](../architecture/conformance-report.md) F-5
- **Dependencies:** T-019 settled (the `instructions_version` dimension). T-011 is not required, but the views are only meaningful once real calls write usage rows.

## Objective
Define read-only views over the AI ledger that give p50 and p95 latency, cost, and error rate by provider, model and `instructions_version`, so that observed latency can be compared with the catalog's static `latency_p50_ms`.

## Scope
- **Part A, proposal.** Views and their columns: time bucket (default: day, UTC), task, provider, model, `instructions_version` (null shown as null), calls, error rate (failed over total calls, by `error_code` too), p50 and p95 `latency_ms` (`percentile_cont`), input units, output units, `cost_micro_usd`, validation failure rate. Workspace-scoped variant (filtered by `workspace_id`) and system-wide variant.
- **Ownership:** the views belong to `ai_platform` and read only `ai_*` tables. `observability_audit` must not read them directly (module boundary); a cross-module consumer uses a public `ai_platform` service method.
- **Access:** through a public service method guarded by `ai:usage_read` for workspace scope. The system-wide variant is system scope only and is not exposed over HTTP in this task.
- **Part B, implementation (after approval).** Migration `0010` creating plain (non-materialized) views, the service method, and tests. Default: plain views, no refresh job (SDD-Q-5).

## Non-goals
OpenTelemetry or Prometheus (deferred to Phase 9). Dashboards or HTTP endpoints. Alerts. Changing the catalog's `latency_p50_ms` logic or Router ranking. Metrics for non-AI modules.

## Implementation expectations
Views expose no prompt, completion or user content; they aggregate only numeric and enum columns plus the opaque label. The tenant-scope metadata rule (DBM-AC-3 classifies tables) is not changed; whether views need classification is raised in Part A.

## Required tests
Aggregation correctness on synthetic ledger rows (known percentiles and rates), null `instructions_version` handling, workspace isolation (another workspace's rows never appear), permission check on the service method, migration upgrade/downgrade/upgrade and drift check through `/run-db-suite`.

## Verification requirements
Dated runs with commands, exit codes and counts (T-014 format), local PostgreSQL only.

## Acceptance criteria
The owner has approved the view definitions; the views return the specified aggregates on synthetic data; no cross-workspace leakage; migration reversible; evidence recorded.

## Evidence
None recorded.

## Review and approval
Not requested. **Gate: always** (migration; contract).
