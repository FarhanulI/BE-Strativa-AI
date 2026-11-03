from __future__ import annotations

import hashlib
import json
from pathlib import Path

from app.api_contract.app import create_app
from app.core import AppEnvironment, Settings

REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
COMMITTED_OPENAPI = REPOSITORY_ROOT / "openapi.json"
# SHA-256 of the FE target (web/docs/backend/openapi.json). Changing it is a contract change
# and must be agreed with the FE repo.
TARGET_SHA256 = "7d14bf113dbac6f626bc54ae5b88e892aec9ad6e1603c560e70a0f4ed65bd88d"


def _generated_text() -> str:
    settings = Settings(
        _env_file=None,
        app_env=AppEnvironment.DEV,
        database_url=None,
        database_url_direct=None,
        database_url_unpooled=None,
        neon_branch_name=None,
        redis_url=None,
        otel_exporter_otlp_endpoint=None,
        sentry_dsn=None,
    )
    document = json.dumps(create_app(settings).openapi(), indent=2, sort_keys=True) + "\n"
    return document.replace("\n", "\r\n")  # same bytes as scripts/generate_openapi.py


def test_generated_openapi_matches_committed_copy() -> None:
    committed = json.loads(COMMITTED_OPENAPI.read_text(encoding="utf-8"))
    assert json.loads(_generated_text()) == committed, "run `just openapi` and commit the result"


def test_committed_openapi_bytes_match_fe_target() -> None:
    assert hashlib.sha256(COMMITTED_OPENAPI.read_bytes()).hexdigest() == TARGET_SHA256


def test_generated_openapi_hash_matches_fe_target() -> None:
    digest = hashlib.sha256(_generated_text().encode("utf-8")).hexdigest()
    assert digest == TARGET_SHA256
