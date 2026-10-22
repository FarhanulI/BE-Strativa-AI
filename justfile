check:
    uv run --directory apps/api --project . --python 3.12 --no-sync python scripts/check.py

migrate:
    uv run --directory apps/api --project . --python 3.12 --no-sync python scripts/migrate.py upgrade

migrate-test:
    uv run --directory apps/api --project . --python 3.12 --no-sync python scripts/migrate.py upgrade --require-test

test-db:
    uv run --directory apps/api --project . --python 3.12 --no-sync python scripts/test_db.py

openapi:
    uv run --directory apps/api --project . --python 3.12 --no-sync python scripts/generate_openapi.py