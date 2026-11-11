# AI Content Studio API

FastAPI backend (Python 3.12+) backed by Neon Postgres and Redis.

## Prerequisites

- Python 3.12+ and [uv](https://docs.astral.sh/uv/)
- A Neon Postgres dev branch
- A running Redis server (login throttling requires it)

## Setup

```powershell
cd api
uv sync
```

## Configuration

Config is read from environment files in the `api/` folder (next to this README), regardless of the directory you launch from.

For dev, create `api/.env.local`:

```
APP_ENV=dev
NEON_BRANCH_NAME=dev
DATABASE_URL=<pooled Neon dev URL>
DATABASE_URL_DIRECT=<direct Neon dev URL>
REDIS_URL=redis://127.0.0.1:16379/0
AUTH_JWT_SECRET=<random string, at least 32 bytes>
```

Generate the secret with:

```powershell
uv run python -c "import secrets; print(secrets.token_urlsafe(48))"
```

Every variable added to `.env.example` must also be added to `.env.local` in the same change. Run `just sync-env` (`scripts/sync_env_local.py`) to append the missing names as placeholders; it never changes existing lines and prints names only.

Keys are listed in `.env.example`. Never commit populated env files. `NEON_BRANCH_NAME` must match `APP_ENV` (`dev`, `test`, `production`).

## Start Redis

Pick one:

```powershell
# WSL (Ubuntu); leave this terminal open
wsl -d Ubuntu --exec redis-server --bind 127.0.0.1 --port 16379 --save "" --appendonly no

# or Docker (then use REDIS_URL=redis://127.0.0.1:6379/0)
docker run -d --name redis-dev -p 6379:6379 redis:8
```

Check with `wsl -d Ubuntu --exec redis-cli -p 16379 ping` (expects `PONG`).

## Run migrations

```powershell
just migrate
```

## Start the server

PowerShell:

```powershell
$env:APP_ENV="dev"; uv run uvicorn app.main:app --reload --port 8000
```

Git Bash / WSL / macOS / Linux:

```bash
APP_ENV=dev uv run uvicorn app.main:app --reload --port 8000
```

Always set `APP_ENV=dev` explicitly. If it is unset and `.env.test.local` exists, the app picks up `APP_ENV=test` from that file, loads `.env.test.local` instead of `.env.local`, and connects to the **test** database branch (and misses dev-only keys such as `AUTH_JWT_SECRET`). Selection order: `APP_ENV` environment variable, then `.env`, then `.env.test.local`, then dev.

- API base: `http://127.0.0.1:8000/api/v1`
- Readiness: `http://127.0.0.1:8000/readyz`

Restart the server after changing env files.

## Troubleshooting

- `503 A required service is temporarily unavailable`: a required setting is missing. Check the server log for the `configuration_error` entry, which names the setting (for example `REDIS_URL`). Login fails closed without Redis by design. `AUTH_JWT_SECRET` must also be set, or register and login return the same 503.

## Common commands

| Command | Purpose |
| --- | --- |
| `just check` | Lint, type-check and unit tests |
| `just migrate` | Apply migrations to the dev DB |
| `just test-db` | Run DB tests in Neon mode (needs `.env.test.local`, `APP_ENV=test`) |
| `just test-db-up` / `just test-db-local` / `just test-db-down` | Start, use and remove the local Docker test database (`TEST_DB_MODE=local`) |
| `just openapi` | Regenerate `openapi.json` |
| `just sync-env` | Append names missing from `.env.local` that exist in `.env.example` (names only, never values) |

## Test database modes

DB-marked tests (`-m db`) can run in two explicit modes. Neither is inferred.

- **Neon mode (default, `TEST_DB_MODE` unset or `neon`).** Needs `.env.test.local` with `APP_ENV=test`, `NEON_BRANCH_NAME=test` and the Neon test branch URLs. Behaviour is unchanged, with one addition: a loopback or unix-socket host is refused, so a local database cannot be passed off as the Neon branch.
- **Local mode (`TEST_DB_MODE=local`).** Runs on a throwaway Postgres container with pgvector (`compose.test-db.yaml`), the default for development. Set `TEST_DB_MODE=local` and `APP_ENV=test` in the process environment, and put the URLs in the git-ignored `.env.test.docker.local` (placeholders in `.env.example`). `.env.test.local` is never read in this mode, and `NEON_BRANCH_NAME` must be unset. The guard accepts only a `localhost`, `127.0.0.1`, `::1` or unix-socket host, a database name ending in `_test`, and identical pooled and direct URLs, and then, before migrations, confirms on the live server that `current_database()` matches and that the database-level marker `app.test_db_marker` equals `local-throwaway-v1` (set by the container's init script, so it is positive evidence that the server is the throwaway container). Anything else refuses to run.

```powershell
$env:TEST_DB_PASSWORD="<choose a throwaway password>"   # same value as in .env.test.docker.local
docker compose -f compose.test-db.yaml up -d --wait     # just test-db-up
$env:TEST_DB_MODE="local"; $env:APP_ENV="test"
uv run python scripts/test_db.py                        # just test-db-local
docker rm -f strativa-test-db                           # just test-db-down (data is on tmpfs)
```

`APP_ENV=test` must be exported in the process environment, not only present in `.env.test.docker.local`. The entry guard and most DB tests load that file, but tests that build `Settings(_env_file=None)` (the auth, workspace and profile API tests, 13 in all) read only the process environment and fail with `TEST_DB_MODE=local requires APP_ENV=test` if it is missing. The guard is correct to refuse.

SQLite is never a substitute. Tests never run against the dev or production databases. A scheduled nightly run on the Neon `test` branch is planned as a later delivery-phase job and is not defined yet.

See `docs/specs/` for module specs and `docs/reports/phase0-verification.md` for verification commands.
