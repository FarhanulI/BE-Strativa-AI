# T-011: AI Platform synchronous `run` path (fake provider)

- **Module and phase:** ai_platform, Phase 2 (sub-task of T-008, part (b))
- **State:** In Progress (plan approved by the owner with "start step 1", 2026-11-21)
- **Requirement IDs:** (all exist in the spec and the traceability matrix; coverage is limited to the `run` path unless stated. Completing the `run` clause of a criterion does not make the whole criterion verified.)
  - Invariants: INV-4 (`run` path only; the `execute_request` and `embed_texts` paths stay open), INV-6, INV-7, INV-8, INV-9, INV-23, INV-24, INV-26, INV-29 (`run` path only).
  - Acceptance criteria:
    - AC-9: `run` part only (spec 17.1, [spec.md:1004](../specs/ai-platform/spec.md#L1004)). The `execute_request` and `embed_texts` clauses stay open.
    - AC-15, AC-17, AC-18, AC-19, AC-22, AC-23, AC-24, AC-25, AC-26, AC-27.
    - AC-16: `run` part only ([spec.md:1014](../specs/ai-platform/spec.md#L1014)). The async (`execute_request`) outcomes in table 10.3 stay open.
    - AC-28: `run` and repair paths ([spec.md:1035](../specs/ai-platform/spec.md#L1035)).
    - AC-29: `run` part only; the spec names both billing modes and the `ai_requests` totals.
    - AC-38: `run`, repair call and fallback call only ([spec.md:1061](../specs/ai-platform/spec.md#L1061)). The `execute_request` clause stays open.
    - AC-51: `run` with a `from_workspace` user context and with `for_worker` ([spec.md:1086](../specs/ai-platform/spec.md#L1086)). The `submit` clause stays open.
    - AC-59 ([spec.md:1095](../specs/ai-platform/spec.md#L1095)): reservation equals the Router estimate, "implemented with the orchestrator".
  - Not claimed, although the code touches them: AC-21 (modality; the rejection is implemented here, the Router image-capable selection part is not tested here), AC-36, AC-58, INV-13, INV-32 (supporting runs may be noted in traceability, status unchanged).
- **Specification references:** [AI Platform spec](../specs/ai-platform/spec.md): 4.5 (sync request lifecycle), 5.2 (orchestrator, transaction ownership), 10.2 to 10.3 (router, failure behavior), 11 and 11.1 (strict output, repair, untrusted context), 12.1 to 12.3 (usage, cost, budgets), 16, 17; [traceability.md](../traceability.md); [decisions.md](../decisions.md) (SDD-D-7).
- **Dependencies:**
  - **SDD-D-7** (development resumed), accepted 2026-11-19.
  - **Revisions 5 to 7 of the spec (T-006).** T-011 relies on rev 5 to 7 decisions that the orchestrator must implement. The owner approved revisions 5 to 7 on 2026-11-19 ("owner decision, this conversation", option (a)); this is recorded in the spec header lines 5 and 7 and in [T-006](T-006-ai-platform-approval-clarification.md). No requirement text was changed by that approval.
  - **Decisions the task implements or uses**, and where each stands in code today (checked 2026-11-19):

    | Decision | Spec | Exists in code | Not yet in code |
    | --- | --- | --- | --- |
    | D-24 reservation equals Router estimate | [spec.md:1228](../specs/ai-platform/spec.md#L1228) | `RoutedModel.estimated_cost_micro_usd` ([router.py:164-170](../../app/ai_platform/router.py#L164-L170)); `reserve_for_call(estimate_micro_usd=...)` ([budget_coordinator.py:144](../../app/ai_platform/budget_coordinator.py#L144)) | The wiring that passes the Router estimate, unchanged, to the reservation (AC-59) |
    | D-26 and D-31 effective output cap | [spec.md:1230](../specs/ai-platform/spec.md#L1230), [spec.md:1235](../specs/ai-platform/spec.md#L1235) | `RoutedModel.effective_max_output_units` ([router.py:166-169](../../app/ai_platform/router.py#L166-L169)); `ProviderGenerationRequest.max_output_units` ([provider.py:41-42](../../app/ai_platform/provider.py#L41-L42)) | Passing the effective value to the provider request |
    | D-33 single refusal path | [spec.md:1236](../specs/ai-platform/spec.md#L1236) | `BudgetCoordinator.refuse_for_call` ([budget_coordinator.py:199](../../app/ai_platform/budget_coordinator.py#L199)); refusal inside `reserve_for_call` ([budget_coordinator.py:144-160](../../app/ai_platform/budget_coordinator.py#L144-L160)) | The orchestrator calling it for a Router step-7 refusal and ending the request row `failed` |
    | D-34 repair reservation | [spec.md:790](../specs/ai-platform/spec.md#L790) | `build_repair_messages` ([messages.py:79](../../app/ai_platform/messages.py#L79)) | Repair reservation sizing, the ceiling check, skipping the repair (no `D-34` reference exists under `app/ai_platform/`, checked by search) |
    | D-35 breaker denial at call time | [spec.md:757](../specs/ai-platform/spec.md#L757) | `CircuitBreakerRegistry.begin_attempt` returns a bool ([circuit_breaker.py:90](../../app/ai_platform/circuit_breaker.py#L90)) | The skip-without-attempt-or-ledger-row behavior and the `provider_unavailable` ending (no `D-35` reference exists under `app/ai_platform/`) |
    | D-7 user-path restriction | [spec.md:1211](../specs/ai-platform/spec.md#L1211) | Task latency classes ([tasks.py](../../app/ai_platform/tasks.py)) | The check in `run` |
    | D-22 explicit key passing | [spec.md:1226](../specs/ai-platform/spec.md#L1226) | `ProviderClient.generate(..., api_key=...)` ([provider.py:96-101](../../app/ai_platform/provider.py#L96-L101)); the fake provider records the key | Passing the configured key from `run` |

  - **T-004 (D-32) does not block T-011.** D-32 is referenced by `failure_policy.final_error` ([failure_policy.py:186-200](../../app/ai_platform/failure_policy.py#L186-L200)) and is not defined in the spec ([decisions.md](../decisions.md) section 6). T-011 reuses `final_error` unchanged. For the all-invalid-output case the result matches the spec ([spec.md:752](../specs/ai-platform/spec.md#L752), AC-24). For mixed failures the spec says only "raise `AiProviderUnavailable`, or the specific error above" ([spec.md:760](../specs/ai-platform/spec.md#L760)), so T-011 tests the mixed-failure outcome as "current behavior, D-32 unresolved" and does not assign a meaning to D-32.
  - Existing components used and not changed: Router (`router.py`), failure policy, output validation (`validation.py`), message builder (`messages.py`), circuit breaker, fake provider, `BudgetCoordinator`, request and budget repositories, task and schema registries.
  - Local Postgres test container, run only through `/run-db-suite`. No Neon.

## Plan update, 2026-11-21 (owner start of step 1)
- Spec line anchors above predate revisions 8 and 9 (T-018, T-019) and are approximate; the section numbers are authoritative.
- `run` passes `request.instructions_version` to `insert_sync_request` (T-019, D-36). Steps 2 and 3 assert it is stored. The same-key, different-label `Conflict` stays with `submit` and is not in this task.
- No migration or schema change is needed; the "stop on schema change" rule still holds.
- Judgment calls in step 1 (owner to confirm): a disallowed scope raises core `ValidationFailed` with the fixed detail `This AI task is not available for this call scope`, because the spec names no error class for it; an omitted `output_schema_version` resolves to the task definition's `default_output_schema_version`.
- Split (steps 7 to 10 as a follow-up task) and the fresh-context audit before `Verified` are still open owner decisions; the work continues with all ten steps and a stop after each.

## Objective
Add the `AiOrchestrator.run` implementation that ties the existing, individually tested parts into one request flow: validate, create the `ai_requests` row, route, reserve, call a `ProviderClient`, validate output (with the repair call), fall back, settle and finish the row. Close the `run` clauses of the requirements above that are `Specified` or partial only because no orchestrator exists. Use the fake provider only.

## Scope
- `AiOrchestrator` with `run` only, built with an `async_sessionmaker`, the config, catalog, clock, breaker, `BudgetCoordinator`, repositories and a `ProviderClient` (spec 5.2).
- Pre-routing validation with nothing written (spec 4.5): unknown or unready task, disallowed scope, the user-path restriction (D-7), unsupported modality.
- Sync lifecycle (spec 4.5): row inserted in its own transaction as `running`; ends `succeeded` or `failed` with `error_code` and `completed_at`. Refused or unroutable calls (`no_route`, `input_too_large`, `provider_not_configured`, `budget_exceeded`) end the row `failed` with no usage row and no reservation. A budget refusal goes through the single refusal path (D-33) before `AiBudgetExceeded`.
- **Missing credentials, zero calls (spec 10.3 table, last row; AC-16):** no reservation, no provider call, no usage row, raise `AiProviderNotConfigured`, row `failed` with `provider_not_configured`.
- Per attempt: reserve with the Router estimate (D-24) in its own transaction, provider call with no open transaction and the effective output cap (D-26, D-31), settle in its own transaction; one usage row per attempt; `call_kind` `initial` or `repair`; `route_rank`.
- Fallback in rank order up to `max_provider_attempts` distinct models, billing-mode constraint (INV-29, AC-17), error mapping per table 10.3, terminal kinds without fallback (`content_refused`, `provider_bad_request`), final error via `final_error` unchanged.
- **Request-deadline stop (spec 10.3, [spec.md:759](../specs/ai-platform/spec.md#L759)):** before the next candidate, stop and fail with `provider_timeout` when the remaining time is below that candidate's `latency_p50_ms`, using `next_attempt_allowed` ([failure_policy.py:209](../../app/ai_platform/failure_policy.py#L209)) and `deadline_stop_error_code` ([failure_policy.py:231](../../app/ai_platform/failure_policy.py#L231)), with the injected `FakeClock`.
- Repair-once with its own reservation and ceiling check (D-34); attempt cap (INV-9); truncation is not repaired and falls back (AC-25).
- Breaker denial at call time (D-35): skip the candidate without an attempt and without a ledger row; `provider_unavailable` when all remaining candidates are skipped.
- Untrusted-context integration (INV-24, AC-28): build generation messages with `build_generation_messages` and repair messages with `build_repair_messages`; no tools, functions or `tool_choice`; sentinel content in no log, event, audit detail, usage row, error or problem response.
- `persist_result` handling, `AiTaskResult` and `AiUsageSummary` construction (no provider or model name, opaque `routing_id`).
- Export of the added public name through `app/ai_platform/__init__.py` as spec section 5 requires.

## Non-goals
- The LiteLLM adapter and any real provider call (AC-54 to AC-57; INV-1 stays `Specified`).
- `submit`, `get_status`, `get_output`, `execute_request`, leases, heartbeats, the reaper, purge, reconcile jobs and the cron CLI (AC-39 to AC-50, INV-16, INV-17, INV-25, INV-28).
- `embed_texts` (AC-8 embedding part, INV-12).
- HTTP endpoints, UI, the real catalog file wiring (the catalog data and AC-60 were done in T-018; `run` is tested with the synthetic catalog), any change to the specification, requirements or decisions.
- Any change to migrations or the schema. If one is needed, stop and write a change proposal.
- Changes to the Router, failure policy, message builder, breaker or `BudgetCoordinator`. If a defect is found, stop and report.
- Resolving D-32 or D-20 (T-004, T-005). Neon runs. Real-provider spend.

## Implementation expectations
Ten steps. Each step is its own commit citing `T-011` and its requirement IDs, and stops for owner review (standing rules). Test layer is stated per step.

1. **Skeleton and pre-routing validation (unit only, no DB).** `app/ai_platform/orchestrator.py` skeleton and `run` rejections: unknown or unready task (INV-23, AC-26), disallowed scope, user-path restriction (INV-26, D-7; AC-51 rejection and the `for_worker` success only as far as unit tests with a fake session factory can show), unsupported modality. Asserts that the fake provider received zero calls. No row-level assertions here.
2. **Request lifecycle and refusal paths (DB).** Row creation, `failed` endings for `no_route`, `input_too_large`, `provider_not_configured` (zero-call case), `budget_exceeded` via the D-33 path. Asserts: no usage row, no reservation, one metadata-only request row (this includes the AC-51 "no usage row, no reservation" assertions).
3. **Single successful call (DB).** Reserve the Router estimate unchanged (D-24, AC-59), call with the effective output cap (D-31) and the configured key (D-22), validate, settle, finish; `AiTaskResult`, usage summary, `persist_result`. AC-22, AC-29 (`run`), INV-7, INV-8, AC-59.
4. **Fallback, error mapping and deadline stop.** Table 10.3 outcomes for timeout, connection, 5xx, rate limit, auth failure, bad request, content refusal; fallback and `route_rank`; terminal kinds; deadline stop with `FakeClock`; final error through `final_error` unchanged (mixed-failure case tested as "current behavior, D-32 unresolved"). AC-15, AC-16 (`run`), AC-18, AC-19.
5. **Billing-mode constraint and breaker denial (D-35).** One billing mode per request, quota exhaustion never crosses to `paid`, excluded candidates carry `billing_mode`; breaker denial skips without an attempt and without a ledger row, `provider_unavailable` when all are skipped. AC-17, INV-29 (`run`), D-35.
6. **Repair, truncation and attempt cap (D-34).** Strict-validation failure then one repair call to the same model with its own reservation and ceiling check; skip the repair when over the ceiling; repair `budget_exceeded` through D-33; truncation not repaired and falls back; invalid-always provider limited to the cap. AC-23, AC-24, AC-25, AC-27, INV-9, INV-8.
7. **Untrusted-context integration (INV-24, AC-28).** Context only in the data message, new marker on collision, no tools parameter, injection-obeying provider output rejected through repair, fallback and `AiOutputInvalid`, sentinel absent from logs, events, audit details, usage rows, errors.
8. **Lock-free provider call (DB, depends on steps 3, 4 and 6).** Spy `ProviderClient` with a separate connection (`FOR UPDATE NOWAIT` on the budget and request rows, no `idle in transaction` for the orchestrator's `application_name`), for `run`, a repair call and a fallback call. AC-38 (`run` part), INV-6.
9. **Router-before-provider proof (depends on steps 3 to 6).** Spy router and spy provider assert every provider call is preceded by a Router decision for the same request. AC-9 (`run` part), INV-4 (`run` part).
10. **Traceability and documentation.** Update the affected rows with dated evidence only; module documentation only if the public contract wording changes. No spec edits.

Boundaries: product code only under `app/ai_platform/`. Persistence stays inside the module. Logs, events and errors carry no prompts, completions or user content. No event payload key contains "token".

## Required tests
- Unit (no DB): steps 1, 4 (policy sequencing), 5 (breaker denial), 6 (attempt cap), 7 (message and sentinel checks), plus the existing architecture tests (litellm boundary, provider identifiers, clock).
- Database (marker `db`, local Postgres container only): steps 2, 3, 4 (ledger rows), 5, 6, 8.
- Every test names the requirement IDs it covers. Synthetic text only.

## Verification requirements
- Unit tests run with the repository's pytest configuration ([pyproject.toml](../../pyproject.toml)). Database tests run only through `/run-db-suite` on the local Postgres container (`TEST_DB_MODE=local`, `APP_ENV=test`). No new commands or scripts are created.
- Evidence per requirement: date, command or skill, environment, counts, recorded in this task and in [traceability.md](../traceability.md).
- Local PostgreSQL verifies no requirement that names Neon. No requirement in this task names Neon, and no Neon operation is authorized.
- No requirement is marked `Verified` without that evidence. A requirement covered only for its `run` clause stays partial and names the open clause.

## Acceptance criteria
- Each listed requirement ID has at least one mapped, executed test for its `run` clause, with dated evidence, or keeps its previous status with the open clause named.
- `run` has no path to a provider that skips the Router; no provider call occurs inside a database transaction; invalid output is never returned or stored.
- Public types expose no provider or model name; no prompt, completion or user content appears in logs, events or errors.
- The unit suite, the architecture tests and the DB suite pass in the recorded runs; any failure is reported with its output.
- Traceability updated for: INV-4 (`run`), INV-6, INV-7, INV-8, INV-9, INV-23, INV-24, INV-26, INV-29 (`run`), AC-9 (`run`), AC-15 to AC-19, AC-22 to AC-29, AC-38 (`run`), AC-51, AC-59. AC-36, AC-58, INV-13 and INV-32 keep their status.

## Evidence
- **Step 1 (2026-11-21):** `env -u TEST_REDIS_URL uv run python scripts/check.py` exit 0, 1781 passed, 0 failed, 4 skipped (redis), 217 deselected (db). Local Windows, DB-free. New: `app/ai_platform/orchestrator.py`, `tests/unit/ai_platform/test_orchestrator_validation.py` (19 tests). Two existing export-list tests were extended with `AiOrchestrator`. No requirement status changes yet (traceability is step 10).
- **Step 2 (2026-11-22), DB-free part:** `env -u TEST_REDIS_URL uv run python scripts/check.py` exit 0, 1781 passed, 0 failed, 4 skipped (redis), 223 deselected (217 earlier db tests plus 6 new). New: row creation, Router call and refusal endings in `app/ai_platform/orchestrator.py`; `tests/db/test_orchestrator_run_refusals.py` (6 db tests). Two step-1 tests were changed from `run` to `validate_run` because `run` now reaches the database after validation. The 6 DB tests were run by the owner on 2026-11-22 with `/run-db-suite all` (`bash scripts/run_db_suite.sh all`, local Postgres container, `TEST_DB_MODE=local`): exit 0, 223 passed, 0 failed, 1785 deselected, `cleanup done`. Step 2 approved by the owner 2026-11-22.
- Step 2 judgment calls (owner to confirm): `UnitEstimator` is a constructor argument (the spec's estimator has no default implementation); `ROUTING_VERSION = "router-10.2-r1"` is a new constant (the spec fixes no value); a Router `modality_not_supported` result ends the row `no_route` (the spec lists no separate code) and still raises `AiModalityNotSupported`; the DB tests use a worker context because a user context needs a real `users` row for the foreign key.
- **Step 3 (2026-11-22), DB-free part:** `env -u TEST_REDIS_URL uv run python scripts/check.py` exit 0, 1781 passed, 0 failed, 4 skipped (redis), 231 deselected (db). New: the single provider attempt in `app/ai_platform/orchestrator.py` (reserve the Router estimate, call, validate, settle, finish); `tests/helpers/orchestrator_db.py`; `tests/db/test_orchestrator_run_success.py` (9 db tests). The step 2 transitional test (routable call left `running`) was removed from `test_orchestrator_run_refusals.py` because the success test now covers row creation (db tests there: 5). The 9 new DB tests have NOT RUN: they need the owner's `/run-db-suite all`.
- Step 3 judgment calls (owner to confirm): `call_kind` is `generation` (the schema value; the task text says "initial"); the circuit breaker is not touched yet (its `begin_attempt`, `record_success` and `record_failure` pairing arrives with D-35 in step 5); a first call that fails or returns invalid output is settled `failed` and then stops at `NotImplementedError` with the request row left `running` until steps 4 to 6; a response without usage is metered from the platform estimator (spec 12.1 says the adapter does this, and the fake provider has no adapter) and no `usage_source` log is written; the call timeout is the time left of the latency-class deadline.
- **Step 3 DB run (2026-11-23), FAILED:** owner ran `/run-db-suite all` (`bash scripts/run_db_suite.sh all`, local Postgres container): 8 failed, 223 passed, exit 1, `cleanup done`. The 8 failures were the step 3 tests that reserve a call: `ValueError: candidate_snapshot entries allow only model, eligible, reason_code`. Cause: spec 4.2 listed three snapshot keys, spec 10.5 and the Router four. Only the reservation-refusal test passed.
- **Scope extension and CP-3 (2026-11-23):** the owner approved [CP-3](../specs/ai-platform/change-proposals/CP-3-candidate-snapshot-provider.md) (spec revision 10: `provider` in the 4.2 snapshot entries) and extending T-011 to `app/ai_platform/budget_repository.py` (`_SNAPSHOT_KEYS` and its error text) and its validator unit tests. Nothing else outside the task scope changed. Added `test_snapshot_entries_with_provider_are_accepted_by_validation`; the DB-level assertion that the stored snapshot equals the Router snapshot is added to the step 3 DB tests. DB-free gate after the change (2026-11-23): `env -u TEST_REDIS_URL uv run python scripts/check.py` exit 0, 1782 passed, 0 failed, 4 skipped (redis), 231 deselected (db). 
- **Step 3 DB rerun 1 (2026-11-23):** owner ran `/run-db-suite all` after the fix: 1 failed, 230 passed, 1786 deselected, `cleanup done`. The 8 snapshot failures are gone. The one failure, `test_persist_result_stores_the_output_only_when_asked` (`AssertionError`), was a test defect: both rows share one `FakeClock` timestamp, so `ORDER BY created_at` was arbitrary. Fixed by matching each row on its returned `request_id`; the orchestrator behavior was correct. The next rerun is NOT RUN: it needs the owner's `/run-db-suite all`. Step 3 stays unverified until then.

## Review and approval
Not requested. Owner approval is recorded elsewhere only for the spec revisions (T-006, 2026-11-19), not for this task.

## Risks and architectural considerations
- **Spec approval basis.** The revision 5 to 7 approval is a conversation-recorded owner decision (T-006), with no earlier evidence. If the owner later amends those revisions, steps 3, 5 and 6 are the affected ones.
- **Stale register row.** [decisions.md](../decisions.md) section 6 ("AI Platform approval history") still describes revisions 5 to 7 as unapproved. It is outside this task's edit scope and needs an owner-approved docs update.
- **Transaction ownership** deviates deliberately from "caller owns the session" (spec 5.2). A provider call must never run inside a database transaction.
- **Lock order** request, usage record, budget row (INV-32) applies to every multi-row transaction written here.
- **`run` must not become the shape `execute_request` copies without fencing (INV-28).** Keep the attempt loop reusable and add no lease code.
- **Partial criteria.** AC-9, AC-16, AC-29, AC-38 and AC-51 keep open clauses (`execute_request`, `embed_texts`, `submit`), and the matrix must not show them `Verified` on `run` evidence alone.
- **D-32 behavior in mixed failures** is observed, not specified.
- **Size.** Ten steps with an owner review after each. If this is too large, the natural split is after step 6, with steps 7 to 10 as a second task.
- **Template.** This Risks section is not in the canonical task template. Proposal only (not applied): add an optional "Risks and architectural considerations" section to the template in [tasks/README.md](README.md), because several tasks need to record risks and dependencies the other sections cannot hold. The owner decides.
