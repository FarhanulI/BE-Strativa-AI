from __future__ import annotations

import asyncio
from typing import Any

from sqlalchemy import text
from sqlalchemy.pool import NullPool

from app.core import (
    AppEnvironment,
    ConfigurationError,
    Settings,
    parse_database_target,
    require_local_test_targets,
)
from app.db_migrations.engine import build_async_engine

LOCAL_TEST_DB_MARKER = "local-throwaway-v1"
NEON_TEST_MARKER = "neon-test-branch-v1"


def validate_test_database_target(settings: Settings) -> str:
    """Single gate for every destructive test-database operation.

    Returns the direct database URL once the selected mode's checks pass. Error messages are
    fixed strings and never include a URL, host or credential.
    """
    if settings.test_db_mode == "local":
        if settings.app_env != AppEnvironment.TEST:
            raise ConfigurationError("TEST_DB_MODE=local requires APP_ENV=test")
        if settings.neon_branch_name is not None:
            raise ConfigurationError("NEON_BRANCH_NAME must not be set in local test mode")
        require_local_test_targets(settings.configured_database_urls())
        return settings.require_database_url(direct=True)

    if settings.test_db_mode != "neon":
        raise ConfigurationError("TEST_DB_MODE must be neon or local")
    if settings.app_env != AppEnvironment.TEST or settings.neon_branch_name != "test":
        raise ConfigurationError("DB tests require APP_ENV=test and NEON_BRANCH_NAME=test")
    _refuse_local_host_in_neon_mode(settings)
    return settings.require_database_url(direct=True)


def validate_migration_target(settings: Settings, *, allow_prod: bool = False) -> str:
    if settings.test_db_mode == "local":
        return validate_test_database_target(settings)
    expected_branch = {
        AppEnvironment.DEV: "dev",
        AppEnvironment.TEST: "test",
        AppEnvironment.PROD: "production",
    }.get(settings.app_env)
    if expected_branch is None or settings.neon_branch_name != expected_branch:
        raise ConfigurationError("NEON_BRANCH_NAME must match APP_ENV for migrations")
    if settings.app_env == AppEnvironment.PROD and not allow_prod:
        raise ConfigurationError("Production migrations require --allow-prod")
    if settings.app_env == AppEnvironment.TEST:
        _refuse_local_host_in_neon_mode(settings)
    return settings.require_database_url(direct=True)


def _refuse_local_host_in_neon_mode(settings: Settings) -> None:
    for url in settings.configured_database_urls():
        if parse_database_target(url).is_local:
            raise ConfigurationError(
                "Neon test mode refuses a loopback or unix-socket host; "
                "set TEST_DB_MODE=local to use a local database"
            )


async def _read_identity(settings: Settings, connection: Any) -> tuple[str, Any, Any]:
    expected = parse_database_target(settings.require_database_url(direct=True)).database
    result = await connection.execute(
        text("SELECT current_database(), current_setting('app.test_db_marker', true)")
    )
    database, marker = result.one()
    return expected, database, marker


async def confirm_local_test_database(settings: Settings, connection: Any) -> None:
    """Live server-side confirmation, run once before migrations in local mode.

    Positive evidence that the server is the throwaway test database: the connected database
    name matches the configured one, and the database-level marker set by the container's init
    script is present with the fixed value. No address-based decision is made.
    """
    expected, database, marker = await _read_identity(settings, connection)
    if database != expected:
        raise ConfigurationError("Connected database does not match the configured test database")
    if marker != LOCAL_TEST_DB_MARKER:
        raise ConfigurationError("Connected database lacks the local test database marker")


async def confirm_neon_test_database(settings: Settings, connection: Any) -> None:
    """Live server-side confirmation, run once before migrations in Neon mode.

    Same shape as the local check with the Neon marker, which the owner sets on the dedicated
    test branch. No host pattern is consulted; the marker is the positive evidence. The local
    marker is refused here, just as the Neon marker is refused in local mode.
    """
    expected, database, marker = await _read_identity(settings, connection)
    if database != expected:
        raise ConfigurationError("Connected database does not match the configured test database")
    if marker != NEON_TEST_MARKER:
        raise ConfigurationError("Connected database lacks the Neon test branch marker")


async def _verify_test_database(settings: Settings, *, neon: bool) -> None:
    engine = build_async_engine(
        settings.require_database_url(direct=True),
        pooled=False,
        engine_options={"poolclass": NullPool},
    )
    try:
        async with engine.connect() as connection:
            if neon:
                await confirm_neon_test_database(settings, connection)
            else:
                await confirm_local_test_database(settings, connection)
    except ConfigurationError:
        raise
    except Exception:
        raise ConfigurationError("Could not verify the test database") from None
    finally:
        await engine.dispose()


def verify_test_database(settings: Settings) -> None:
    """Run the live check for the selected mode after the static guard has passed.

    Local mode checks the local marker; Neon mode with APP_ENV=test checks the Neon marker. In
    Neon mode for any other APP_ENV nothing runs and nothing connects (the static rules govern
    dev and prod). Serves both modes.
    """
    if settings.test_db_mode == "local":
        validate_test_database_target(settings)
        asyncio.run(_verify_test_database(settings, neon=False))
    elif settings.test_db_mode == "neon" and settings.app_env == AppEnvironment.TEST:
        validate_test_database_target(settings)
        asyncio.run(_verify_test_database(settings, neon=True))
