from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

import pytest

from app.core.config import AppEnvironment, ConfigurationError, Settings
from app.db_migrations.guard import (
    confirm_local_test_database,
    validate_migration_target,
    validate_test_database_target,
)

PASSWORD = "s3cr3t-pw-marker"
NEON_URL = f"postgresql://owner:{PASSWORD}@ep-example-123.region.aws.neon.tech/neondb"


def local_url(host: str = "127.0.0.1", database: str = "strativa_test") -> str:
    return f"postgresql://app_test:{PASSWORD}@{host}:55432/{database}"


def local_settings(**overrides: Any) -> Settings:
    values: dict[str, Any] = {
        "_env_file": None,
        "app_env": AppEnvironment.TEST,
        "test_db_mode": "local",
        "database_url": local_url(),
        "database_url_direct": local_url(),
    }
    values.update(overrides)
    return Settings(**values)


def neon_test_settings(**overrides: Any) -> Settings:
    values: dict[str, Any] = {
        "_env_file": None,
        "app_env": AppEnvironment.TEST,
        "neon_branch_name": "test",
        "database_url": NEON_URL,
        "database_url_direct": NEON_URL,
    }
    values.update(overrides)
    return Settings(**values)


def assert_no_leak(error: BaseException) -> None:
    message = str(error).lower()
    for forbidden in (PASSWORD.lower(), "postgresql://", "127.0.0.1", "neon.tech", "token"):
        assert forbidden not in message


@pytest.mark.parametrize("host", ["localhost", "127.0.0.1", "[::1]"])
def test_local_mode_accepts_loopback_test_databases(host: str) -> None:
    url = local_url(host)
    settings = local_settings(database_url=url, database_url_direct=url)
    assert validate_test_database_target(settings) == url
    assert validate_migration_target(settings) == url


def test_local_mode_accepts_unix_socket() -> None:
    url = f"postgresql://app_test:{PASSWORD}@/strativa_test?host=/var/run/postgresql"
    settings = local_settings(database_url=url, database_url_direct=url)
    assert validate_test_database_target(settings) == url


@pytest.mark.parametrize(
    "url",
    [
        f"postgresql://u:{PASSWORD}@db.example.com/strativa_test",
        NEON_URL,
        f"postgresql://u:{PASSWORD}@127.0.0.1/strativa",
        f"postgresql://u:{PASSWORD}@127.0.0.1/strativa_test_backup",
        f"postgresql://u:{PASSWORD}@127.0.0.1/Strativa_TEST",
        f"postgresql://u:{PASSWORD}@127.0.0.1/strativa_test?host=db.example.com",
        f"postgresql://u:{PASSWORD}@127.0.0.1/strativa_test?hostaddr=10.0.0.5",
        f"postgresql://u:{PASSWORD}@/strativa_test",
        f"postgresql://u:{PASSWORD}@127.0.0.1,db.example.com/strativa_test",
        f"mysql://u:{PASSWORD}@127.0.0.1/strativa_test",
        f"postgresql://u:{PASSWORD}@[::1/strativa_test",
    ],
)
def test_local_mode_refuses_non_local_or_non_test_targets(url: str) -> None:
    with pytest.raises(ConfigurationError) as raised:
        local_settings(database_url=url, database_url_direct=url)
    assert_no_leak(raised.value)


def test_guard_refuses_local_mode_without_database_url() -> None:
    settings = Settings(_env_file=None, app_env=AppEnvironment.TEST, test_db_mode="local")
    with pytest.raises(ConfigurationError, match="requires a database URL"):
        validate_test_database_target(settings)


def test_local_mode_refuses_mismatched_pooled_and_direct_urls() -> None:
    with pytest.raises(ConfigurationError, match="same database") as raised:
        local_settings(
            database_url=local_url(database="other_test"),
            database_url_direct=local_url(),
        )
    assert_no_leak(raised.value)


@pytest.mark.parametrize(
    "environment", [AppEnvironment.DEV, AppEnvironment.PROD, AppEnvironment.STAGING]
)
def test_local_mode_refused_outside_test_environment(environment: AppEnvironment) -> None:
    with pytest.raises(ConfigurationError, match="APP_ENV=test"):
        local_settings(app_env=environment)


def test_local_mode_refuses_neon_branch_label() -> None:
    with pytest.raises(ConfigurationError, match="NEON_BRANCH_NAME"):
        local_settings(neon_branch_name="test")


@pytest.mark.parametrize("mode", ["LOCAL", "remote", "neon "])
def test_unknown_mode_is_refused(mode: str) -> None:
    with pytest.raises(ConfigurationError, match="TEST_DB_MODE"):
        Settings(_env_file=None, app_env=AppEnvironment.TEST, test_db_mode=mode)


def test_mode_must_come_from_process_environment(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.delenv("TEST_DB_MODE", raising=False)
    monkeypatch.setenv("APP_ENV", "test")
    (tmp_path / ".env").write_text("TEST_DB_MODE=local\n", encoding="utf-8")
    monkeypatch.setattr(Settings, "repository_root", staticmethod(lambda: tmp_path))
    with pytest.raises(ConfigurationError, match="TEST_DB_MODE"):
        Settings()


def test_local_mode_uses_docker_env_file_not_neon_file(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    for name in (
        "NEON_BRANCH_NAME",
        "DATABASE_URL",
        "DATABASE_URL_DIRECT",
        "DATABASE_URL_UNPOOLED",
        "LOG_LEVEL",
    ):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("TEST_DB_MODE", "local")
    monkeypatch.setenv("APP_ENV", "test")
    (tmp_path / ".env.test.local").write_text(
        "NEON_BRANCH_NAME=test\nLOG_LEVEL=ERROR\n", encoding="utf-8"
    )
    (tmp_path / ".env.test.docker.local").write_text(
        f"DATABASE_URL={local_url()}\nDATABASE_URL_DIRECT={local_url()}\nLOG_LEVEL=WARNING\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(Settings, "repository_root", staticmethod(lambda: tmp_path))
    settings = Settings()
    assert settings.log_level == "WARNING"
    assert settings.neon_branch_name is None
    assert validate_test_database_target(settings) == local_url()


def test_default_mode_is_neon_and_unchanged() -> None:
    settings = neon_test_settings()
    assert settings.test_db_mode == "neon"
    assert validate_test_database_target(settings) == NEON_URL
    assert validate_migration_target(settings) == NEON_URL


@pytest.mark.parametrize("label", ["dev", "production", None])
def test_neon_mode_refuses_wrong_labels(label: str | None) -> None:
    settings = Settings(_env_file=None, app_env=AppEnvironment.TEST)
    settings.neon_branch_name = label
    with pytest.raises(ConfigurationError, match="NEON_BRANCH_NAME"):
        validate_test_database_target(settings)


def test_neon_mode_still_rejects_mismatched_label_with_url() -> None:
    with pytest.raises(ConfigurationError, match="NEON_BRANCH_NAME"):
        neon_test_settings(neon_branch_name="dev")
    with pytest.raises(ConfigurationError, match="NEON_BRANCH_NAME"):
        neon_test_settings(neon_branch_name="production")


def test_neon_mode_refuses_dev_and_prod_environments() -> None:
    dev = Settings(_env_file=None, app_env=AppEnvironment.DEV, neon_branch_name="dev")
    prod = Settings(_env_file=None, app_env=AppEnvironment.PROD, neon_branch_name="production")
    for settings in (dev, prod):
        with pytest.raises(ConfigurationError, match="APP_ENV=test"):
            validate_test_database_target(settings)


@pytest.mark.parametrize("host", ["localhost", "127.0.0.1", "[::1]"])
def test_neon_mode_refuses_loopback_hosts(host: str) -> None:
    url = f"postgresql://owner:{PASSWORD}@{host}/neondb"
    settings = neon_test_settings(database_url=url, database_url_direct=url)
    for guard in (validate_test_database_target, validate_migration_target):
        with pytest.raises(ConfigurationError, match="loopback") as raised:
            guard(settings)
        assert_no_leak(raised.value)


def test_neon_mode_refuses_unix_socket() -> None:
    url = f"postgresql://owner:{PASSWORD}@/neondb?host=/var/run/postgresql"
    settings = neon_test_settings(database_url=url, database_url_direct=url)
    with pytest.raises(ConfigurationError, match="loopback"):
        validate_test_database_target(settings)


def test_dev_migration_target_is_not_subject_to_the_loopback_rule() -> None:
    url = "postgresql://dev@localhost/app"
    dev = Settings(
        _env_file=None,
        app_env=AppEnvironment.DEV,
        neon_branch_name="dev",
        database_url=url,
        database_url_direct=url,
    )
    assert validate_migration_target(dev) == url


class FakeResult:
    def __init__(self, row: tuple[Any, Any]) -> None:
        self._row = row

    def one(self) -> tuple[Any, Any]:
        return self._row


class FakeConnection:
    def __init__(self, row: tuple[Any, Any]) -> None:
        self.row = row
        self.statements: list[str] = []

    async def execute(self, statement: Any) -> FakeResult:
        self.statements.append(str(statement))
        return FakeResult(self.row)


@pytest.mark.parametrize("address", [None, "127.0.0.1", "::1"])
def test_live_check_accepts_loopback_or_socket(address: str | None) -> None:
    connection = FakeConnection(("strativa_test", address))
    asyncio.run(confirm_local_test_database(local_settings(), connection))
    assert len(connection.statements) == 1


@pytest.mark.parametrize(
    ("row", "fragment"),
    [
        (("production", "127.0.0.1"), "database"),
        (("strativa_test", "10.1.2.3"), "loopback"),
        (("strativa_test", "not-an-ip"), "loopback"),
    ],
)
def test_live_check_refusals_use_fixed_messages(row: tuple[str, str], fragment: str) -> None:
    connection = FakeConnection(row)
    with pytest.raises(ConfigurationError, match=fragment) as raised:
        asyncio.run(confirm_local_test_database(local_settings(), connection))
    assert_no_leak(raised.value)
    assert "10.1.2.3" not in str(raised.value)
