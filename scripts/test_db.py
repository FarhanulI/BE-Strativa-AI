from __future__ import annotations

import subprocess
import sys
from pathlib import Path

from app.core.config import ConfigurationError, Settings
from app.db_migrations import validate_test_database_target

try:
    validate_test_database_target(Settings())
except ConfigurationError as error:
    raise SystemExit(str(error)) from None
raise SystemExit(
    subprocess.call(
        [sys.executable, "-m", "pytest", "-m", "db", *sys.argv[1:]],
        cwd=Path(__file__).resolve().parents[1],
    )
)
