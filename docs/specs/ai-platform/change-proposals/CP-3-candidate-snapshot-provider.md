# CP-3: `provider` in `candidate_snapshot` entries (change proposal for the AI Platform spec)

- **Status:** Approved by the owner 2026-11-23, together with the T-011 scope extension below, and applied as spec revision 10.
- **Raised by:** task [T-011](../../../tasks/T-011-ai-platform-sync-run-path.md), step 3. The owner's DB run of 2026-11-23 failed 8 of 9 new tests with `ValueError: candidate_snapshot entries allow only model, eligible, reason_code`.
- **Spec revision it would amend:** revision 9, producing revision 10. Section 4.2 (the `candidate_snapshot` row of `ai_usage_records`) only.
- **Rule:** SDD rules 4 and 15. A spec conflict is a change proposal, never a silent edit.

## Why

The spec contradicts itself:

- Section 4.2 describes the stored `candidate_snapshot` as `{model, eligible, reason_code}`.
- Section 10.5 says the Router's snapshot is `{provider, model, eligible, reason_code}`, and that this snapshot is what the usage row records ("which model served this, why, and what else was considered").

The Router follows 10.5. `budget_repository._validate_reserved_record` follows 4.2 and refuses any other key. The orchestrator stores the Router's snapshot unchanged (D-24, 10.5), so every real reservation fails. `provider` is also needed: a model name alone does not identify a catalog entry, since the catalog key is `(provider, model)` and the Router orders ineligible entries by `(provider, model)`.

## Proposed text

**Section 4.2, `candidate_snapshot` row.** Replace
"ordered list of `{model, eligible, reason_code}` (ids and codes only, no content)"
with
"ordered list of `{provider, model, eligible, reason_code}` (ids and codes only, no content), exactly the Router snapshot of 10.5".

No other section changes. Section 10.5, INV-5, AC-14 and the no-leakage rules (INV-18, INV-24) already describe or permit this shape: `provider` is a catalog id, not content. No new decision ID is proposed, since this corrects 4.2 to match 10.5 and changes no behavior the spec defined elsewhere. Say so if you want a `D-37` recorded anyway.

## Scope extension requested for T-011

T-011 lists the Router, failure policy, message builder, breaker and `BudgetCoordinator` as out of scope, and says to stop on a defect there. The defect is in the budget repository validator, which `BudgetCoordinator` uses. On approval I would add to T-011 (step 3 area, same commit series):

1. [app/ai_platform/budget_repository.py](../../../../app/ai_platform/budget_repository.py): add `"provider"` to `_SNAPSHOT_KEYS` (line 47) and to the error text (line 419). Entries stay a subset check, so the three-key entries used by existing tests remain valid; `provider` becomes allowed, not required.
2. Tests of that validator and its callers that pin the old key list or error text: [tests/unit/ai_platform/test_budget_repository_validation.py](../../../../tests/unit/ai_platform/test_budget_repository_validation.py) (updated and extended with a case that accepts `provider` and one that still rejects an unknown key such as `prompt`). I will check the other files that use the snapshot (`tests/db/test_budget_coordinator.py`, `test_budget_repository.py`, `test_budget_usage_services.py`, `tests/helpers/ai_request_db_env.py`, `tests/unit/ai_platform/test_router.py`) and change one only if it fails or pins the old text.
3. A DB-level assertion in the T-011 success test that the stored `candidate_snapshot` equals the Router's snapshot, provider included.

Not touched: Router, failure policy, message builder, breaker, `BudgetCoordinator`, migrations (the column is jsonb with no key constraint).

## Impact

- Requirements: AC-14 and INV-5 (determinism of the Router snapshot) are unaffected. The stored snapshot now equals the Router's, which is what D-24 and 10.5 intend. No requirement changes status.
- Existing data: none (no usage rows exist yet, since the orchestrator is not wired in).
- Security: the snapshot still holds ids and codes only (INV-18, INV-24).

## Owner decision requested

1. Approve the 4.2 text above as spec revision 10?
2. Approve the T-011 scope extension to `budget_repository.py` and its tests, as listed?

On approval I apply revision 10 (spec header, revision note, `docs/decisions.md` or traceability only if the spec's own rules require it), make the change, record the failed step-3 run honestly in the task Evidence, run the DB-free gate, commit and push, and ask you to type `/run-db-suite all`.
