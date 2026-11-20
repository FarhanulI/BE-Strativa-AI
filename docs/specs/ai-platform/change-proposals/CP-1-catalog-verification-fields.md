# CP-1: Catalog verification fields (change proposal for the AI Platform spec)

- **Status:** Proposed (not applied; the approved spec is unchanged)
- **Raised by:** task [T-018](../../../tasks/T-018-model-catalog-verification.md), 2026-11-20
- **Spec revision it would amend:** revision 7. Sections 10.1 and 17.5 (AC-60). Answers SDD-Q-3.
- **Rule:** SDD rules 4 and 15. Nothing in `spec.md` is edited until the owner approves this proposal and records a new revision.

## Why

Spec 10.1 lists the exact fields of a catalog entry. It has no `verified` flag, no verification date for non-price facts, no large-prompt price tier and no per-task `required_min_input_units` (AC-60 says the value is "catalog configuration"). `CatalogModel` forbids extra fields, so none of these can be added without changing a contract. Section 20.4 says the owner-selected Gemini ids are unverified, and T-018 must stop a loader from trusting them.

## Proposed changes

1. **Entry fields (10.1).** Two new required fields on every model entry:
   - `verified: bool` (strict). `true` only when every fact in the entry was read from the cited official source.
   - `verified_on: date`. The date the non-price facts were checked. `price_checked_on` stays as it is.
   An entry with `enabled: true` and `verified: false` is invalid in a production load.
2. **Loader rule (10.1).** `load_catalog(path, *, allow_unverified: bool = False)`. With the default, any entry with `verified: false` raises `ConfigurationError`. The message names field paths only (for example `models.1.verified`), never model content. Tests pass `allow_unverified=True` or use the synthetic catalog helper.
3. **Per-task minimum input (AC-60).** A top-level catalog field `task_min_input_units`, a map from task name to a positive integer. Keys must be known task names. The values are set from verified prices in the catalog step. No number is written in the spec.
4. **Large-prompt price tiers.** Two options. The owner chooses.
   - **Option A (recommended):** no tier field. The catalog holds one input and one output price. A model with a documented large-prompt tier above the usable context is entered with the base price only if the tier cannot be reached under the task ceilings (AC-60 (b) proves this per task). Otherwise the entry stays `enabled: false` and is reported. This adds no contract surface and keeps D-19 (catalog list price is the authority).
   - **Option B:** add optional `input_tiers` and `output_tiers` lists (threshold units, price). The reservation and cost formulas (12.2) must then change. This touches the budget path and is a larger change than T-018.
5. **Data file location.** `app/ai_platform/catalog_data/models.json`. The task text said `app/ai_platform/catalog/`, which would collide with the existing module `app/ai_platform/catalog.py`. INV-3 is unaffected (the catalog file is still one of the three places that may hold identifiers).
6. **Not changed.** No billing-mode field (D-19). `latency_p50_ms` stays a static estimate. It is not a documented fact, so it never makes an entry `verified` by itself; the record states it as an estimate. Rate limits stay out of the catalog (they are not entry fields in 10.1) and are recorded in the T-018 evidence only.

## Impact

- Catalog tests: new field tests; existing tests need the two fields added to their sample entries (a test-data change, not a behavior change).
- No schema, migration, event or HTTP change. No provider call.
- Traceability: AC-60 only. INV-3 and INV-12 are not affected.

## Owner decisions requested

1. Approve items 1 to 3, 5 and 6 as written?
2. Option A or Option B for item 4?

On approval I record a spec revision (8), add a decision `D-36` text for the loader rule only if you want it as a decision rather than spec text, and proceed to stop 2 (fetch official sources).
