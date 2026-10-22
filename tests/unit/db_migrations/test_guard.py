from __future__ import annotations

import pytest

from app.core.config import AppEnvironment, ConfigurationError, Settings
from app.db_migrations.guard import validate_migration_target


def test_migration_guard_rejects_missing_or_mismatched_branch() -> None:
    settings = Settings(_env_file=None, app_env=AppEnvironment.TEST)
    with pytest.raises(ConfigurationError, match="NEON_BRANCH_NAME"):
        validate_migration_target(settings)

    mismatched = Settings(
        _env_file=None,
        app_env=AppEnvironment.TEST,
        neon_branch_name="dev",
    )
    with pytest.raises(ConfigurationError, match="NEON_BRANCH_NAME"):
        validate_migration_target(mismatched)


def test_production_requires_explicit_opt_in_and_direct_url() -> None:
    settings = Settings(
        _env_file=None,
        app_env=AppEnvironment.PROD,
        neon_branch_name="production",
        database_url_direct="postgresql://migration-user@host/db",
    )
    with pytest.raises(ConfigurationError, match="--allow-prod"):
        validate_migration_target(settings)

    assert validate_migration_target(settings, allow_prod=True) == "postgresql://migration-user@host/db"