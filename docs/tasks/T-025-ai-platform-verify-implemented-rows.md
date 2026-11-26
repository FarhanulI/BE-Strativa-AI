# T-025: Verify the AI Platform rows that are Implemented (sub-task T-008-F)

- **Module and phase:** ai_platform, Phase 2 (sub-task F of [T-008](T-008-ai-platform-remaining-verification.md))
- **State:** Accepted (2026-11-26; steps 1 to 5 done, 16 rows Verified). Was Ready (approved by the owner 2026-11-25, decisions D-A to D-C settled to the defaults)
- **Requirement IDs:** all exist in the spec and the matrix; status read from [traceability.md](../traceability.md) on 2026-11-25.
  - **Group 1, complete rows, verify by executing existing tests (no code change):** INV-5, INV-21; AC-5, AC-6, AC-10, AC-12, AC-13, AC-14, AC-20, AC-30, AC-32, AC-34, AC-64, AC-65.
  - **Group 2, rows with a test-only gap on code that exists:** INV-2 and AC-3 (no test reflects the `run` signature for a provider, model or override field), INV-13 and AC-36 (the mixed workload is driven through the repository, not `run`), AC-35 (no in-flight-settles check; the HTTP 429 clause needs an endpoint and stays open), AC-21 (a Router-time modality refusal ending a `run` row `failed` is not asserted), AC-51 (the `from_workspace` success path is covered by unit validation only).
  - **Group 3, recorded only, stay `Implemented`:** every other `Implemented` row. Each has an open clause that needs code that does not exist (`submit`, `execute_request`, `embed_texts`, the adapter, the periodic handlers, the endpoints). AC-60 is also in this group (see decision D-B). Examples: INV-4, INV-6 to INV-9, INV-12, INV-14, INV-17 to INV-20, INV-22 to INV-24, INV-26, INV-29 to INV-32, AC-2, AC-4, AC-7 to AC-9, AC-11, AC-16, AC-28, AC-31, AC-33, AC-37, AC-38, AC-45, AC-46, AC-52, AC-53, AC-58, AC-61, AC-62.
- **Specification references:** [AI Platform spec](../specs/ai-platform/spec.md) sections 16, 17.1 to 17.5; [T-008](T-008-ai-platform-remaining-verification.md); [T-023](T-023-ai-platform-run-followups.md) decision D-F (precedent: a row with an open clause stays `Implemented`); [traceability.md](../traceability.md); [evidence template](../reports/_template-evidence.md) (T-014).
- **Dependencies:**
  - T-008 Ready (2026-11-25). T-011, T-022, T-023, T-024 Accepted; they supply the code under test.
  - Local Postgres container and Redis, run only through `/run-db-suite`. The owner runs it; the agent does not start Docker. No Neon.
  - Does not depend on T-004, T-005, or on the other T-008 sub-tasks. Sub-tasks B to E later reopen the Group 3 rows; this task does not wait for them.

## Objective
Move the Group 1 rows to `Verified` with dated execution evidence, add the missing tests for the Group 2 gaps and verify those rows only where every clause is then covered, and record for every Group 3 row the exact open clause that keeps it `Implemented`. No product code changes.

## Scope
1. **Classification record (read-only).** For each `Implemented` AI Platform row, confirm from the matrix and the tests which group it is in, and write the table in the Evidence section. Correct any row whose note is stale (for example AC-62 still says `submit` arrives with T-011).
2. **Group 2 tests.** Add the five test-only items above. Each test cites its requirement ID. A test that would need product code is not added; the row moves to Group 3 with the reason.
3. **Execution.** DB-free gate (`scripts/check.py`), then the owner runs `/run-db-suite`. Record command, exit code, counts, environment and date per the template.
4. **Traceability.** Update Test, Evidence and Status cells. A row becomes `Verified` only with a linked evidence record and a `PASS` from the fresh-context audit for that criterion. Group 3 notes keep the open clause.
5. **Audit.** A fresh-context `spec-auditor` reports PASS, PARTIAL or FAIL per criterion. The implementing session does not audit.

**Owner decisions (defaults proposed):**
- **D-A. Rows with an open clause on absent code.** (a) Stay `Implemented`, per T-023 D-F. (b) Verify the `run` part only. Default: (a), because a `Verified` row would overstate coverage of the criterion.
- **D-B. AC-60.** Its `task_min_input_units` values (except `EMBED_TEXT`) and `latency_p50_ms` are owner-review proposals, not documented facts. (a) Leave `Implemented` until the owner confirms the values. (b) The owner confirms them in this task. Default: (a).
- **D-C. Group 2 size.** (a) All five items. (b) Only INV-2/AC-3 and INV-13/AC-36. Default: (a).

## Non-goals
Any change to `app/`, migrations, the spec, the catalog or configuration. Building `submit`, `execute_request`, `embed_texts`, the adapter, handlers or endpoints (sub-tasks B to D). Real-provider calls (sub-task E). Neon. Resolving D-32 (T-004). Marking a row `Verified` for a criterion with an open clause.

## Implementation expectations
Tests only, under `tests/unit/ai_platform/` and `tests/db/`, reusing existing helpers (`build_orchestrator`, `FakeAiProvider`, the synthetic catalog). Tests use synthetic text. No prompts, completions or `token` keys in assertions' failure messages. No change under `.env*`. Commits cite T-025 and the requirement IDs.

## Required tests
Existing tests for Group 1 (listed per row in the matrix). New tests for Group 2:
- INV-2/AC-3: reflect `AiOrchestrator.run` parameters; none names a provider, model or override.
- INV-13/AC-36: a `run` workload with repairs, fallbacks, a failed call and a refusal, then the AC-36 query on the budget row.
- AC-35 (in-flight part): a settlement in flight at refusal time is not lost; `spent + reserved <= limit` throughout.
- AC-21: a Router-time modality refusal ends the `run` row `failed` with no usage row and no call.
- AC-51: the `from_workspace` interactive success path through `run` with a real `users` row, or a recorded reason it stays unit-only.

## Verification requirements
Environment: local PostgreSQL (`TEST_DB_MODE=local`, `APP_ENV=test`) and Redis through `/run-db-suite`; DB-free gate through `scripts/check.py`. Each command is recorded with exit code, counts, environment and date in `docs/reports/<date>-T-025-...md`, linked from the Evidence cell. Anything not run is `NOT RUN` with the reason. Local PostgreSQL verifies no requirement that names Neon (none here does). At task end the agent asks the owner to run `/run-db-suite all`.

## Acceptance criteria
- Every Group 1 row is `Verified` with a linked, dated evidence record and a `PASS` audit line, or stays `Implemented` with the reason recorded.
- Each Group 2 item has a passing test, and its row is `Verified` only if no clause remains open.
- Every Group 3 row names its open clause and the code it waits for.
- `app/` and migrations are unchanged (`git diff --stat` recorded).
- DB-free gate green; DB suite count recorded and no regression from 305 passed (T-022, 2026-11-25).
- `spec-auditor` run in a fresh context; findings applied or recorded.

## Evidence
No test or command was executed yet; step 1 is a read-only classification. Dated 2026-11-25.

**Step 1: classification record (read-only, 2026-11-25).** Method: read the spec text of each criterion, the matrix row and note, and checked by script that every test reference in the Test column of the 21 Group 1 and Group 2 rows exists (file and function: 0 missing). Tests were not executed.

Group 1, confirmed (every clause of the spec text is mapped to an existing test; the Test column covers it):

| Row | Check against the spec text |
| --- | --- |
| AC-5, AC-6, AC-10, AC-12, AC-13, AC-14, INV-5, INV-21 | All clauses mapped (including the DB part of AC-10 and `publish` for each event in AC-6) |
| AC-20 | Opens on the fifth failure, closes through a half-open probe, `FakeClock` only (a test asserts the system clock is never read) |
| AC-30 | 30 callers against K=7, exactly K succeed, `reserved + spent <= limit` sampled |
| AC-32 | Workspace 25,000,000 and system 100,000,000 defaults; new UTC month at zero with `FakeClock` across 31 December to 1 January |
| AC-34 | No publish on reservations; one event and one audit at the crossing settlement; concurrent crossings publish once; calls continue |
| AC-64 | Clauses (a) to (h) each map to a named test |
| AC-65 | Clauses (a) to (d) each map to a named test (tests 10 to 13). Caveats kept in the matrix note: no probe-specific cancellation test (not required by the AC); test 13 was not run against the unguarded release (step 2 may add a check) |

Group 2, corrected. The gap is confirmed in each case, but closing it does not always make the row `Verified`, because the spec text of some criteria also names code that does not exist:

| Row | Test gap confirmed | After the new test, can the row be `Verified`? |
| --- | --- | --- |
| AC-36 | Yes: the only workload test goes through the repository | Yes, if the `run`-driven workload passes. INV-13 still maps to AC-46 (no handler), so INV-13 stays `Implemented` |
| AC-21 | Router-time modality refusal on `run` is not asserted in `tests/db` | Probably yes (its spec text has no clause on absent code); the first clause is already unit tested |
| INV-2, AC-3 | Yes: no test reflects `AiOrchestrator.run`; no idempotency-parameter check | No. AC-3 also names `EmbeddingService.embed_texts` and `submit`, which do not exist. The `run` test is still added |
| AC-35 | Yes: no in-flight-settles check; no HTTP 429 or `GET /budget` test | No. The 429 and `GET /budget` clauses need an endpoint. The in-flight test is still added |
| AC-51, INV-26 | Yes: no DB-level `from_workspace` test (a user context needs a real `users` row) | No. AC-51 also says the task succeeds via `submit`, which does not exist |

Result: expected `Verified` after execution and audit: 14 Group 1 rows (INV-5, INV-21, AC-5, AC-6, AC-10, AC-12, AC-13, AC-14, AC-20, AC-30, AC-32, AC-34, AC-64, AC-65), plus AC-36 and AC-21 if their new tests pass and the audit agrees. Total at most 16. The other Group 2 rows stay `Implemented` (D-A (a)). The five Group 2 tests in scope are unchanged (D-C (a)).

Group 3: each row's open clause is already named in its matrix note (code that does not exist: `submit`, `execute_request`, `embed_texts`, the adapter, `reconcile_budgets` and the other handlers, endpoints, `build_ai_platform`). No Group 3 note was found without a named open clause. AC-60 stays per D-B (a).

Stale notes corrected in [traceability.md](../traceability.md) (docs only, no status change):
- AC-64 and AC-65: "audit and owner review pending" now says T-022 was accepted 2026-11-25 after its own `spec-auditor` run, with no evidence record linked yet, and points to this task.
- AC-62: "`submit` does not exist until T-011" now says T-011 built only `run` and `submit` belongs to T-008-C.

Files changed in step 1: `docs/traceability.md` (the two notes above) and this file. `app/`, `tests/` and migrations unchanged.

**Step 2: Group 2 tests written (2026-11-25).** Tests and one test-helper parameter only; `app/` and migrations unchanged.

| Row | Test | Kind |
| --- | --- | --- |
| INV-2, AC-3 (`run` part) | `tests/unit/ai_platform/test_orchestrator_signature.py` (3 tests: parameters are exactly `ctx` and `request`; no provider, model, override or idempotency name; typed `AiTaskRequest` and `AiTaskResult`) | DB-free |
| AC-36, INV-13 | `tests/db/test_orchestrator_run_mixed_workload.py::test_a_mixed_run_workload_reconciles_with_the_usage_ledger` (success, repair, fallback, all-invalid, bad request, budget refusal through `run`; `reconciliation_query` empty, `reserved = 0`, `spent` equals the usage sum and the request-cost sum) | DB |
| AC-35 (in-flight clause) | `tests/db/test_orchestrator_run_in_flight_refusal.py::test_a_refusal_while_a_call_is_in_flight_leaves_that_call_to_settle` (second `run` refused while the first holds its reservation; the first settles; one exhausted event with `spent` below the limit; no usage row for the refused call) | DB |
| AC-21 | `tests/db/test_orchestrator_run_modality_and_user_path.py::test_a_modality_no_model_accepts_ends_the_row_failed_with_no_route` (task allows images, catalog is text-only: `AiModalityNotSupported`, row `failed` with `no_route`, no usage, no reservation, no call) | DB |
| AC-51 (`run` part), INV-26 | same file, `::test_the_user_path_runs_the_interactive_task_and_refuses_the_others` (real `users` row; interactive task succeeds with the user recorded; the other task raises `ValidationFailed` with the fixed detail and leaves no row, usage or reservation) | DB |

Helper change: `tests/helpers/orchestrator_db.py::build_orchestrator` gained an optional `tasks` argument (default `None`, no behavior change for existing tests).

Commands executed:
- `uv run --python 3.12 --no-sync python scripts/check.py` (DB-free gate, local, 2026-11-25): exit 0, 1805 passed, 309 deselected. First run failed only on E501 line length in the new files; fixed with `ruff format` and a manual wrap, then re-run green.
- DB suite: run at step 3, see below.

Expectation recorded before running: AC-36 and AC-21 can move to `Verified` only if their tests pass and the audit agrees. AC-3, AC-35, AC-51, INV-2, INV-13 and INV-26 stay `Implemented` (open clauses on `submit`, `embed_texts` and the endpoint), as decided in step 1.

**Step 3: execution evidence recorded (2026-11-25).** Record: [2026-11-25-T-025-ai-platform-implemented-rows.md](../reports/2026-11-25-T-025-ai-platform-implemented-rows.md).
- `uv run --python 3.12 --no-sync python scripts/check.py`: exit 0, 1805 passed, 0 failed, 309 deselected.
- `bash scripts/run_db_suite.sh all` (owner's `/run-db-suite all`, local PostgreSQL and Redis, `TEST_DB_MODE=local`, `APP_ENV=test`): 309 passed, 0 failed, 1805 deselected, 109.09 s, `cleanup done`. Exit code not reported by the session output. 305 before plus the 4 new DB tests: no regression. All four new DB tests passed.
- Neon, real provider: `NOT RUN` (out of scope).
- Proposed statuses (pending audit): `Verified` for INV-5, INV-21, AC-5, AC-6, AC-10, AC-12, AC-13, AC-14, AC-20, AC-21, AC-30, AC-32, AC-34, AC-36, AC-64, AC-65 (16 rows). INV-2, INV-13, INV-26, AC-3, AC-35 and AC-51 stay `Implemented` (open clauses on absent code). No traceability status changed yet (step 4).

**Step 4: traceability updated (2026-11-25).** [traceability.md](../traceability.md) only; `app/` and migrations unchanged.
- Evidence cell links to the step 3 record for all 22 rows touched (the 16 proposed `Verified` rows plus INV-2, INV-13, INV-26, AC-3, AC-35, AC-51). DB-free rows use the `local-db-free` label, DB rows `local-postgres`.
- Test cell: the new tests added to INV-2, AC-3, AC-21, AC-35, AC-36, AC-51, INV-13 and INV-26.
- Notes: stale "no test" and "no evidence record linked yet" sentences removed for AC-21, AC-35, AC-36, AC-51, INV-2, AC-3, INV-13, AC-64 and AC-65; open clauses on absent code kept.
- Status: no row set to `Verified`. Rule 20 needs the fresh-context `spec-auditor` first, so the 16 rows stay `Implemented` with a note saying `Verified` waits for step 5 and the owner's milestone review. After a PASS, step 5 flips them.

**Step 5: `spec-auditor` (fresh context, 2026-11-26).** Result: 9 of 16 proposed rows `Verified`; 7 held; the 6 others confirmed `Implemented`.
- `Verified` (audit PASS): INV-5, AC-5, AC-6, AC-12, AC-13 (after mapping `test_step_not_configured_alone`), AC-14, AC-20, AC-21, AC-64.
- Held at `Implemented`: INV-21, AC-10, AC-30, AC-32, AC-34, AC-36 (coverage PASS, but the DB suite exit code is not recorded, sdd.md section 10) and AC-65 (its D-35 sentence was unmapped; the two D-35 tests are now mapped; exit code also unrecorded).
- INV-2, INV-13, INV-26, AC-3, AC-35, AC-51 confirmed `Implemented`. For INV-2, INV-13 and INV-26 the reason is the section 17.7 mapping to AC-3, AC-46 and AC-51, not an open clause in the invariant; notes corrected.
- `git diff --stat -- app migrations`: empty. The DB-free count delta (1798 to 1805) is explained only in part; recorded in the evidence record.
- Open: the owner's DB suite run needs its exit code recorded (re-run `/run-db-suite all` and note the exit code), then the 7 held rows can be re-checked. Not done: a per-test report (`-rA`); AC-32 has no single default-config-to-row test (auditor note, not a blocker).

**Step 5 follow-up (2026-11-26).** `/run-db-suite all` re-run by the owner: exit 0, 309 passed, 0 failed, 1805 deselected, 240.09 s, `cleanup done` (command 3 in the record). INV-21, AC-10, AC-30, AC-32, AC-34, AC-36 and AC-65 flipped to `Verified`: 16 rows `Verified` in total. Open: owner review and acceptance. `Verified` rows still await the owner's milestone review.

## Review and approval
Result accepted by the owner 2026-11-26 ("approved, T-025 accepted"): 16 rows `Verified`, 6 stay `Implemented`.
Plan approved by the owner as `Ready` on 2026-11-25 ("approved, make T-025 Ready, use defaults"). Decisions settled to the defaults: D-A (a) rows with an open clause on absent code stay `Implemented`; D-B (a) AC-60 stays `Implemented` until the owner confirms the catalog values; D-C (a) all five Group 2 tests. Result review is milestone-level (tests and docs only, no migration, contract, security or AI target change).

Proposed commit message:

```
docs(T-025): prepare verification of Implemented AI Platform rows (T-008-F)

Add task T-025 for INV-2, INV-5, INV-13, INV-21, AC-3, AC-5, AC-6, AC-10,
AC-12 to AC-14, AC-20, AC-21, AC-30, AC-32, AC-34 to AC-36, AC-51, AC-64 and
AC-65, and record the rows that stay Implemented. Docs only. State Proposed.


```
