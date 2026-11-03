from __future__ import annotations

import asyncio
import ipaddress
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


def _is_loopback_address(address: str) -> bool:
    try:
        return ipaddress.ip_address(address).is_loopback
    except ValueError:
        return False


async def confirm_local_test_database(settings: Settings, connection: Any) -> None:
    """Live server-side confirmation, run once before migrations in local mode."""
    expected = parse_database_target(settings.require_database_url(direct=True)).database
    result = await connection.execute(
        text("SELECT current_database(), host(inet_server_addr())")
    )
    database, address = result.one()
    if database != expected:
        raise ConfigurationError("Connected database does not match the configured test database")
    if address is not None and not _is_loopback_address(address):
        raise ConfigurationError("Connected server is not a loopback or unix-socket endpoint")


async def _verify_local_test_database(settings: Settings) -> None:
    engine = build_async_engine(
        settings.require_database_url(direct=True),
        pooled=False,
        engine_options={"poolclass": NullPool},
    )
    try:
        async with engine.connect() as connection:
            await confirm_local_test_database(settings, connection)
    except ConfigurationError:
        raise
    except Exception:
        raise ConfigurationError("Could not verify the local test database") from None
    finally:
        await engine.dispose()


def verify_local_test_database(settings: Settings) -> None:
    """Run the live check in local mode after the static guard has passed. No-op in neon mode."""
    if settings.test_db_mode != "local":
        return
    validate_test_database_target(settings)
    asyncio.run(_verify_local_test_database(settings))
