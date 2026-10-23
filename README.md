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
| `just test-db` | Run DB tests (needs `.env.test.local`, `APP_ENV=test`) |
| `just openapi` | Regenerate `openapi.json` |

See `docs/specs/` for module specs and `docs/reports/phase0-verification.md` for verification commands.
