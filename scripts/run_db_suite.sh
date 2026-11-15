#!/usr/bin/env bash
# Run the local database test suite on the throwaway Postgres container, then clean up.
# Usage: bash scripts/run_db_suite.sh [--replace] [all | tests/db/<file>.py]
# TEST_DB_PASSWORD must already be exported in the shell. It is never accepted as an argument.
set -euo pipefail

COMPOSE_FILE="compose.test-db.yaml"
CONTAINER="strativa-test-db"

cd "$(dirname "$0")/.."

# --- arguments -----------------------------------------------------------------------------
replace=0
if [ "${1:-}" = "--replace" ]; then
  replace=1
  shift
fi
if [ "$#" -gt 1 ]; then
  echo "Refused: expected at most one argument (all or tests/db/<file>.py)." >&2
  exit 2
fi
target="${1:-all}"
if [ "$target" != "all" ]; then
  if ! [[ "$target" =~ ^tests/db/[A-Za-z0-9_./-]+\.py$ ]] || [[ "$target" == *..* ]] \
    || [ ! -f "$target" ]; then
    echo "Refused: argument must be 'all' or an existing tests/db/<file>.py path." >&2
    exit 2
  fi
fi

# --- preconditions -------------------------------------------------------------------------
if ! docker info >/dev/null 2>&1; then
  echo "Docker is not running. Start Docker Desktop and run this again." >&2
  exit 3
fi
if [ -z "${TEST_DB_PASSWORD:-}" ]; then
  echo "TEST_DB_PASSWORD is not set. Before starting the agent, set it in the shell" >&2
  echo "(for example: read -rs TEST_DB_PASSWORD; export TEST_DB_PASSWORD)." >&2
  echo "It must equal the password in .env.test.docker.local." >&2
  exit 4
fi
if docker ps -a --format '{{.Names}}' | grep -qx "$CONTAINER"; then
  if [ "$replace" -ne 1 ]; then
    echo "Container $CONTAINER already exists. Remove it yourself or run again with --replace." >&2
    exit 5
  fi
  docker rm -f "$CONTAINER" >/dev/null
fi

# --- run -----------------------------------------------------------------------------------
out="$(mktemp)"
cleanup() {
  rm -f "$out"
  docker compose -f "$COMPOSE_FILE" down >/dev/null 2>&1 || true
  echo "cleanup done"
}
trap cleanup EXIT

docker compose -f "$COMPOSE_FILE" up -d --wait >/dev/null

if [ "$target" = "all" ]; then
  cmd=(uv run python scripts/test_db.py)
else
  cmd=(uv run pytest -m db "$target" -q --tb=short)
fi

set +e
TEST_DB_MODE=local APP_ENV=test "${cmd[@]}" >"$out" 2>&1
status=$?
set -e

# Redact the password (read from the environment, never from an argument) before printing.
uv run python -c '
import os, sys
secret = os.environ.get("TEST_DB_PASSWORD", "")
text = sys.stdin.read()
sys.stdout.write(text.replace(secret, "[REDACTED]") if secret else text)
' <"$out"

summary="$(grep -E '[0-9]+ (passed|failed|skipped|errors?)' "$out" | tail -n 1 \
  | grep -oE '[0-9]+ (passed|failed|skipped|errors?|xfailed|xpassed|deselected)' \
  | paste -sd, - | sed 's/,/, /g' || true)"
if [ -n "$summary" ]; then
  echo "Summary: $summary"
fi

exit "$status"
