from __future__ import annotations

import subprocess
import sys
from pathlib import Path

from app.core.config import AppEnvironment, Settings

settings = Settings()
if settings.app_env != AppEnvironment.TEST or settings.neon_branch_name != "test":
    raise SystemExit("DB tests require APP_ENV=test and NEON_BRANCH_NAME=test")
settings.require_database_url(direct=True)
raise SystemExit(
    subprocess.call(
        [sys.executable, "-m", "pytest", "-m", "db", *sys.argv[1:]],
        cwd=Path(__file__).resolve().parents[1],
    )
)