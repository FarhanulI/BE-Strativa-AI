check:
    uv run --python 3.12 --no-sync python scripts/check.py

migrate:
    uv run --python 3.12 --no-sync python scripts/migrate.py upgrade

migrate-test:
    uv run --python 3.12 --no-sync python scripts/migrate.py upgrade --require-test

test-db:
    uv run --python 3.12 --no-sync python scripts/test_db.py

sync-env:
    uv run --python 3.12 --no-sync python scripts/sync_env_local.py

openapi:
    uv run --python 3.12 --no-sync python scripts/generate_openapi.py

test-db-up:
    docker compose -f compose.test-db.yaml up -d --wait

test-db-local:
    TEST_DB_MODE=local uv run --python 3.12 --no-sync python scripts/test_db.py

test-db-down:
    docker rm -f strativa-test-db
