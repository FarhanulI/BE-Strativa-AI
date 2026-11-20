# T-018: Model catalog verification from official documentation

- **Module and phase:** ai_platform, Phase 2
- **State:** Ready (plan approved by the owner 2026-11-20; blocked at stop 1 on CP-1 approval before any code)
- **Requirement IDs:** AC-60 (catalog fitness; currently `Specified`). Context: D-21, D-22, D-26, D-27, D-28 and spec section 20.4.
- **Specification references:** [AI Platform spec](../specs/ai-platform/spec.md) sections 9, 10.1, 12.2, 17.4 (AC-60), 20.3, 20.4; [conformance report](../architecture/conformance-report.md) F-1
- **Dependencies:** T-017 (LiteLLM installed, for the LiteLLM identifier checks). Owner approval of the catalog format. Web access to official documentation. No provider API call is made, so the spend cap (D-11, D-16) is not touched and D-27 is not engaged.

## Objective
Replace the unverified owner-selected model identifiers and the embedding limits with entries verified against official documentation fetched in this session, stored in a committed catalog file that the loader trusts only when it says it was verified.

## Scope
- Official sources only, fetched in the session, with the URL and fetch date recorded: Google AI documentation for Gemini models, Perplexity documentation for `pplx-embed-v1-0.6b`, LiteLLM documentation for the provider identifiers. Anything not found is left unverified; nothing is written from memory.
- For each model, record what spec 20.4 lists: exact id and LiteLLM id; general availability or preview; deprecation date; context window; maximum output; structured-output support; prices including any large-prompt tier; whether thinking units are billed as output; free-tier availability and data terms; rate limits; scheduled price changes. Embedding model: the per-text, per-batch and total-request limits (D-23) and the price.
- The owner-selected `gemini-3.5-flash-lite` and `gemini-3.8-flash` are checked against the documentation. If a document does not confirm one, that entry stays `verified: false` and is reported to the owner. It is never replaced by another model silently.
- Catalog file: `app/ai_platform/catalog_data/models.json` (changed from `catalog/`, which collides with `catalog.py`; see CP-1). Each entry carries the source URL, the verification date, a `verified` flag; the file carries `catalog_version` and `price_version`.
- Loader change: `load_catalog` refuses any entry with `verified: false` outside tests (tests use the synthetic catalog helper). The refusal message names no model content beyond the field path.
- AC-60: the DB-free fitness test over every (task, model) pair, with the per-task `required_min_input_units` set from verified prices.

## Non-goals
Calling any provider. Choosing models the owner did not select. The adapter. Changing Router logic. Real user data (D-27).

## Implementation expectations
`CatalogModel` already has `price_source_url` and `price_checked_on` and forbids extra fields. A `verified` flag and a verification date for non-price facts are new fields. **If spec section 10.1 or 20.4 does not already define them, stop and write a spec change proposal before changing the model; do not edit the approved spec.** Large-prompt price tiers must be representable or the entry is not enabled; if the model cannot represent them, stop and propose.

## Required tests
Loader refuses an unverified entry outside tests and accepts it in tests; schema strictness for the new fields; AC-60 fitness table printed and asserted; the existing catalog tests unchanged.

## Verification requirements
A record (T-014 format) with the list of fetched URLs and dates, the verified facts per model, the commands run for the tests with exit codes and counts, and what remained unverified.

## Acceptance criteria
- Every enabled entry is `verified: true` with source URL and date; unverified entries are disabled or absent.
- The loader refuses unverified entries in production use.
- AC-60 has an executed test with dated evidence, or stays `Specified`/`Gap` with the reason.
- The owner has reviewed the verified facts.

## Evidence
- 2026-11-20 stop 1: SDD-Q-3 answered by reading spec 10.1 and 20.4: they do not define `verified`, `verified_on`, large-prompt tiers or `required_min_input_units`. Change proposal written: [CP-1](../specs/ai-platform/change-proposals/CP-1-catalog-verification-fields.md). No code, fetch or spec edit has happened.

## Review and approval
Not requested. **Gate: always** (AI targets; possible contract change).
