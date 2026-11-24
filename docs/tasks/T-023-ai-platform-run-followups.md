# T-023: AI Platform `run` follow-ups from the T-011 audit

- **Module and phase:** ai_platform, Phase 2 (follow-up to T-011; part of T-008)
- **State:** Ready (approved by the owner 2026-11-24, "approve T-023 as Ready, use defaults for D-B to D-D"). Decisions D-B, D-C and D-D are settled to their proposed defaults. D-A is settled (owner, 2026-11-24): reuse `execution_abandoned`. D-E is settled (owner, 2026-11-24): not a defect. D-F is settled (owner, 2026-11-24): keep INV-9, INV-23 and INV-29 at `Implemented`. All decisions D-A to D-F are now recorded; nothing blocks steps 3 to 6.
- **Requirement IDs:** (all exist in the spec and the traceability matrix; coverage is limited to the `run` path unless stated)
  - Invariants: INV-7 (every attempt settled or abandoned exactly once), INV-14 (cost never undercounts; an abandoned reservation is charged at its estimate), INV-9, INV-23, INV-29 (promotion decision only, no code).
  - Acceptance criteria: AC-45 (`run` part: a sync row ends `succeeded` or `failed`), AC-16, AC-29, AC-59 (clauses the audit found unasserted, tests only), AC-9 (adapter-reference clause stays open, named only).
  - Spec section without an ID: 4.5 (sync request lifecycle, "Statuses": `running` then `succeeded` or `failed`).
- **Specification references:** [AI Platform spec](../specs/ai-platform/spec.md): 4.5 ([spec.md:247](../specs/ai-platform/spec.md#L247)), 5.4 (persisted `error_code` list, [spec.md:402](../specs/ai-platform/spec.md#L402)), 8.2 (reaper), 10.3 ([spec.md:740](../specs/ai-platform/spec.md#L740)), 12.1; [traceability.md](../traceability.md); [T-011](T-011-ai-platform-sync-run-path.md) (Audit and Open after the audit entries).
- **Dependencies:**
  - T-011 steps 1 to 10 committed (done; the owner confirmed step 10 is pushed). This task starts only after the owner approves it as `Ready`.
  - **Owner decisions needed before step 2** (listed in the Scope, section "Decisions"). If the owner chooses a new `error_code`, a spec change proposal and a new spec revision come first (rule 4); the task then stays `Blocked` on it.
  - Local Postgres test container, run only through `/run-db-suite`. No Neon.
  - Does not depend on T-004 (D-32), T-005 or T-022.

## Objective
Close what the fresh-context audit of T-011 (2026-11-24, `spec-auditor`) left open, in order of risk:
1. **Unexpected exceptions leave rows open.** `AiOrchestrator.run` catches only `AiBudgetExceeded` ([orchestrator.py:213-272](../../app/ai_platform/orchestrator.py#L213-L272)). Any other exception during an attempt (a non-`ProviderCallError` raised by the provider, a database error while settling, task cancellation) leaves the request row `running` and the in-flight usage row `reserved`, until a reaper that does not exist yet. Spec 4.5 says the row ends `succeeded` or `failed`. This is untested and was not recorded as open before the audit.
2. **Unasserted clauses.** AC-29, AC-59 and AC-16 have clauses no test asserts (see Scope).
3. **A possible deadline gap.** The deadline stop is skipped while no candidate has been attempted ([orchestrator.py:217](../../app/ai_platform/orchestrator.py#L217)).
4. **Stale traceability notes** in rows T-011 did not touch, and the promotion decision for INV-9, INV-23 and INV-29.

## Scope
**Decisions (owner, before step 2).** Proposed defaults are marked. Owner decision 2026-11-24: D-B, D-C and D-D take their proposed defaults (the budget_coordinator.py change in D-B is therefore in scope). D-A: option (a), reuse `execution_abandoned` (owner, 2026-11-24; no spec change and no change proposal; the spec meaning "caller crashed" now also covers "caller alive, unexpected exception", which the Notes of the affected rows must say). D-E: not a defect (owner, 2026-11-24; the spec wording "next candidate" describes a candidate after an attempt, a breaker denial costs no time and the first call's timeout is already the time left; no code and no test). D-F: keep INV-9, INV-23 and INV-29 at `Implemented` until `execute_request` exists (owner, 2026-11-24), consistent with INV-4, INV-6, INV-7 and INV-8.
- **D-A. Persisted code for an unexpected exception.** The spec's `error_code` list is closed ([spec.md:402](../specs/ai-platform/spec.md#L402)) and has no internal-error value.
  - (a) Reuse `execution_abandoned`. No spec change. Its spec meaning is "the caller crashed" (4.5, 8.2), which differs from "the caller is alive and an exception was raised", so reports would mix two causes.
  - (b) Add a new code (for example `internal_error`) by a change proposal and a new spec revision. Cleaner, but it adds a decision and blocks the task until approved.
  - Default proposed: (b) if the owner wants the two causes separated, otherwise (a). The agent does not choose.
- **D-B. What happens to the in-flight reservation.** Proposed default: abandon it (the usage row becomes `abandoned`, cost equals the reserved estimate, the budget row's reservation is released in one statement), because the call may have been billed and INV-14 forbids undercounting. This needs a `BudgetCoordinator` method that wraps the existing `budget_repository.abandon_usage_record` (the repository function exists; the coordinator has no such method, so the change to `budget_coordinator.py` is in scope of this task only if the owner agrees here).
- **D-C. What the caller sees.** Proposed default: finish the row, release the reservation, then re-raise the original exception unchanged. The orchestrator does not wrap it and does not swallow it.
- **D-D. Cancellation.** Proposed default: handle `asyncio.CancelledError` too, with the cleanup shielded so it completes, then re-raise. If the owner prefers, cancellation is left to the reaper and recorded as an open item.
- **D-E. Deadline edge.** Spec 10.3 says the orchestrator stops "when the remaining time is below the next candidate's `latency_p50_ms`". It is unclear whether this covers the first candidate actually attempted after earlier candidates were breaker-denied (D-35). Owner picks: apply the check to every attempted candidate, or record it as not a defect.
- **D-F. Promotion.** Whether INV-9, INV-23 and INV-29 move to `Verified` on `run` evidence alone, given that they are path-agnostic and `submit` and `execute_request` do not exist yet.

**Work.**
- Unexpected-exception handling in `run` per D-A to D-D: end the request row `failed` with the chosen code, abandon the in-flight reservation (D-B), keep the breaker `abandon_attempt` behavior, re-raise (D-C). No event, no log content, no prompt or completion in any message.
- Tests that close the audit's unasserted clauses, tests only unless a defect is found (then stop and report):
  - AC-29: a `paid` call records the same formula-based cost as `free_tier`; the cost is metered, not an invoice; `price_version` and `period_start` on the orchestrator-written row; the expected cost computed by an independent formula, not by `cost_micro_usd`.
  - AC-59 second sentence: a Router-admitted candidate is admitted by the reservation and a Router-removed one is refused, at equal figures, including the boundary.
  - AC-16: the request-level `error_code` and the raised class when every candidate fails with connection, rate limit, auth and truncation (only per-attempt codes are asserted today).
- Deadline edge per D-E: no code and no test. Record the decision (and its reason) in the traceability Notes of the row that names the deadline stop, if any, and in this task.
- Traceability: refresh the stale notes in AC-21, AC-4, AC-3, INV-31, INV-11 and AC-8, and any other row with the same stale phrasing found by search (for example INV-2); apply D-F; add dated evidence. No spec edits.

## Non-goals
- `submit`, `get_status`, `get_output`, `execute_request`, leases, the reaper, purge, reconcile jobs, the cron CLI (AC-39 to AC-50, INV-16, INV-17, INV-25, INV-28).
- `embed_texts`, the LiteLLM adapter, any real provider call, HTTP endpoints, UI.
- Changes to the Router, failure policy, message builder, breaker or migrations. The only product files allowed: `app/ai_platform/orchestrator.py` and, if D-B is accepted, `app/ai_platform/budget_coordinator.py` (one new method). If any other defect or a schema change is needed, stop and write a change proposal.
- Resolving D-32 or D-20 (T-004, T-005). Neon runs. Real-provider spend.
- Editing the spec or decisions. A new `error_code` (D-A option b) goes through a change proposal, not this task's edits.

## Implementation expectations
Six steps. Each step is its own commit citing `T-023` and its requirement IDs, and stops for owner review (standing rules).
1. **Owner decisions D-A to D-F.** No code. D-A to D-D are recorded (D-A is option (a), so no change proposal is needed). D-E and D-F are collected before steps 5 and 6.
2. **Red tests (DB).** Fault injection through the existing helper hooks: a provider that raises an unexpected exception, a coordinator whose settle fails, and (if D-D accepts it) a cancelled call. Assert the intended outcome (row `failed`, reservation abandoned, budget `reserved` back to 0 and `spent` equal to the estimate, usage row `abandoned`, exception re-raised unchanged, no content in the stored rows, logs or errors). The tests fail against current code, and the failure is recorded.
3. **Implementation (DB).** `run` handling and, if D-B is accepted, the coordinator method. The step 2 tests pass; the T-011 DB tests still pass.
4. **Closing tests for AC-29, AC-59 and AC-16 (DB).** Tests only.
5. **Deadline edge** per D-E: not a defect, so no code and no test. The step only records the decision. It may be merged into step 6.
6. **Traceability and evidence.** Stale notes, D-F, dated evidence in the task and the matrix.

Boundaries: product code only under `app/ai_platform/`. Persistence stays inside the module. No lock order violation (request, usage record, budget row; INV-32). No provider call inside a transaction (INV-6): the cleanup runs after the provider call has returned or failed.

## Required tests
- Database (marker `db`, local Postgres only): steps 2, 3, 4 and 5 (fault injection, abandon accounting, the three clause groups, the deadline case).
- Unit (no DB): any pure helper added; the existing architecture tests (litellm boundary, provider identifiers, clock) stay green.
- Every test names the requirement IDs it covers. Synthetic text only.

## Verification requirements
- DB-free gate: `env -u TEST_REDIS_URL uv run python scripts/check.py`. Database tests run only through `/run-db-suite` on the local Postgres container (`TEST_DB_MODE=local`, `APP_ENV=test`). No new commands or scripts.
- Evidence per requirement: date, command or skill, environment, counts, recorded in this task and in [traceability.md](../traceability.md). Anything not run is written `NOT RUN` with the reason.
- Local PostgreSQL verifies no requirement that names Neon; none here does.
- A fresh-context `spec-auditor` run before the task moves to `Verified` or owner review (rule 20). The implementing session does not audit its own work.
- No requirement becomes `Verified` without executed, dated evidence. A requirement covered only for `run` stays partial and names the open clause.

## Acceptance criteria
- After any exception during an attempt (and a cancelled call if D-D accepts it), the request row is `failed` with the code chosen in D-A, the in-flight usage row is `abandoned` at its reserved estimate (if D-B accepts it), the budget row's reservation is released, and the original exception reaches the caller unchanged. The T-011 DB tests still pass.
- No prompt, completion or user content appears in any stored row, log or error of that path. No event payload key contains "token".
- The clauses listed under AC-29, AC-59 and AC-16 each have an executed test, or the traceability Notes keep naming them as open.
- The deadline edge has the owner's recorded decision (D-E: not a defect, no code change).
- The six stale notes (and any same-phrasing rows found) match the current code; D-F is applied: INV-9, INV-23 and INV-29 keep `Implemented`, and their Notes name `submit` and `execute_request` as the open paths.
- The unit suite, the architecture tests and the DB suite pass in recorded runs; any failure is reported with its output. The independent audit reports PASS or lists what remains.

## Evidence
- **Step 2 (2026-11-24), DB-free part:** `env -u TEST_REDIS_URL uv run python scripts/check.py` (ruff, mypy, pytest) passed: 1798 passed, 4 skipped (redis), 279 deselected (db: 276 earlier plus 3 new). Local Windows, DB-free. No product code changed. New: `tests/db/test_orchestrator_run_unexpected_errors.py` (3 db tests, INV-7, INV-14, AC-45 `run`): an unexpected provider exception (a `responder` that raises `RuntimeError`), a failure while settling (a `BudgetCoordinator` whose `settle_call` raises, after a valid provider answer), and a cancelled call (the provider call is delayed, the task cancelled once the call is recorded). Each asserts the intended outcome of D-A to D-D: row `failed` with `execution_abandoned` and `completed_at`, one usage row `abandoned` with `cost_micro_usd = reserved_micro_usd` and `finished_at`, budget `reserved` 0 and `spent` equal to the estimate, the original exception re-raised unwrapped (cancellation stays `CancelledError`), and the sentinel text absent from the stored rows and the logs. The tests are written to FAIL against the T-011 code. The red run has NOT RUN: it needs the owner's `/run-db-suite all`, and the failure output is to be recorded here. Expected, not observed (before the run): 3 failures, each an `AssertionError` on the row or usage status; 276 passed.
- **Step 2 red run (2026-11-24):** the owner ran `/run-db-suite all` (`bash scripts/run_db_suite.sh all`, local Postgres container, `TEST_DB_MODE=local`, `APP_ENV=test`): exit 1, 3 failed, 273 passed, 3 errors, 1802 deselected, `cleanup done`. The 3 failures are the 3 new tests, as intended (red): all `AssertionError`. The output of `test_a_cancelled_call_is_cleaned_up_and_stays_cancelled` shows `request row left 'running'` after the cancellation propagated correctly; the other two failures were read only from the summary list, with the same cause expected, not confirmed. The 3 errors are setup errors in `tests/db/test_outbox_relay_redis.py` (`test_relay_publishes_correlation_metadata_to_the_stream`, `test_relay_retries_with_bounded_backoff_then_publishes`, `test_one_request_id_follows_outbox_relay_worker_and_audit`); their messages were not seen. They are Redis-backed tests that passed in earlier runs, so an unavailable Redis is the likely cause, not confirmed. They are unrelated to T-023 and are to be re-run before step 3 is accepted.
- **Step 2 red run, rerun with Redis up (2026-11-24):** the owner started a `redis-dev` container (`redis:8`, port 6379) and ran `/run-db-suite all` again (`bash scripts/run_db_suite.sh all`, local Postgres container): exit 1, 3 failed, 276 passed, 0 errors, 1802 deselected, `cleanup done`. The 3 failures are the 3 new tests, all `AssertionError` (red, as intended); the 3 Redis errors of the first run are gone, so they were Redis being down. Step 2 approved by the owner 2026-11-24. The failure text was read in full only for the cancellation test (`request row left 'running'`); the other two were read from the summary list.
- Step 2 judgment calls (owner to confirm): the fault injection uses the existing hooks (`FakeAiProvider(responder=...)`, `coordinator_factory`), so no helper changed; a failing `settle_call` stands in for "a database error while settling"; the cancellation test uses `delay_seconds=3600` and cancels after the provider records the call, so it never waits an hour.
- **Step 3 (2026-11-24), DB-free part:** `env -u TEST_REDIS_URL uv run python scripts/check.py` (ruff, mypy, pytest) passed: 1798 passed, 4 skipped (redis), 279 deselected (db: 276 plus the 3 step 2 tests, which now should pass). Local Windows, DB-free. Changed: `app/ai_platform/orchestrator.py` and `app/ai_platform/budget_coordinator.py`. `run` now creates the row and then calls the new `_run_routed` (the old body, moved unchanged) inside `try/except BaseException`; the handler calls `_fail_open_request` (one conditional `complete_request`: `failed`, `execution_abandoned`, a no-op when the row already ended) and re-raises the original exception unchanged (D-A, D-C). `_attempt` reserves, then calls the new `_call_and_settle` (the old provider call and settlement, moved unchanged) inside `try/except BaseException`; the handler calls the new `BudgetCoordinator.abandon_call(usage_record_id)` (one transaction over the existing `abandon_usage_record`: usage row `abandoned` at its estimate, budget `reserved` moved to `spent`) and re-raises (D-B). Both cleanups run through `_finish_shielded`, which finishes the cleanup even when the task is cancelled and drops an error in the cleanup itself (the reaper remains the backstop) (D-D). The 3 step 2 tests and the T-011 DB tests have NOT RUN against this change: they need the owner's `/run-db-suite all`. Expected, not observed: 279 passed.
- Step 3 judgment calls (owner to confirm): the run-level handler runs on every exception, including the deliberate error classes (`AiBudgetExceeded`, `AiOutputInvalid` and so on) whose rows are already ended; it costs one extra conditional UPDATE on those error paths and changes nothing; an error inside the cleanup is dropped silently (no logging, by the module's rule), which leaves the reaper to finish the job; the breaker `abandon_attempt` in `_guarded_attempt` is unchanged and still runs after the new handler; `abandon_call` writes no event and no log record.

## Review and approval
Not requested. Plan approval is required before work starts (rule 18). Result review is required before the next task because the task may change an error-code contract (D-A) and accounting behavior.
