from __future__ import annotations

import runpy
import sys
from pathlib import Path
from typing import Any

import pytest
from alembic import command

import app.db_migrations as db_migrations
from tests.helpers import database_setup

ROOT = Path(__file__).resolve().parents[3]
LOCAL_URL = "postgresql://app_test:pw-marker@127.0.0.1:55432/strativa_test"
ENV_NAMES = (
    "APP_ENV",
    "NEON_BRANCH_NAME",
    "TEST_DB_MODE",
    "DATABASE_URL",
    "DATABASE_URL_DIRECT",
    "DATABASE_URL_UNPOOLED",
)


@pytest.fixture
def calls(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> list[str]:
    for name in ENV_NAMES:
        monkeypatch.delenv(name, raising=False)
    # No env files: Settings reads only the process environment from an empty root.
    monkeypatch.setattr(
        "app.core.config.Settings.repository_root", staticmethod(lambda: tmp_path)
    )
    recorded: list[str] = []
    monkeypatch.setattr(command, "upgrade", lambda *a, **k: recorded.append("upgrade"))
    monkeypatch.setattr(command, "downgrade", lambda *a, **k: recorded.append("downgrade"))
    monkeypatch.setattr(command, "check", lambda *a, **k: recorded.append("check"))
    monkeypatch.setattr(
        db_migrations,
        "verify_local_test_database",
        lambda settings: recorded.append("live-check"),
    )
    monkeypatch.setattr(
        database_setup,
        "verify_local_test_database",
        lambda settings: recorded.append("live-check"),
    )
    return recorded


def run_migrate(monkeypatch: pytest.MonkeyPatch, *arguments: str) -> None:
    monkeypatch.setattr(sys, "argv", ["migrate.py", *arguments])
    runpy.run_path(str(ROOT / "scripts" / "migrate.py"), run_name="__main__")


def local_env(monkeypatch: pytest.MonkeyPatch, url: str = LOCAL_URL) -> None:
    monkeypatch.setenv("APP_ENV", "test")
    monkeypatch.setenv("TEST_DB_MODE", "local")
    monkeypatch.setenv("DATABASE_URL", url)
    monkeypatch.setenv("DATABASE_URL_DIRECT", url)


@pytest.mark.parametrize("action", ["upgrade", "downgrade"])
def test_migrate_runs_guard_and_live_check_before_alembic(
    action: str, monkeypatch: pytest.MonkeyPatch, calls: list[str]
) -> None:
    local_env(monkeypatch)
    run_migrate(monkeypatch, action, "--require-test")
    assert calls == ["live-check", action]


@pytest.mark.parametrize("action", ["upgrade", "downgrade"])
def test_migrate_refuses_before_alembic_when_target_is_not_local(
    action: str, monkeypatch: pytest.MonkeyPatch, calls: list[str]
) -> None:
    local_env(monkeypatch, "postgresql://u:pw-marker@db.example.com/strativa_test")
    with pytest.raises(SystemExit) as raised:
        run_migrate(monkeypatch, action, "--require-test")
    assert calls == []
    assert "pw-marker" not in str(raised.value)
    assert "example.com" not in str(raised.value)


@pytest.mark.parametrize("action", ["upgrade", "downgrade"])
def test_migrate_require_test_refuses_dev_labels_before_alembic(
    action: str, monkeypatch: pytest.MonkeyPatch, calls: list[str]
) -> None:
    monkeypatch.setenv("APP_ENV", "dev")
    monkeypatch.setenv("NEON_BRANCH_NAME", "dev")
    monkeypatch.setenv("DATABASE_URL", "postgresql://u@db.example.com/app")
    monkeypatch.setenv("DATABASE_URL_DIRECT", "postgresql://u@db.example.com/app")
    with pytest.raises(SystemExit):
        run_migrate(monkeypatch, action, "--require-test")
    assert calls == []


def test_migrate_refuses_neon_test_mode_with_loopback_host(
    monkeypatch: pytest.MonkeyPatch, calls: list[str]
) -> None:
    monkeypatch.setenv("APP_ENV", "test")
    monkeypatch.setenv("NEON_BRANCH_NAME", "test")
    monkeypatch.setenv("DATABASE_URL", LOCAL_URL)
    monkeypatch.setenv("DATABASE_URL_DIRECT", LOCAL_URL)
    with pytest.raises(SystemExit, match="loopback"):
        run_migrate(monkeypatch, "downgrade", "--require-test")
    assert calls == []


def test_conftest_setup_guards_before_upgrade(
    monkeypatch: pytest.MonkeyPatch, calls: list[str]
) -> None:
    local_env(monkeypatch)
    from app.core.config import Settings

    database_setup.prepare_test_schema(Settings())
    assert calls == ["live-check", "upgrade", "check"]


def test_conftest_setup_never_migrates_a_refused_target(
    monkeypatch: pytest.MonkeyPatch, calls: list[str]
) -> None:
    local_env(monkeypatch, "postgresql://u:pw-marker@db.example.com/strativa_test")
    from app.core.config import ConfigurationError, Settings

    with pytest.raises(ConfigurationError):
        database_setup.prepare_test_schema(Settings())
    assert calls == []


def test_conftest_setup_refuses_unlabelled_neon_mode(
    monkeypatch: pytest.MonkeyPatch, calls: list[str]
) -> None:
    from app.core.config import AppEnvironment, ConfigurationError, Settings

    settings = Settings(_env_file=None, app_env=AppEnvironment.TEST)
    with pytest.raises(ConfigurationError, match="NEON_BRANCH_NAME"):
        database_setup.prepare_test_schema(settings)
    assert calls == []


def test_entry_points_do_not_duplicate_the_label_check() -> None:
    sources: dict[str, Any] = {
        name: (ROOT / name).read_text(encoding="utf-8")
        for name in (
            "scripts/test_db.py",
            "scripts/migrate.py",
            "scripts/verify_phase0.py",
            "tests/conftest.py",
        )
    }
    for name, source in sources.items():
        assert 'neon_branch_name != "test"' not in source, name
