# Phase 1 Contract Diff

Target: `web/docs/backend/openapi.json` (SHA-256 `7d14bf113dbac6f626bc54ae5b88e892aec9ad6e1603c560e70a0f4ed65bd88d`, verified).
Generated: `create_app(...).openapi()` at commit `453c6fe`, written to a scratch path (repo `openapi.json` untouched).

## Step 0 results

- Non-DB tests (`tests/unit`): 128 passed.
- DB suites (`pytest -m db`): 81 passed, on the local throwaway pgvector container (`TEST_DB_MODE=local`) after `alembic upgrade head` (0001 to 0008).
- Neon `test` branch (`br-rapid-silence-b3iezotg`, project `nameless-heart-50634755`) was inspected read-only: `alembic_version = 0014_rag_source_id_denylist`, 22 tables. It is AHEAD of this repo (head 0008), so `upgrade head` was not run and DB suites were not run against it. Nothing on it was changed.

## Structural diff

| Aspect | Result |
| --- | --- |
| Paths and methods | Identical (41 operations) |
| `components` (all schemas) | Identical |
| Parameters, `If-Match` (13 operations), `ETag` response headers | Identical |
| `Idempotency-Key`, `X-Request-ID` | Absent from both target and generated |
| Status codes 401/403/404/409/422/428/429/500/502 | Identical |
| Problem+json shape (`ProblemDetails`) | Identical |
| Status code 503 | **Differs**: generated declares a `503` problem+json response on all 41 operations; the target declares it only on the operations that own one (`/readyz`) |

No ai_platform paths appear in either document, so there are no class (a) differences.

## Classification

| # | Difference | Class | Notes |
| --- | --- | --- | --- |
| 1 | `503` response declared on every operation by `openapi_with_shared_schemas` (`app/api_contract/app.py`, `setdefault`) | (c) target looks incomplete, needs owner decision | The central `ConfigurationError` handler really does return 503 problem+json at runtime for any route, so the BE declaration is accurate. Removing it would hide real behavior. |
| 2 | Maturity thresholds are dataclass defaults, not typed settings | (b) fix | Not visible in OpenAPI; spec requires typed settings. |

## Verified present (no change needed)

`PATCH /auth/me`; password 12 to 128; name limits 160; 428/409-with-current-state on all 13 profile writes (`tests/db/test_profile.py`); central `ConfigurationError` to 503 handler; refresh cookie `refresh_token` (HttpOnly, Secure, SameSite=Lax, path `/api/v1/auth`, max-age = refresh TTL); `expires_in` (900) on token responses.
