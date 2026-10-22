# Phase 0 Verification

## Safe Local Setup

Use Python 3.12 and `uv sync --python 3.12`. Dependencies must be installed before running scripts with plain Python. Never print, commit, or paste connection strings into logs.

Configure repository-root `.env.test.local` using `.env.example`: explicitly set `APP_ENV=test` and `NEON_BRANCH_NAME=test`; supply the dedicated test branch's pooled `DATABASE_URL` and direct `DATABASE_URL_DIRECT` or `DATABASE_URL_UNPOOLED`. Both aliases, if populated, must be identical. Set a real `REDIS_URL` for worker/demo verification. Keep dev credentials in `.env.local` with dev/dev selectors. Prefer `APP_ENV=test` in the invoking process to select the test file unambiguously.

Before a destructive downgrade, compare both configured endpoint hosts with Neon branch metadata. The 2026-10-14 run confirmed project `nameless-heart-50634755`, non-default branch `test` (`br-rapid-silence-b3iezotg`), endpoint `ep-jolly-grass-b3wiywq9`. The initial test DB had no tables. No dev or production database changes were made. Labels alone are not proof of endpoint identity.

The original guard failure was missing environment/branch selectors, not a URL alias conflict. The existing guard was retained. A separate runtime failure found during live verification was fixed by passing `prepared_statement_cache_size` through SQLAlchemy `connect_args` instead of as an engine option.

## Commands Without Just

Run from the repository root. The following `uv` commands are the equivalents of every existing `justfile` target; `just` and `make` are not required.

| Just Target | Equivalent Command |
| --- | --- |
| `check` | `uv run --python 3.12 --no-sync python scripts/check.py` |
| `migrate` | `uv run --python 3.12 --no-sync python scripts/migrate.py upgrade` |
| `migrate-test` | `APP_ENV=test uv run --python 3.12 --no-sync python scripts/migrate.py upgrade --require-test` |
| `test-db` | `APP_ENV=test uv run --python 3.12 --no-sync python scripts/test_db.py -q` |
| `openapi` | `uv run --python 3.12 --no-sync python scripts/generate_openapi.py` |

With the API virtual environment activated, omit the `uv run ...` prefix and use `python scripts/<script>.py` with the same arguments. The runners resolve their own package paths. Bash prefixes are shown; in PowerShell set `$env:APP_ENV = 'test'` before invoking the command.

Run the reversible live test cycle before integration tests (this deletes test foundation state):

```bash
APP_ENV=test uv run --no-sync python scripts/migrate.py upgrade --require-test
APP_ENV=test uv run --no-sync python scripts/migrate.py downgrade --require-test
APP_ENV=test uv run --no-sync python scripts/migrate.py upgrade --require-test
APP_ENV=test uv run --no-sync python scripts/migrate.py check --require-test
APP_ENV=test uv run --no-sync python scripts/test_db.py -q
APP_ENV=test uv run --no-sync python scripts/demo_ping.py
APP_ENV=test uv run --no-sync python scripts/verify_phase0.py
```

The demo commits producer audit state and an outbox event in one transaction, relays through real Redis, and consumes the exact event twice using the same consumer group. It requires two acknowledged deliveries, exactly one processed-event record, and exactly two audit rows (producer plus consumer). It uses/deletes a unique Redis stream and retains correlated DB evidence; repeat runs use new event IDs. It is an integration script, not a new HTTP endpoint.

For this run, Redis 8 was already installed in Ubuntu WSL and was started temporarily with `wsl -d Ubuntu --exec redis-server --bind 127.0.0.1 --port 16379 --save "" --appendonly no`. The demo received `REDIS_URL=redis://127.0.0.1:16379/15` via its process environment. No Redis credentials were saved, no Docker was used, and no fake service was substituted. Start a real Redis instance before rerunning, and stop the temporary instance after verification.

## Evidence

- Live test upgrade to `0004_citext`, downgrade to base, and upgrade back to head: passed.
- Live Alembic drift check: `No new upgrade operations detected.` The DB suite now includes drift detection in its migration setup. Explicit ORM model registration fixed the initially empty autogeneration metadata.
- PostgreSQL integration suite: 6 passed, including isolated two-connection `SKIP LOCKED`, producer state/event rollback, persisted consumer idempotency, exact UPDATE/DELETE rejection, and tenant metadata checks.
- Real Redis/Neon demo: `deliveries=2`, `processed_events=1`, `audit_records=2`, `correlation_verified=true`, `redelivery_idempotent=true`.
- Installed extensions: `citext 1.8`, `pgcrypto 1.4`, `vector 0.8.6`. Case-insensitive comparison and built-in `gen_random_uuid()` passed. The database has zero vector columns and only foundation tables. `uuid-ossp 1.1` is available but not installed or required.
- `verify_phase0.py` confirmed live `/readyz` HTTP 200 with database/Redis `ok`. Its PostgreSQL probe uses a five-second attempt timeout and ten-second total deadline, replacing one-second attempts that failed a measured healthy 1.484-second TLS connection.
- Shared `ProblemDetails`, `CursorParams`, and `CursorPage` exports match regenerated OpenAPI JSON, including `application/problem+json` error responses. Generation uses no DB or Redis connections.
- Portable `check.py`: Ruff passed, configured core mypy passed, and 41 DB-free tests passed. Test-only migration commands reject dev selection before connecting. Direct script and `uv` entrypoints were exercised from the repository root; `just` itself is not installed.

Only the dedicated test branch is certified by this close-out. Dev/production rollout, infrastructure durability/load/failover testing, web foundation, TypeScript client generation, and Phase 1 remain outside this verification task.

## Close-out Decisions

1. Branch/environment validation remains enforced when a database URL is configured, preserving DB-free OpenAPI generation.
2. The foundation modules were implemented and verified without adding Phase 1 features. Live verification corrected pooled-cache argument placement and explicit Alembic model registration.
3. This close-out certifies only the dedicated test branch, not dev or production.
4. The local setup repair added only the missing `APP_ENV` and `NEON_BRANCH_NAME` selectors; existing credential values were preserved and the environment guard was not weakened.