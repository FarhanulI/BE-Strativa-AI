# T-024: AI Platform `run` cleanup test gaps and edge decisions (follow-up to T-023)

- **Module and phase:** ai_platform, Phase 2 (follow-up to T-023; part of T-008)
- **State:** Ready (approved by the owner 2026-11-25, "approve T-024 as Ready, use defaults for D-A to D-D"). Decisions D-A to D-D are settled to their proposed defaults: D-A (a) keep, D-B (a) no bound, D-C (b) pass `None` before routing, D-D (a) keep silent. Nothing blocks steps 2 to 4; no change proposal is needed.
- **Requirement IDs:** (all exist in the spec and the traceability matrix; coverage stays limited to the `run` path)
  - Invariants: INV-7 (every attempt settled or abandoned exactly once), INV-14 (an abandoned reservation is charged at its estimate), INV-18 (no content in events, logs or errors).
  - Acceptance criteria: AC-45 (`run` part: a sync row ends `succeeded` or `failed`), AC-28 (no request content in stored rows, logs or events; `run` part).
  - Spec sections without an ID: 4.5 (sync lifecycle, reaper as backstop), 8.2 (reaper), 4.1 (`ai_requests.routing_version` is nullable, "router rules version used").
- **Specification references:** [AI Platform spec](../specs/ai-platform/spec.md): 4.1, 4.5, 8.2, 12.3 (lock order); [T-023](T-023-ai-platform-run-followups.md) (Decisions D-A to D-D, Evidence "Open test gaps"); [traceability.md](../traceability.md); the T-023 `spec-auditor` report of 2026-11-25 (should-fix and Note items).
- **Dependencies:**
  - T-023 Accepted (2026-11-25). It supplies the code under test: `AiOrchestrator._fail_open_request`, `_finish_shielded`, `BudgetCoordinator.abandon_call`.
  - Owner decisions D-A to D-D: settled 2026-11-25 to the defaults, none needs a spec change. If a later decision picks an option that does (a new config value, a new `error_code`), a change proposal comes first (rule 4) and the affected step stays `Blocked`.
  - Local Postgres container, run only through `/run-db-suite` (Redis up for the 3 Redis-backed tests). No Neon.
  - Does not depend on T-004 (D-32), T-005 or T-022.

## Objective
Close the cleanup-path gaps the T-023 audit left open, in order of risk:
1. **Failing cleanup is untested.** If `abandon_call` or the run-level completion raises, the error is dropped silently and the reaper (not built) is the only backstop. Nothing proves the original exception still reaches the caller, that no "exception was never retrieved" warning appears, or what state the rows are left in.
2. **A fault after earlier attempts settled is untested.** Every T-023 fault test fails the first attempt. INV-7 and INV-14 also have to hold when attempt 1 (or a repair call) settled and a later attempt raises.
3. **The content check is narrow.** The sentinel is looked for only in the request and usage rows and in `caplog`. The budget row, outbox rows and structlog output are not checked.
4. **Three edge behaviors have no recorded decision:** a cancellation that arrives during cleanup is swallowed; the cleanup has no timeout; the run-level handler writes `ROUTING_VERSION` even when the failure came before routing.

## Scope
**Decisions (owner, settled 2026-11-25: all four take the proposed default).** Chosen: D-A (a), D-B (a), D-C (b), D-D (a). The options below stay as written for the record.
- **D-A. Cancellation during cleanup.** Today `_finish_shielded` holds further cancellations until cleanup is done and drops them. If the original exception was not a `CancelledError`, that cancellation is lost.
  - (a) Keep. Pin it with a test. Reason: D-C of T-023 re-raises the original exception unchanged, and a task that is already failing ends the same way.
  - (b) After cleanup, re-deliver the cancellation (raise `CancelledError`, chained to the original). More conventional for asyncio, but it changes D-C for this rare case.
  - Default proposed: (a).
- **D-B. Cleanup timeout.** Today the shielded cleanup has no bound, so a hung database blocks a cancelled caller.
  - (a) No bound. Record it as an accepted risk; the connection layer's own timeouts apply. No code.
  - (b) A fixed module constant bounds the cleanup; on expiry it gives up and leaves the rest to the reaper.
  - (c) A configuration value. This adds a config key (spec 14 table, `.env.example` and `.env.local` under the ENV RULE) and needs a change proposal first.
  - Default proposed: (a), because the spec gives no value; (b) or (c) need a number the owner chooses.
- **D-C. `routing_version` before routing.** The column is nullable and `complete_request` keeps the stored value when it is given `None`. The run-level handler passes `ROUTING_VERSION` even if routing never ran.
  - (a) Leave it and record it (the value is the version in force, not a claim a decision was made).
  - (b) Pass `None` when no routing decision was made, so the column stays null; one small change in `orchestrator.py`, with a test. Step 3 first confirms from the row-creation code whether the insert already sets the column.
  - Default proposed: (b).
- **D-D. A dropped cleanup error.** Today it is dropped with no log.
  - (a) Keep silent. Pin it with a test.
  - (b) Write one fixed-message log record with the request id and the exception class name only, never the message (INV-18).
  - Default proposed: (a), as T-023 judged; (b) is cheap if the owner wants operators to see lost cleanups.

**Work.**
- Tests of the current behavior (steps 2): fault injection through the existing hooks (`FakeAiProvider(responder=...)`, `coordinator_factory`, `sessions=` on `build_orchestrator`); a small helper under `tests/helpers/` only if a hook is missing.
  - Failing cleanup: `abandon_call` raises; the run-level completion raises. Assert the original exception reaches the caller, no warning about an unretrieved task exception, and the stored states (usage row `reserved` until the reaper; request row per the failure injected), each stated in the test docstring.
  - Fault after settled attempts: (i) attempt 1 fails with a counted failure and settles, attempt 2 raises; (ii) a first call returns invalid output, and the repair call raises. Assert attempt 1 keeps its settled cost, the in-flight attempt is `abandoned` at its estimate, budget `reserved` is 0 and `spent` equals the sum, the request row is `failed` with `execution_abandoned`.
  - Wider content check on the T-023 fault paths: the sentinel is absent from the budget row, from structlog output (`structlog.testing.capture_logs`, as the T-011 context tests do), and from `caplog`; no new outbox or audit row is written by the cleanup (the helper that reads the outbox is identified in step 2).
- Decision-dependent changes (step 3), only what D-A to D-D select: a pinned-behavior test for (a) options; the code and test for any (b) option. Product code only in `app/ai_platform/orchestrator.py`.
- Traceability (step 4): Notes and Evidence of INV-7, INV-14, AC-45, INV-18 and AC-28; remove the closed gaps from the T-023 open list; no status promotion beyond what the audit supports.

## Non-goals
- The reaper, `submit`, `execute_request`, leases, purge, reconcile jobs (AC-39 to AC-50).
- The other items still open from T-023: signature reflection on `run` (INV-2, AC-3), the DB test for a Router-time modality refusal (AC-21), the AC-9 adapter clause, D-32 (T-004).
- Changes to the Router, failure policy, breaker, message builder, budget repository or migrations. If a defect needs one, stop and write a change proposal.
- A new `error_code`, a spec edit, or a decision change. D-B (c) goes through a change proposal, not this task's edits.
- Neon, real providers, paid calls, new dependencies.

## Implementation expectations
Four steps, each its own commit citing `T-024` and the requirement IDs, each stopping for owner review (standing rules).
1. **Owner decisions D-A to D-D.** No code. Done 2026-11-25: D-A (a), D-B (a), D-C (b), D-D (a); no change proposal needed.
2. **Tests of current behavior (DB).** The three groups above. They pass against the T-023 code. Each probe is shown able to fail: a negative self-check in the test (a deliberately leaked marker is detected), as the T-011 lock-probe test does. No product code changes in this step. DB-free gate, then the owner runs `/run-db-suite all`.
3. **Decision-dependent changes (DB).** D-A to D-D as chosen; a red test first where code changes, then the change, then green. If every default is chosen, only D-C (b) changes code.
4. **Traceability and evidence.** Notes, dated Evidence, T-023 open list updated; a fresh-context `spec-auditor` run before any status change.

Boundaries: product code only under `app/ai_platform/`, in `orchestrator.py`. Persistence stays inside the module. No lock order violation (request, usage record, budget row; INV-32). No provider call inside a transaction (INV-6).

## Required tests
- Database (marker `db`, local Postgres only): steps 2 and 3.
- Unit (no DB): any pure helper added; the existing architecture tests stay green.
- Every test names the requirement IDs it covers and uses synthetic text only.

## Verification requirements
- DB-free gate: `env -u TEST_REDIS_URL uv run python scripts/check.py`. Database tests only through `/run-db-suite` on the local Postgres container (`TEST_DB_MODE=local`, `APP_ENV=test`). Baseline before this task: 1798 passed, 4 skipped, 288 deselected (DB-free); 288 passed (DB suite). No new commands or scripts.
- Evidence per requirement: date, command or skill, environment, counts, in this task and in [traceability.md](../traceability.md). Anything not run is written `NOT RUN` with the reason.
- Local PostgreSQL verifies no requirement that names Neon; none here does.
- A fresh-context `spec-auditor` run before the task moves to `Verified` or owner review (rule 20).
- No requirement becomes `Verified` without executed, dated evidence; a requirement covered only for `run` stays partial and names the open clause.

## Acceptance criteria
- A failing `abandon_call` and a failing run-level completion each leave the original exception reaching the caller unchanged, with no unretrieved-exception warning, and the left-over row states are asserted and documented.
- A fault in a later attempt or in a repair call, after earlier attempts settled, leaves earlier attempts settled at their cost, the in-flight one `abandoned` at its estimate, `reserved` 0 and `spent` the exact sum.
- The sentinel is absent from the budget row, structlog output and `caplog` on the T-023 fault paths, and the cleanup writes no event or audit row.
- Each of D-A to D-D has the owner's recorded choice, and the chosen behavior has an executed test (or, for an accepted risk, a recorded sentence in the traceability Notes).
- The DB-free gate and the DB suite pass in recorded runs; any failure is reported with its output. The independent audit reports PASS or lists what remains.

## Evidence
- **Step 1 (2026-11-25):** owner decisions recorded: D-A (a), D-B (a), D-C (b), D-D (a). No code.
- **Step 2 (2026-11-25), DB-free part:** `env -u TEST_REDIS_URL uv run python scripts/check.py` (ruff, mypy, pytest) passed: 1798 passed, 4 skipped (redis), 296 deselected (db: 288 plus 8 new). Local Windows, DB-free. No product code changed. New: `tests/db/test_orchestrator_run_cleanup_edges.py` (8 db tests, INV-7, INV-14, INV-18, AC-45 `run`, AC-28 `run`). (1) A failing cleanup, 2 tests: `abandon_call` raising (a `BudgetCoordinator` subclass) and the run-level `UPDATE ai_requests` raising (a `before_cursor_execute` hook on the engine, removed in `finally`). Each asserts the caller sees the provider's exception unchanged (no `__cause__`), the cleanup error is absent from the log, no "never retrieved" asyncio warning after `gc.collect()`, and the left-over states: with `abandon_call` failing, the request row is `failed`/`execution_abandoned`, the usage row stays `reserved` and the budget keeps the reservation with `spent` 0; with the completion failing, the usage row is `abandoned` at its estimate, the budget `reserved` is 0, and the request row stays `running` with no `completed_at`. (2) A fault after settled attempts, 2 tests: a fallback call (attempt 1 `CONNECTION_ERROR` settled at 100 micro-USD, attempt 2 raises) and a repair call (first call invalid output settled at 1120, repair raises); each asserts the settled cost by an independent formula, the in-flight attempt `abandoned` at its estimate, `reserved` 0, `spent` equal to the exact sum, the request row `failed`/`execution_abandoned`. (3) The wider content check, 4 tests: one probe self-check (a sentinel planted in structlog and standard log output is found by the same collector) and one parametrized test over a provider exception, a failure while settling and a cancellation, asserting the sentinel is absent from the request, usage and budget rows, the outbox and audit rows of the budget row, structlog output and `caplog`, and that the cleanup wrote no outbox and no audit row.
- **Step 2 (2026-11-25), DB run:** `/run-db-suite all` (`bash scripts/run_db_suite.sh all`), local Postgres container, exit 0: 296 passed, 0 failed, 0 skipped, 1802 deselected in 54.55s; cleanup done. The 8 new tests in `test_orchestrator_run_cleanup_edges.py` all passed, first run, no test or product change needed. Step 2 approved by the owner 2026-11-25.
- **Step 3 (2026-11-25), DB-free part:** `env -u TEST_REDIS_URL uv run python scripts/check.py` (ruff, mypy, pytest) passed: 1798 passed, 4 skipped (redis), 300 deselected (db: 296 plus 4 new). Local Windows, DB-free. New: `tests/db/test_orchestrator_run_edge_decisions.py` (4 db tests). Row-creation check: `insert_sync_request` does not set `routing_version`, so the column is NULL until a completion writes it. Product change (D-C (b)) in `app/ai_platform/orchestrator.py` only: `run` keeps a small per-call `_RoutingDecided` holder, set when `route()` returns, and the run-level cleanup passes its value (`None` before routing) to `_end_failed`, whose parameter is now `str | None`; deliberate endings are unchanged. Tests: D-C: a fault before routing (a breaker subclass raising in `unavailable_models`) leaves `routing_version` NULL with the row `failed`/`execution_abandoned`, no provider call, no usage row; a fault after routing (provider raises) records `router-10.2-r1`. D-A (a): the caller is cancelled while a slow `abandon_call` runs; the cleanup finishes (usage `abandoned` at its estimate, `reserved` 0, request `failed`) and the caller sees the original `RuntimeError`, not `CancelledError`. D-D (a): a failing `abandon_call` writes no structlog or standard-log record (message absent, no error or warning record). D-B (a): an accepted risk (no bound on the cleanup; the connection layer's timeouts apply), to be recorded in the traceability Notes in step 4; no test. The red run of the D-C test before the change was not observed (written together with the change; DB tests need the owner's `/run-db-suite all`), so that test is not shown to fail on the old code.
- **Step 3 (2026-11-25), DB run:** `/run-db-suite all` (`bash scripts/run_db_suite.sh all`), local Postgres container, exit 0: 300 passed, 0 failed, 0 skipped, 1802 deselected in 134.79s; cleanup done. The 4 new tests in `test_orchestrator_run_edge_decisions.py` passed on the first run. Step 3 approved by the owner 2026-11-25 (result review under rule 18).
- Step 3 judgment calls (owner to confirm): the D-C test injects its fault through a `CircuitBreakerRegistry` subclass, because `run` reads `unavailable_models()` while building the routing input, before `route()`; a fault after routing but before an attempt keeps the version, which is the stricter reading of "no routing decision was made".
- Step 2 judgment calls (owner to confirm): the two failing-cleanup tests pin today's behavior, including two states that are not good outcomes but are the documented backstop case (usage `reserved` after a failed abandon; request `running` after a failed completion), so a later reaper task should change those assertions deliberately; the completion fault is injected by an engine-level `before_cursor_execute` hook that matches `UPDATE ai_requests` (only `request_repository.complete_request` issues it), because the orchestrator and the coordinator share one session factory; the expected settled costs rely on the synthetic prices (1 micro-USD per input unit, 0.6 per output unit) and on a failed provider call settling at its reported units; the row probe stringifies `SELECT *` rows, so the probe self-check covers the log sources only, not a planted database value.

## Review and approval
Plan approved by the owner 2026-11-25 ("approve T-024 as Ready, use defaults for D-A to D-D"). Result review is required before the next task if D-A, D-B or D-C changes product code, because that touches cancellation, accounting and stored-row behavior.
