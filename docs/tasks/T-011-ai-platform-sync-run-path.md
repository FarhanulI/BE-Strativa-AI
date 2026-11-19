# T-011: AI Platform synchronous `run` path (fake provider)

- **Module and phase:** ai_platform, Phase 2 (sub-task of T-008, part (b))
- **State:** Proposed
- **Requirement IDs:** (all exist in the spec and the traceability matrix; coverage is limited to the `run` path unless stated)
  - Invariants: INV-4 (`run` path only), INV-6, INV-7, INV-8, INV-9, INV-23, INV-26.
  - Acceptance criteria: AC-9 (`run` part only), AC-15, AC-16 (`run` part; the `execute_request` part is deferred), AC-17, AC-18, AC-19, AC-22, AC-23, AC-24, AC-25, AC-26, AC-27, AC-29 (`run` part), AC-38 (`run`, repair and fallback calls only), AC-51 (`run` with a user and a `for_worker` context; the `submit` clause is deferred).
  - Decisions applied: D-7, D-22, D-33 and the rest of section 20.1 as cited by the spec sections below.
- **Specification references:** [AI Platform spec](../specs/ai-platform/spec.md) sections 4.5 (sync request lifecycle), 5.2 (orchestrator, transaction ownership), 10.2 and 10.3 (router, fallback, failure behavior), 11 (strict output), 12.1 to 12.3 (usage, cost, budgets), 16 and 17; [traceability.md](../traceability.md); [decisions.md](../decisions.md) (SDD-D-7).
- **Dependencies:**
  - SDD-D-7 (development resumed). Accepted 2026-11-19.
  - Existing components, already in the tree and not changed by this task: Router (`router.py`), failure policy, output validation, circuit breaker, fake provider, `BudgetCoordinator`, request repository, usage repository, task and schema registries.
  - T-004 (D-32) and T-006 (revision 5 to 7 approval) stay open governance items. They do not block this task, because it needs no D-32 text and no revision 5 to 7 behavior beyond what is already implemented.
  - The local Postgres test container, run only through `/run-db-suite`. No Neon.

## Objective
Add the `AiOrchestrator.run` implementation that ties the existing, individually tested parts into one request flow: validate, create the `ai_requests` row, route, reserve, call a `ProviderClient`, validate output (with one repair call), fall back, settle and finish the row. Close the requirements the matrix lists as `Specified` or partial only because no orchestrator exists. Use the fake provider only.

## Scope
- `AiOrchestrator` class with `run` only, built with an `async_sessionmaker`, the config, catalog, clock, breaker, `BudgetCoordinator`, repositories and a `ProviderClient` (spec 5.2).
- Validation before routing, with nothing written: unknown or unready task, disallowed scope, the user-path restriction (D-7), unsupported modality (spec 4.5).
- Sync lifecycle (spec 4.5): row inserted in its own transaction, `running`, then `succeeded` or `failed` with `error_code` and `completed_at`; refused or unroutable calls end the row `failed` with no usage row and no reservation; budget refusal goes through `refuse_for_call` (D-33) before `AiBudgetExceeded`.
- Per attempt: reserve (own transaction) → provider call with no open transaction → settle (own transaction); one usage row per attempt; `call_kind` `initial` or `repair`; `route_rank`.
- Fallback, billing-mode constraint, repair-once, attempt cap, error mapping from the failure policy.
- `persist_result` handling, `AiTaskResult` and `AiUsageSummary` construction (no provider or model name, opaque `routing_id`).
- Explicit API key passing from config to the provider call (D-22), using the fake provider's recorded argument.
- Export through `app/ai_platform/__init__.py` as the spec's section 5 requires for the added name.

## Non-goals
- The LiteLLM adapter and any real provider call (AC-54 to AC-57, INV-1 stays `Specified`).
- `submit`, `get_status`, `get_output`, `execute_request`, leases, heartbeats, the reaper, purge, reconcile jobs and the cron CLI (AC-39 to AC-50, INV-16, INV-17, INV-25, INV-28).
- `embed_texts` (AC-8 embedding part, INV-12).
- Untrusted-context assembly and AC-28 (INV-24), unless it already exists in `messages.py`; if the `run` path needs a change there, stop and raise it as a scope question.
- HTTP endpoints, UI, catalog data, prices (AC-60), any change to the specification or to approved decisions.
- Any change to migrations or to the schema. If one is needed, stop and write a change proposal.
- Neon runs. Real-provider spend.

## Implementation expectations
Planned in steps; each step is a commit that cites `T-011` and the requirement IDs:

1. **Orchestrator skeleton and pre-routing validation.** New `app/ai_platform/orchestrator.py`. Covers INV-23, INV-26, AC-26, AC-51. Unit tests with the fake provider and no DB.
2. **Request lifecycle and refusal paths.** Row creation, `failed` endings for `no_route`, `input_too_large`, `provider_not_configured`, `budget_exceeded` (spec 4.5). DB tests.
3. **Single successful call.** Reserve, call, validate, settle, finish; `AiTaskResult`, usage summary, `persist_result`. Covers AC-22, AC-29 (`run` part), INV-7, INV-8. DB tests.
4. **Repair, fallback and attempt cap.** Covers AC-15, AC-16 (`run` part), AC-17, AC-18, AC-19, AC-23, AC-24, AC-25, AC-27, INV-9. Fake provider scripted per spec table 10.3. DB tests for ledger rows and `route_rank`.
5. **Lock-free provider call.** Spy `ProviderClient` with a separate connection (`FOR UPDATE NOWAIT` on the budget and request rows, no `idle in transaction`). Covers AC-38 and INV-6 for `run`, repair and fallback.
6. **Router-before-provider proof for `run`.** Spy router and spy provider. Covers AC-9 (`run` part) and INV-4 (`run` part).
7. **Traceability and docs.** Update the affected rows (see below) and the module documentation if the public contract wording changes. No spec edits.

Boundaries: only `app/ai_platform/` is touched in product code. Persistence stays inside the module. Logs, events and errors carry no prompts, completions or user content. No event payload key contains the word "token".

## Required tests
- Unit (no DB): pre-routing validation, D-7 restriction, task-not-ready, repair and fallback sequencing, attempt cap with an always-invalid provider, billing-mode constraint, error mapping per spec table 10.3, explicit key passing, architecture tests still pass (litellm boundary, provider identifiers, clock).
- Database (marker `db`, local Postgres container only): lifecycle rows, ledger rows per attempt, `route_rank`, refusal endings with no usage row, reconciliation after a mixed run (supports AC-36 evidence, not claimed for it), the AC-38 spy test.
- Every test names the requirement IDs it covers. Synthetic text only.

## Verification requirements
- Database tests run only through `/run-db-suite` on the local Postgres container (`TEST_DB_MODE=local`, `APP_ENV=test`). Unit tests run with the repository's pytest configuration (`pyproject.toml`); no new commands or scripts are created.
- Evidence recorded per requirement: date, command or skill, environment, counts, in the task and in [traceability.md](../traceability.md).
- Local PostgreSQL verifies no requirement that names Neon. No requirement in this task names Neon.
- No requirement is marked `Verified` without that evidence. Requirements whose coverage is only the `run` part stay partial and say so.

## Acceptance criteria
- Each listed requirement ID has at least one mapped, executed test for its `run` part, with dated evidence, or stays `Implemented` / `Specified` / `Gap` with the remaining part named.
- `run` provides no path to a provider that skips the Router; no provider call occurs inside a database transaction; invalid output is never returned or stored.
- Public types expose no provider or model name; no prompt, completion or user content appears in logs, events or errors.
- The unit suite, the architecture tests and the DB suite pass in the recorded runs, and any failure is reported with its output.
- Traceability updated: INV-6, INV-7, INV-8, INV-9, INV-23, INV-26, AC-15 to AC-19, AC-22 to AC-27, AC-38, AC-51 and the `run` parts of INV-4, AC-9, AC-16, AC-29. AC-36, AC-58, INV-13 and INV-32 stay as they are (supporting runs may be noted).

## Evidence
None recorded.

## Review and approval
Not requested.

## Risks and architectural considerations
- Transaction ownership deviates deliberately from "caller owns the session" (spec 5.2). The orchestrator owns short transactions; a provider call must never run inside one.
- Lock order request, usage record, budget row (INV-32) applies to every multi-row transaction written here.
- `run` must not become the shape that `execute_request` copies without the fencing (INV-28). Keep the attempt loop reusable but do not add lease code.
- AC-16 and AC-38 each have clauses for `execute_request`; they remain partial after this task, so the matrix must not show them `Verified` on `run` evidence alone.
- The failure-policy, router and coordinator are reused unchanged. If a defect in them is found, stop and report instead of patching under this task.
