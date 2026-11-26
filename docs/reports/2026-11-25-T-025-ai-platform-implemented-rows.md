# Evidence record: T-025 AI Platform Implemented rows (T-008-F)

Template: [_template-evidence.md](_template-evidence.md). Rules: [sdd.md](../sdd.md) sections 6 and 10 to 11, [traceability.md](../traceability.md).

## Record

| Field | Value |
| --- | --- |
| Task | [T-025](../tasks/T-025-ai-platform-verify-implemented-rows.md) |
| Date of execution | 2026-11-25 |
| Environment | Local Windows, Python 3.12.14. DB-free gate: no database. Database suite: local container `strativa-test-db` (`TEST_DB_MODE=local`, `APP_ENV=test`) with local Redis, through `scripts/run_db_suite.sh`. Neon: not used |
| Commit | `45e8eaa` plus uncommitted changes (the five new T-025 test files, `tests/helpers/orchestrator_db.py`, `docs/traceability.md`, `docs/tasks/`) |
| Run by | DB-free gate: agent session. Database suite: `/run-db-suite all`, started by the owner, executed by the agent session |

## Commands

| # | Exact command | Exit code | Passed | Failed | Skipped | Errors |
| --- | --- | --- | --- | --- | --- | --- |
| 1 | `uv run --python 3.12 --no-sync python scripts/check.py` | 0 | 1805 | 0 | not reported | 0 |
| 2 | `bash scripts/run_db_suite.sh all` (2026-11-25, first run) | not reported (the script printed `cleanup done`; no failure or error was printed) | 309 | 0 | not reported | 0 |
| 3 | `bash scripts/run_db_suite.sh all` (2026-11-26, owner's `/run-db-suite all`, re-run to capture the exit code; same tree) | 0 | 309 | 0 | not reported | 0 |

## Requirements covered

The runs are aggregate: neither command printed a per-test list in the session, so each mapped test is one that the run collected and that produced no failure. Test names are the ones in the Test column of the traceability row (checked to exist in step 1: 0 missing).

| Requirement ID | Mapped tests that ran (file::name) | Clause covered | Result | Proposed status |
| --- | --- | --- | --- | --- |
| INV-5 | `tests/unit/ai_platform/test_router.py` (`test_repeated_calls_and_shuffled_catalogs_are_byte_identical`, `test_snapshot_json_is_canonical`, `test_router_has_no_io_calls`) | whole requirement (pure function; the `AiRouter` class does not exist and the spec does not require one) | passed | Verified (audit PASS) |
| INV-21 | `tests/unit/ai_platform/test_ai_platform_schema_metadata.py::test_ai_tables_are_registered_and_tenant_scoped`; `tests/db/test_ai_platform_schema.py` (three `*_check_constraints_reject_bad_rows` tests) | whole requirement | passed | Verified (audit PASS, exit code recorded by command 3) |
| AC-5 | `tests/unit/ai_platform/test_ai_platform_registries_types.py` (5 tests) | whole requirement | passed | Verified (audit PASS) |
| AC-6 | `tests/unit/ai_platform/test_ai_platform_events.py` (4 tests) | whole requirement | passed | Verified (audit PASS) |
| AC-10 | `test_ai_platform_schema_metadata.py::test_ai_tables_are_registered_and_tenant_scoped`; `tests/db/test_ai_platform_schema.py` (three constraint tests) | whole requirement, including the DB part | passed | Verified (audit PASS, exit code recorded by command 3) |
| AC-12 | `tests/unit/architecture/test_ai_call_context_construction.py` (2 tests); `tests/unit/ai_platform/test_ai_call_context.py` (2 tests) | whole requirement | passed | Verified (audit PASS) |
| AC-13 | `tests/unit/ai_platform/test_router.py` (`test_each_step_alone_removes_the_right_model`, `test_every_reason_code_is_covered_in_step_order`, `test_quality_floor_below_the_task_class_has_no_effect`) | whole requirement | passed | Verified (audit PASS) |
| AC-14 | `tests/unit/ai_platform/test_router.py` (4 ranking and determinism tests) | whole requirement | passed | Verified (audit PASS) |
| AC-20 | `tests/unit/ai_platform/test_circuit_breaker.py` (5 tests, `FakeClock` only) | whole requirement | passed | Verified (audit PASS) |
| AC-30 | `tests/db/test_budget_coordinator.py::test_concurrent_reservations_admit_exactly_k`; `tests/db/test_budget_repository.py::test_concurrent_reservations_admit_exactly_k` | whole requirement | passed | Verified (audit PASS, exit code recorded by command 3) |
| AC-32 | `tests/db/test_budget_repository.py` (`test_ensure_budget_row_creates_row_with_limit_and_zero_counters`, `test_new_utc_month_starts_a_new_row_at_zero`); `test_ai_platform_config_errors.py::test_defaults` | whole requirement | passed | Verified (audit PASS, exit code recorded by command 3) |
| AC-34 | `tests/db/test_budget_coordinator.py` (2 tests); `tests/db/test_budget_repository.py` (2 tests) | whole requirement | passed | Verified (audit PASS, exit code recorded by command 3) |
| AC-64 | `tests/unit/ai_platform/test_circuit_breaker.py`, clauses (a) to (h), 14 named tests | whole requirement | passed | Verified (audit PASS) |
| AC-65 | `tests/db/test_orchestrator_run_probe_release.py` (4 named tests, one with 2 cases) | clauses (a) to (d). Caveat kept: no probe-specific cancellation test (not required by the AC) | passed | Verified (audit PASS, exit code recorded by command 3) |
| AC-36 | `tests/db/test_orchestrator_run_mixed_workload.py::test_a_mixed_run_workload_reconciles_with_the_usage_ledger` (new); `tests/db/test_budget_repository.py::test_mixed_workload_reconciles` | whole requirement, through `run` and through the repository | passed | Verified (audit PASS, exit code recorded by command 3) |
| AC-21 | `tests/unit/ai_platform/test_router.py` (2 tests); `tests/unit/ai_platform/test_orchestrator_validation.py::test_image_part_on_a_text_only_task_is_a_modality_error`; `tests/db/test_orchestrator_run_modality_and_user_path.py::test_a_modality_no_model_accepts_ends_the_row_failed_with_no_route` (new) | whole requirement | passed | Verified (audit PASS) |
| INV-2, AC-3 (`run` part) | `tests/unit/ai_platform/test_orchestrator_signature.py` (3 new tests) | `run` signature only. `submit` and `EmbeddingService.embed_texts` do not exist | passed | Implemented (open clause on absent code) |
| AC-35 | `tests/db/test_orchestrator_run_in_flight_refusal.py::test_a_refusal_while_a_call_is_in_flight_leaves_that_call_to_settle` (new) | in-flight clause. HTTP 429 and `GET /budget` need an endpoint that does not exist | passed | Implemented (open clause on absent code) |
| AC-51, INV-26 (`run` part) | `tests/db/test_orchestrator_run_modality_and_user_path.py::test_the_user_path_runs_the_interactive_task_and_refuses_the_others` (new) | `run` part only. `submit` does not exist | passed | Implemented (open clause on absent code) |
| INV-13 | same workload test as AC-36 | the reconciliation invariant through `run`. INV-13 also maps to AC-46 (no handler) | passed | Implemented (maps to AC-46) |

"Verified, pending audit" is a proposal. No row is `Verified` until the fresh-context `spec-auditor` reports PASS for it and the traceability Evidence cell links to this record (T-025 steps 4 and 5).

## Failures

None. Command 1: 0 failed. Command 2: 0 failed.

## Not run

| Item | Reason |
| --- | --- |
| Neon | `NOT RUN`: needs a separate explicit authorization; no row in this task names Neon |
| Real-provider tests | `NOT RUN`: out of scope (T-008-E); no provider spend |
| Real-Redis rows other than those the suite already covers | `NOT RUN` here: not part of T-025 |
| Clauses on code that does not exist (`submit`, `embed_texts`, endpoints, adapter, periodic handlers) | `NOT RUN`: nothing to execute; the rows stay `Implemented` (T-025 D-A (a)) |
| Per-test result listing | `NOT RUN`: neither command was asked to print one (`-rA` or a report file); only aggregate counts exist |
| Exit code of command 2 | not reported by the session output; command 3 records exit 0 |

## Notes

- Command 3 (2026-11-26): `collected 2114 items / 1805 deselected / 309 selected`, `309 passed, 1805 deselected in 240.09s`, `cleanup done`, exit 0 printed as `EXIT_CODE=0`. Files and counts match command 2. Skipped: the summary line prints none, so 0 skipped is implied but the field stays `not reported`.

- `git diff --stat -- app migrations` (2026-11-26): empty, no change to `app/` or migrations.
- The DB-free count rose from 1798 (last recorded in T-022 and T-024 step 2) to 1805; T-025 added 3 DB-free tests, the other 4 are not attributed (T-024 step 4 added tests after the 1798 run). Not reconciled further.
- Added mappings after the audit: AC-13 `test_step_not_configured_alone`; AC-20 four boundary tests; AC-64 (f) `test_a_non_probe_success_clears_the_history_only_while_closed`; AC-65 two D-35 tests in `test_orchestrator_run_billing_breaker.py`. These were collected in the same runs.
- Command 1: 309 deselected (the DB-marked tests). Command 2: 1805 deselected (the DB-free tests), 109.09 s. 305 passed before the four new DB tests (T-022, 2026-11-25); 309 now, so no regression.
- The DB-free run of command 1 was made before the DB suite; no `app/` or migration file changed between them (`app/` and migrations are unchanged by T-025).
- First run of command 1 failed only on ruff E501 in the new test files; fixed, re-run green. The figure above is the green run.
- Synthetic text only; fake provider; no secrets read or printed.

## Review

| Step | State |
| --- | --- |
| Independent audit (sdd.md section 11) | `spec-auditor`, fresh context, 2026-11-26: PASS for INV-5, AC-5, AC-6, AC-12, AC-14, AC-20, AC-21, AC-64 and (after mapping `test_step_not_configured_alone`) AC-13. Held then flipped to Verified after command 3 (exit 0): INV-21, AC-10, AC-30, AC-32, AC-34, AC-36, AC-65 (D-35 clause mapped). INV-2, INV-13, INV-26, AC-3, AC-35, AC-51 confirmed `Implemented` |
| Owner review | Not requested |
