# T-022: Circuit breaker probe ownership and lease (D-37)

- **Module and phase:** ai_platform, Phase 2
- **State:** Ready (owner readiness decision 2026-11-24: "T-022 is Ready, start checkpoint 2"). Checkpoint 2 approved 2026-11-24. Checkpoint 3 approved 2026-11-25. Checkpoint 4 approved 2026-11-25; DB suite 305 passed.
- **Requirement IDs:**
  - New: AC-64 and AC-65 (spec 17.2, revision 11). Decision D-37 (spec 20.1, revision 11).
  - Preserved without change: AC-20 and D-35. This task does not change their requirements or status.
  - Supporting: INV-22 (injected `Clock`; breaker timing), INV-7 and INV-14 (the ledger rules the probe cleanup must not disturb), INV-18 (no "token" in log or event field names; the handle field is `claim_id`).
- **Specification references:** [AI Platform spec](../specs/ai-platform/spec.md) 10.3 (failure table, D-35 breaker denial), 10.4 (circuit breaker, ownership, lease, internal failures), 17.2 (AC-20, AC-64, AC-65), D-37; [CP-4](../specs/ai-platform/change-proposals/CP-4-circuit-breaker-probe-ownership.md).
- **Dependencies:**
  - CP-4 approved and applied (done, 2026-11-24).
  - Owner readiness review: done 2026-11-24.
  - None on [T-011](T-011-ai-platform-sync-run-path.md). T-011 is unchanged in scope and record, and its step 5 is reviewed independently.

## Objective

Make the circuit breaker's half-open probe ownership-aware, replace the time-only probe lease with a derived lease, and prove that the orchestrator releases a claimed probe on every path that records no provider outcome. This closes findings H1, H2 and M1 of the Step 5 read-only verification.

## Scope

- [app/ai_platform/circuit_breaker.py](../../app/ai_platform/circuit_breaker.py): `AttemptHandle(key, claim_id, probe)`; a `probe_claim` per entry and a claim-id counter per registry; `begin_attempt` returns `AttemptHandle | None`; `record_success(handle)`, `record_failure(handle, kind)` and `abandon_attempt(handle)` act on the probe only for its current owner; the lease check in `begin_attempt`.
- [app/ai_platform/config.py](../../app/ai_platform/config.py): a derived property `probe_lease_seconds = longest_deadline_seconds + 30`. The 30 s margin is an internal constant. No new field and no environment variable.
- [app/ai_platform/orchestrator.py](../../app/ai_platform/orchestrator.py): pass the handle through `_guarded_attempt` and `_attempt`; on `BaseException` try `abandon_attempt(handle)` inside its own `try/except Exception`, then re-raise the original exception. Provider outcome recording stays before `settle_call`.
- Tests listed below, and the traceability and task evidence updates.

## Non-goals

- Cross-process or Redis breaker state.
- The failure classification, billing-mode rules, Router, usage and budget code.
- A hard `asyncio` timeout around the provider call (see "Follow-up considerations").
- Any `.env`, `.env.example` or `.env.local` change, or `scripts/sync_env_local.py`.
- Moving provider outcome recording after the usage settlement.
- Changing T-011, D-35 or AC-20.

## Implementation expectations

- A handle is the current owner iff `handle.probe` and the entry's `probe_claim` equals `handle.claim_id`. Every owner path clears `probe_claim`.
- A non-probe outcome never changes an open or half-open state. A non-probe success clears the failure history only while the breaker is closed. A counted non-probe failure adds to the history only while the breaker is closed.
- An authentication failure marks the model unavailable for the process whichever handle reports it, counts nothing, and clears `probe_claim` only when the reporting handle is the owner.
- A neutral outcome from the owner releases the probe without closing or re-opening, as today.
- Recording or releasing twice, or recording then releasing, is a no-op the second time.
- An internal exception (budget refusal, unexpected provider exception, settlement failure, cancellation) is not recorded as a provider failure. The probe is released, and the original exception propagates unchanged even if the release fails.
- Logged transition fields stay provider, model, state and failure count. No field name contains "token".
- Supersession note: the ownership-aware handle API supersedes the earlier boolean `begin_attempt` described in T-011's plan table and step 5 evidence. T-011's historical text stays as written. This note is the cross-reference.

## Required tests

Registry (unit, DB-free, `FakeClock` only), for AC-64. Test 1 is written first and shown failing against the current implementation, with the command, exit code and counts recorded before the fix.

1. An old handle cannot abandon a newer probe (the H1 interleaving: A releases, E claims, A abandons, F is denied).
2. An old handle cannot record success or failure against a newer probe.
3. An unsuperseded probe completes after the lease expires: a late success closes, a late failure re-opens for a full open period.
4. A superseded probe's completion has no effect.
5. Concurrent half-open acquisition gives exactly one current owner (the existing 32-thread test, adapted).
6. Repeated cleanup is idempotent (`record_success` then `abandon`; `abandon` twice).
7. Non-probe outcomes cannot change an open or half-open state.
8. Authentication failure behavior is unchanged, and it leaves another handle's probe claim untouched.
9. `probe_lease_seconds` equals the longest deadline plus 30 and does not change with `breaker_open_seconds`.

Orchestrator (DB, local Postgres, through the owner-run `/run-db-suite`), for AC-65:

10. A budget refusal releases the claimed probe and is not a provider failure.
11. An unexpected provider exception releases the probe and propagates unchanged.
12. A settlement failure after the outcome was recorded leaves the breaker as that outcome made it.
13. A failure inside `abandon_attempt` does not replace the original exception.

Registry semantics are not repeated in the DB tests. Existing tests that move to handles: the breaker unit tests, the three DB uses in `test_orchestrator_run_billing_breaker.py` (including `_DenyingBreaker`), and `test_lost_probe_lets_a_new_probe_start`, which changes to the new lease. The AC-20 tests keep their meaning.

## Verification requirements

- Dated records in the T-014 report format (command, exit code, counts, environment, date; `NOT RUN` with the reason where not executed).
- A recorded failing run of test 1 against the old implementation, before the ownership change.
- The DB-free gate (`scripts/check.py`) after the change.
- The database suite only through the owner-run `/run-db-suite all`, local PostgreSQL. No Neon, no real provider spend.
- A fresh-context spec-auditor audit (SDD rule 20) reporting PASS, PARTIAL or FAIL per criterion. The implementing session never audits its own task. `Verified` requires that audit and the evidence above.
- `docs/traceability.md`: AC-64 and AC-65 move from `Specified` to `Implemented` after implementation, and to `Verified` only with the linked evidence. AC-20 and D-35 are not re-marked because of this task.

## Acceptance criteria

AC-64 and AC-65 pass with recorded evidence; AC-20 and D-35 tests still pass with unchanged meaning; no new setting or environment variable; T-011 is untouched; no requirement is `Verified` without linked evidence and the final audit.

## Follow-up considerations (not in scope)

- **Adapter timeout limitation.** The call bound relies on the provider adapter honoring `ProviderGenerationRequest.timeout_seconds` ([orchestrator.py](../../app/ai_platform/orchestrator.py), the request deadline minus elapsed time). Nothing in `app/ai_platform` enforces a hard timeout, and no real adapter exists yet. Ownership makes an overshoot safe: a probe that outlives its lease is superseded, and its late outcome is ignored. It does not make the lease adequate. A hard timeout is a separate decision.
- **Async worker path (T-008).** How a probe claimed by an async worker interacts with the lease and the worker's own lease and heartbeat was not verified. It must be checked when the `execute_request` path is built.
- **Margin coupling.** The margin is fixed at 30 s so it does not follow `breaker_open_seconds`. If real adapters overshoot their deadline by more than 30 s, revisit the constant.

## Evidence

- **2026-11-24, checkpoint 2: H1 tests written first and shown failing against the current implementation.** Environment: local, DB-free (no Postgres, no Redis, no Neon, no provider). `TEST_REDIS_URL` unset for the command. Code under test unchanged: `app/ai_platform/circuit_breaker.py` still has the bool API.
  - Tests added at the end of `tests/unit/ai_platform/test_circuit_breaker.py`, using the current bool API and asserting the behavior D-37 requires (AC-64 (a), (b)/(f)):
    - `test_a_released_attempt_cannot_clear_a_newer_probe_claim`: A claims the probe, a neutral outcome releases it, E claims a new probe, A's `abandon_attempt` runs; F must be denied.
    - `test_an_attempt_started_while_closed_cannot_release_the_probe_later`: a closed-state attempt's `abandon_attempt` must not release the half-open probe claimed by C.
    - `test_an_attempt_started_while_closed_cannot_close_the_breaker_as_a_probe`: a closed-state attempt's `record_success` while half-open must not close the breaker.
  - They carry `@pytest.mark.xfail(strict=True)` so the DB-free gate stays green. A strict xfail fails when the behavior is fixed, which forces removing the marker at checkpoint 3, where the tests are rewritten for attempt handles.
  - `python -m pytest tests/unit/ai_platform/test_circuit_breaker.py --runxfail -p no:cacheprovider -q -k "released_attempt or started_while_closed"`: exit 1, **3 failed**, 34 deselected. Failures: `assert True is False` (a second probe is granted while the first is still claimed) in the first two tests, and `assert 'closed' == 'half_open'` in the third. These are the H1 symptoms, not errors in the tests.
  - `python -m pytest tests/unit/ai_platform/test_circuit_breaker.py -p no:cacheprovider -q`: exit 0, **34 passed, 3 xfailed**. The 34 earlier tests are unchanged and pass.
  - `ruff check` and `ruff format --check` on that file: passed.
  - Not run: `scripts/check.py` (the full gate), `/run-db-suite`, mypy. No application code was changed at this checkpoint.
- **2026-11-24, checkpoint 3: registry ownership and lease implemented.** Environment: local, DB-free (no Postgres, Redis, Neon or provider); `TEST_REDIS_URL` unset.
  - `app/ai_platform/circuit_breaker.py`: `AttemptHandle(key, claim_id, probe)`; `begin_attempt` returns `AttemptHandle | None`; `record_success(handle)`, `record_failure(handle, kind)` and `abandon_attempt(handle)` act on the probe only for its current owner (`probe_claim`); non-probe outcomes change no open or half-open state and touch the failure history only while closed; auth failure marks the model unavailable whichever handle reports it and releases only the reporter's own claim; a probe lease replaces the old `breaker_open_seconds` rule in `begin_attempt` and `unavailable_models`. Late outcomes of an unsuperseded probe are applied.
  - `app/ai_platform/config.py`: `PROBE_LEASE_MARGIN_SECONDS = 30` (internal constant) and the derived property `probe_lease_seconds = longest_deadline_seconds + 30` (330 s with the defaults). No new field, no environment variable, no `.env*` change.
  - **Mechanical changes outside the checkpoint 3 files, needed to keep the tree compiling and the gate green** (the API change would otherwise break mypy and every orchestrator run): `app/ai_platform/orchestrator.py` passes the handle (`_guarded_attempt` takes it from `begin_attempt`, `_attempt` takes it as a parameter and calls `record_success(handle)` and `record_failure(handle, kind)`, and the existing `BaseException` handler calls `abandon_attempt(handle)`), and `_DenyingBreaker.begin_attempt` in `tests/db/test_orchestrator_run_billing_breaker.py` returns `AttemptHandle | None`. Nothing else in the orchestrator changed. The guarded release (a failing `abandon_attempt` must not replace the original exception), the new DB tests (AC-65) and the DB run are checkpoint 4 and are NOT done.
  - `tests/unit/ai_platform/test_circuit_breaker.py` rewritten for handles. The three H1 tests were rewritten for the handle API and the strict `xfail` marker was removed; they now pass. Added tests for AC-64 (a) to (h): released and closed-state handles cannot release or close a newer probe; non-probe counted failures cannot re-open a half-open breaker or change an open one; a superseded probe cannot record, an unsuperseded probe completes after lease expiry (success and failure); repeated cleanup is idempotent; auth failure leaves another handle's claim untouched; the lease is derived and independent of `breaker_open_seconds`. The AC-20 tests keep their assertions (only the call shapes changed).
  - `python -m pytest tests/unit/ai_platform/test_circuit_breaker.py -p no:cacheprovider -q`: exit 0, **50 passed**.
  - `python scripts/check.py` (ruff, mypy, `pytest -m "not db"`): exit 0, **1798 passed, 4 skipped, 264 deselected**.
  - **NOT RUN:** `/run-db-suite` (owner-run; the DB tests that use the changed API, `test_orchestrator_run_billing_breaker.py`, have therefore not run against the new registry), any Neon run, any real provider.
- **2026-11-25, checkpoint 4: orchestrator release guarded, AC-65 DB tests written.** Environment: local Windows, DB-free for the gate; `TEST_REDIS_URL` unset.
  - `app/ai_platform/orchestrator.py` (only product file changed): in `_guarded_attempt` the `BaseException` handler now calls `abandon_attempt(handle)` inside `contextlib.suppress(Exception)`, then re-raises the original exception, so a failing release cannot replace it. Handle passing and the recording of the provider outcome before `settle_call` were done in checkpoint 3 and are unchanged.
  - New `tests/db/test_orchestrator_run_probe_release.py` (4 test functions, 5 cases; AC-65, D-37). Setup: the real registry for the only model is opened with counted failures, then the fake clock moves past the open period, so the next attempt claims the half-open probe. Test 10: a budget refusal at reservation releases the probe, the breaker stays `half_open`, no provider call. Test 11: an unexpected provider exception releases the probe, the breaker stays `half_open` (not a provider failure), the original exception propagates with no `__cause__`. Test 12 (two cases): a settlement failure after a recorded success leaves the breaker `closed`, after a counted failure `open`. Test 13: `abandon_attempt` raising does not replace the original exception, the request row ends `failed`/`execution_abandoned`, and the lost release holds the probe until its lease (no second probe is admitted).
  - `env -u TEST_REDIS_URL uv run python scripts/check.py` (ruff, mypy, pytest): exit 0, **1798 passed, 4 skipped, 305 deselected** (db: 300 plus 5 new), 11.96s.
  - **NOT RUN:** a recorded red run of test 13 against the unguarded release (the test and the fix were written together); Neon; any real provider.
  - Judgment calls (owner to confirm): the lost-release case in test 13 pins today's backstop (the claim stays until the lease expires), which a later change must alter on purpose; the fault in tests 10 to 13 is injected through a `CircuitBreakerRegistry` subclass and `BudgetCoordinator` subclasses, and the half-open state is built with the real registry and `FakeClock`, not a stub.
- **2026-11-25, checkpoints 3 and 4: DB run.** `/run-db-suite all` (`bash scripts/run_db_suite.sh all`), local Postgres container, Redis up, exit 0: **305 passed, 0 failed, 0 skipped**, 1802 deselected, 97.91s; cleanup done. The 5 new tests in `test_orchestrator_run_probe_release.py` and the 9 tests in `test_orchestrator_run_billing_breaker.py` (the DB users of the changed handle API) all passed, on the tree with checkpoints 3 and 4 together. This also closes the checkpoint 3 "DB run NOT RUN" item. Checkpoint 4 approved by the owner 2026-11-25.

## Review and approval

- Plan approval: required (SDD rule 18).
- **Gate: always.** Owner review at each checkpoint:
  1. Spec change proposal and revision 11 approval: **done, 2026-11-24** (owner decision, this conversation).
  2. The failing H1 test demonstrated against the old implementation.
  3. The registry ownership and lease implementation.
  4. The orchestrator integration and DB tests.
  5. Final verification and the fresh-context spec-auditor audit.
- Readiness (`Proposed` to `Ready`): **approved 2026-11-24** ("T-022 is Ready, start checkpoint 2").
- Checkpoint 2 (failing H1 test against the old implementation): **approved 2026-11-24.**
- Checkpoint 3 (registry ownership and lease): **approved 2026-11-25** ("approved checkpoint 3, start checkpoint 4"). Its own DB run was NOT RUN; the DB test of the changed API runs with checkpoint 4.
- Checkpoint 4 (orchestrator integration and DB tests): **approved 2026-11-25** ("approved checkpoint 4, record the DB run"). Checkpoint 5 not started.
