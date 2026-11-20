# T-018 stop 2: facts read from official documentation

- **Task:** [T-018](../tasks/T-018-model-catalog-verification.md). **Date fetched:** 2026-11-20. **Run by:** agent session through three read-only fetch sub-agents. **Commands/tests:** none (NOT RUN: no code exists yet). No provider API call was made, no key was used.
- **Nothing is in the catalog yet.** This record is for owner review before stop 3 writes `models.json`.
- **Method and confidence.** Every fact below was read from the cited page in this session. The sub-agents quoted verbatim except where marked `[summary]` (a model-extracted summary of a truncated page). No fact is from memory. No page shows a publication date; "fetched on" is the date of record. `ai.google.dev` URLs redirect (HTTP 301) to `aistudio.google.com/docs/...`; the redirect targets are the sources.

## URLs read (2026-11-20)

Google: `https://aistudio.google.com/docs/models`, `/docs/models/gemini-3.8-flash`, `/docs/models/gemini-3.5-flash-lite`, `/docs/pricing`, `/docs/deprecations`, `/docs/rate-limits`, `/docs/structured-output`, `/docs/thinking`, `/docs/terms` (terms: "Effective March 23, 2026").
Perplexity: `https://docs.perplexity.ai/docs/embeddings/quickstart`, `/docs/embeddings/standard-embeddings`, `/api-reference/embeddings-post`, `/docs/getting-started/pricing`, `/docs/admin/rate-limits-usage-tiers`.
LiteLLM: `https://docs.litellm.ai/docs/providers/gemini`, `/docs/providers/perplexity_embedding`.

## Owner-selected Gemini models

| Fact | `gemini-3.5-flash-lite` (standard tier) | `gemini-3.8-flash` (high tier) |
| --- | --- | --- |
| Exact id on the pages | Yes | Yes |
| Status | Stable | Stable (see conflict 1) |
| Release / shutdown | 2026-07-21 / "No shutdown date announced" | 2026-09-02 / "No shutdown date announced" |
| Context window (input) | 1,048,576 | 1,048,576 |
| Max output | 65,536 | 65,536 |
| Inputs / output | text, image, video, audio, PDF / text | text, image, video, audio, PDF / text |
| Structured output | listed "supported" on its model page | listed "supported" on its model page |
| Input price per 1M (paid, standard) | $0.30 | $0.75 through 2026-12-31, **$1.50 from 2027-01-01** |
| Output price per 1M (incl. thinking) | $2.50 | $3.75 through 2026-12-31, **$7.50 from 2027-01-01** |
| Large-prompt higher tier | NOT STATED | NOT STATED |
| Thinking billed as output | Yes ("response pricing is the sum of output tokens and thinking tokens") | Yes |
| Thinking can be bounded | Levels minimal, low, medium, high; default minimal. `max_output_tokens` includes thought tokens (hard cutoff, output may be truncated or empty) | Levels low, medium, high (default medium); `minimal` returns an error; same `max_output_tokens` rule |
| Free tier | Yes; free-tier content is used to improve Google products ("Yes"); paid: "No" | Same |
| Per-model rate limits (RPM, TPM) | NOT STATED (pages say limits are viewed in AI Studio and are not guaranteed) | NOT STATED |
| LiteLLM id on the LiteLLM page | **NOT STATED** (id absent from the page) | `gemini/gemini-3.8-flash` stated |

Rate limits that are stated apply per account tier, not per model: spend limit per 10 minutes (Free N/A, Tier 1 $10, Tier 2 $200, Tier 3 $200). Batch enqueued-token limits are listed per tier and are not used by this module.

LiteLLM facts: AI Studio prefix is `gemini/` with `GEMINI_API_KEY`; ids without a prefix go to Vertex. `reasoning_effort` maps to Gemini `thinking_level` for Gemini 3+; LiteLLM says thinking cannot be fully disabled on Gemini 3 and it sends `low` where `minimal` is rejected; `usage.completion_tokens_details.reasoning_tokens` is billed. Structured output is passed as `response_format` with `response_schema` (and an optional `enforce_validation`); a `type: json_schema` form is NOT STATED on that page.

## Perplexity `pplx-embed-v1-0.6b`

| Fact | Value (source page) |
| --- | --- |
| API id | `pplx-embed-v1-0.6b`, `POST /v1/embeddings` (API reference enum) |
| Dimensions | 1024 native; optional `dimensions` multiples of 8 from 128 to 1024 (not used, spec 5.3) |
| Per-text limit (D-23 `EMBED_MAX_TEXT_UNITS`) | 32,768 tokens (standard-embeddings, v1 input limits) |
| Per-batch limit (`EMBED_MAX_BATCH`) | 512 texts per request |
| Total request limit (`EMBED_MAX_REQUEST_UNITS`) | 120,000 tokens combined |
| Empty input | rejected |
| Price | $0.004 per 1M tokens input; no other billed dimension listed for embeddings (pricing page) |
| Rate limits | queries per second by usage tier: Tier 0 85, Tiers 1 to 3 170, Tiers 4 to 5 335; no token-per-minute limit stated |
| `encoding_format` | `base64_int8` (default), `base64_binary`; `float` is stated unsupported only for the v2 table, NOT STATED for v1 |
| Usage block | `prompt_tokens`, `total_tokens`, `cost` {`input_cost`, `total_cost`, `currency` = USD} (API reference) |
| Data retention / training on content | NOT STATED on any of the five pages |
| LiteLLM | model string `perplexity/pplx-embed-v1-0.6b`; key variable on the LiteLLM page is `PERPLEXITYAI_API_KEY` (D-22 already reads `PERPLEXITY_API_KEY` and passes keys explicitly); whether base64 is decoded, and usage field names: NOT STATED on the LiteLLM page |

## Findings that need an owner decision

1. **`gemini-3.8-flash` has contradictory wording.** The models list calls it "our previous-generation Flash model"; its model page calls it "our most intelligent Flash model". Spec 20.4 says previous-generation models are not default production models. It is listed Stable and newer than `3.5`. Do you keep it as the high-tier model? If the answer is no, you name the replacement; the agent will not choose one. (Other Stable ids on the pages for reference only: `gemini-3.6-flash`, `gemini-3.1-flash-lite`, `gemini-2.5-flash-lite`.)
2. **A dated price change falls inside the planning window.** `gemini-3.8-flash` doubles on 2027-01-01. The catalog has one price per entry and no effective date. Option A (approved) adds no tier or date field. Proposal: enter the price valid today ($0.75/$3.75), set `price_version` to include the date, and open a follow-up (a re-verification task due before 2027-01-01, which spec section 20.3 already requires at least monthly). The metered cost and the AC-60 table would be recomputed then. Alternatively enter the 2027 price now (conservative: reservations and AC-60 then hold after the change). Which?
3. **`gemini/gemini-3.5-flash-lite` is not confirmed by LiteLLM documentation.** Only the prefix rule is documented. The catalog does not store LiteLLM ids today (the adapter maps them), so this does not block the catalog, but it stays a stated gap for the adapter task, together with checking that installed `litellm==1.109.1` knows both ids.
4. **Perplexity v1 is being phased out.** The standard-embeddings page says "v1 models will be phased out during 2027"; the current quickstart uses a v2 model. D-21 selected v1. This is a decision for you, not a catalog change; the agent will not pick a v2 model. Recording it keeps the catalog `verified` entry honest (a deprecation notice with no date).
5. **Items that cannot be verified from documentation, and how the catalog treats them.**
   - `latency_p50_ms`: not a documented fact. Both entries carry an owner-supplied estimate flagged as an estimate in the record; it never makes an entry unverified by itself.
   - Per-model Gemini rate limits and Perplexity token-per-minute limits: NOT STATED; recorded as such, outside the catalog.
   - Provider data terms: Gemini free tier uses submitted content to improve Google products; Perplexity states nothing. D-27 therefore stays in force (synthetic text only).
6. **Source quality.** The Google pages were reached by redirect and read by sub-agents; two points were a summary of a truncated page, neither is used for a catalog value (they concern `gemini-3.1` prices and the structured-output callout). Every number proposed for the catalog was read verbatim.

## Proposed catalog contents (not written yet)

| Entry | Enabled | verified | input micro-USD per 1M | output micro-USD per 1M | context | max output |
| --- | --- | --- | --- | --- | --- | --- |
| gemini / `gemini-3.5-flash-lite`, tier standard | true | true | 300,000 | 2,500,000 | 1,048,576 | 65,536 |
| gemini / `gemini-3.8-flash`, tier high | true if you keep it (finding 1) | true | 750,000 (finding 2) | 3,750,000 (finding 2) | 1,048,576 | 65,536 |
| perplexity / `pplx-embed-v1-0.6b`, embedding | true | true | 4,000 | 0 | 32,768 per text | none |

`task_min_input_units` values are chosen at stop 3 from these prices, with the AC-60 table printed, and are reviewed by you.

## Not run

Tests, the loader change and the catalog file (stop 3). `/run-db-suite` (not applicable until code exists).
