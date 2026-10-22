from __future__ import annotations

import json
from pathlib import Path

from app.api_contract.app import create_app
from app.core import AppEnvironment, Settings

output_path = Path(__file__).resolve().parents[1] / "openapi.json"
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
output_path.write_text(
    json.dumps(create_app(settings).openapi(), indent=2, sort_keys=True) + "\n",
    encoding="utf-8",
)