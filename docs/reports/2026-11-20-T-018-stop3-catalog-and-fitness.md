# Evidence record: T-018 stop 3 (catalog file, loader refusal, AC-60 fitness)

## Record

| Field | Value |
| --- | --- |
| Task | [T-018](../tasks/T-018-model-catalog-verification.md) |
| Date of execution | 2026-11-20 |
| Environment | Local Windows, Python 3.12, `uv run`, DB-free (`TEST_REDIS_URL` unset for the gate). No database, no Redis, no Neon, no provider call. |
| Commit | Working tree on top of the spec revision 8 commit; the code and test files were uncommitted when run (committed right after, see the task Evidence) |
| Run by | Agent session |

## Commands

| # | Exact command | Exit code | Passed | Failed | Skipped | Errors |
| --- | --- | --- | --- | --- | --- | --- |
| 1 | `uv run pytest tests/unit/ai_platform/test_catalog_verification.py tests/unit/ai_platform/test_catalog_fitness.py tests/unit/ai_platform/test_ai_platform_catalog.py -q -s` | 0 | 67 | 0 | not reported | 0 |
| 2 | `env -u TEST_REDIS_URL uv run python scripts/check.py` (ruff, mypy, `pytest -m "not db"`) | 0 | 1730 | 0 | 4 (the `redis`-marked tests, by design) | 0 |
| 3 | `uv run ruff check .` | 0 | n/a | n/a | n/a | n/a |
| 4 | `uv run mypy` | 0 | n/a | n/a | n/a | n/a |

Deselected by command 2: 200 (`db` tests). The previous gate count was 1709 passed (T-017); the new 21 are this task's tests.

## AC-60 table (printed by command 1, default cost ceilings 20,000 / 100,000 / 500,000 micro-USD)

| Task | Model | Ceiling | Output cost | Max input units | Required min | OK |
| --- | --- | --- | --- | --- | --- | --- |
| ANALYZE_MARKET_TRENDS | gemini-3.5-flash-lite | 100000 | 10000 | 300000 | 32000 | yes |
| ANALYZE_MARKET_TRENDS | gemini-3.8-flash | 100000 | 15000 | 113333 | 32000 | yes |
| GENERATE_CONTENT_BRIEF | gemini-3.8-flash | 500000 | 22500 | 636666 | 100000 | yes |
| GENERATE_CHANNEL_EXECUTION | gemini-3.5-flash-lite | 100000 | 10000 | 300000 | 32000 | yes |
| GENERATE_CHANNEL_EXECUTION | gemini-3.8-flash | 100000 | 15000 | 113333 | 32000 | yes |
| GENERATE_CONTENT_DRAFT | gemini-3.8-flash | 500000 | 30000 | 626666 | 100000 | yes |
| GENERATE_HOOK_VARIATIONS | gemini-3.5-flash-lite | 20000 | 3750 | 54166 | 8000 | yes |
| GENERATE_HOOK_VARIATIONS | gemini-3.8-flash | 20000 | 5625 | 19166 | 8000 | yes |
| ANALYZE_PERFORMANCE | gemini-3.8-flash | 100000 | 15000 | 113333 | 32000 | yes |
| EXTRACT_AUDIENCE_SIGNALS | gemini-3.5-flash-lite | 20000 | 7500 | 41666 | 8000 | yes |
| EXTRACT_AUDIENCE_SIGNALS | gemini-3.8-flash | 20000 | 11250 | 11666 | 8000 | yes |
| SYNTHESIZE_SIGNALS | gemini-3.5-flash-lite | 100000 | 10000 | 300000 | 32000 | yes |
| SYNTHESIZE_SIGNALS | gemini-3.8-flash | 100000 | 15000 | 113333 | 32000 | yes |
| EMBED_TEXT | pplx-embed-v1-0.6b | 20000 | 0 | 5000000 | 120000 | yes |

Tightest pair: `gemini-3.8-flash` on EXTRACT_AUDIENCE_SIGNALS (11,666 max input against 8,000 required). Hand-computed values match the test output.

## Requirements covered

| Requirement ID | Mapped tests that ran | Clause covered | Result | Proposed status |
| --- | --- | --- | --- | --- |
| AC-60 | `test_catalog_fitness.py` (4 tests), `test_catalog_verification.py` (loader refusal, strict fields) | Whole requirement against the committed catalog | passed | Implemented. Not `Verified` until the owner reviews the catalog values, because the per-task minimums and `latency_p50_ms` are proposals, not documented facts |

## Failures

None.

## Not run

`/run-db-suite all` (to be run by the owner after review; no database path changed). Any provider call (none exists; D-27). LiteLLM id check for both Gemini ids against the installed `litellm==1.109.1` (adapter task).

## Open items and judgment calls (owner review)

1. **`retrieval_grounding` capability.** Six tasks require it. No documentation page states it as a Gemini model capability: in this module it means the model answers from context the application supplies. Without it no model is eligible for those tasks. It is entered for both Gemini models as an interpretation, not a documented fact.
2. **`task_min_input_units`.** Only `EMBED_TEXT` (120,000, the documented per-request limit) is grounded in a source. The others are proposals by cost class: 8,000 (low), 32,000 (medium), 100,000 (high). They are not derived from any retrieval design, which does not exist yet.
3. **`latency_p50_ms`.** 1,500 (`gemini-3.5-flash-lite`), 3,000 (`gemini-3.8-flash`), 300 (embedding). Unmeasured placeholders that only fix the ranking order for `interactive` tasks. No page states latency.
4. **Embedding limits are env configuration, not catalog data.** Verified values for `EMBED_MAX_TEXT_UNITS` (32768), `EMBED_MAX_BATCH` (512), `EMBED_MAX_REQUEST_UNITS` (120000) are in the stop 2 record. Setting them touches `.env.example` and `.env.local` and falls under the ENV rule; not done here.
5. **`gemini-3.8-flash` price** is today's ($0.75 / $3.75 per 1M). It doubles on 2027-01-01. A re-verification is due before then (SDD-Q-11).
6. **Embedding `quality_tier`.** Entered as `standard` because `EMBED_TEXT` has quality `standard` and the filter requires `tier >= task.quality`.
7. **Source URL.** The spec has one `price_source_url` per entry. The other pages read are listed in the stop 2 record.
