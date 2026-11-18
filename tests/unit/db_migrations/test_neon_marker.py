"""Neon-mode live marker check and teardown-helper marker selection. Fake connections only."""

from __future__ import annotations

import asyncio
import inspect
from typing import Any

import pytest

import app.db_migrations as db_migrations
import app.db_migrations.guard as guard_module
from app.core.config import AppEnvironment, ConfigurationError, Settings
from app.db_migrations.guard import (
    LOCAL_TEST_DB_MARKER,
    NEON_TEST_MARKER,
    confirm_local_test_database,
    confirm_neon_test_database,
    verify_test_database,
)
from tests.helpers import audit_teardown
from tests.helpers.audit_teardown import (
    NOT_ENABLED_MESSAGE,
    REFUSED_MESSAGE,
    AuditTeardownError,
    delete_audit_rows,
)
from tests.unit.db_migrations.test_local_mode import (
    NEON_URL,
    PASSWORD,
    FakeConnection,
    local_settings,
    neon_test_settings,
)

BAD_MARKERS = [None, "", "NEON-TEST-BRANCH-V1", "neon-test-branch-v1 ", "other-value"]
FORBIDDEN = (
    PASSWORD.lower(),
    "postgresql://",
    "ep-example-123",
    "neon.tech",
    "token",
    "other-value",
)


def assert_fixed(error: BaseException) -> None:
    message = str(error).lower()
    for forbidden in FORBIDDEN:
        assert forbidden not in message


def test_markers_are_the_documented_constants() -> None:
    assert NEON_TEST_MARKER == "neon-test-branch-v1"
    assert LOCAL_TEST_DB_MARKER == "local-throwaway-v1"


def test_neon_marker_accepted_in_neon_mode() -> None:
    connection = FakeConnection(("neondb", NEON_TEST_MARKER))
    asyncio.run(confirm_neon_test_database(neon_test_settings(), connection))
    assert len(connection.statements) == 1
    assert "current_setting('app.test_db_marker', true)" in connection.statements[0]


def test_local_marker_refused_in_neon_mode() -> None:
    connection = FakeConnection(("neondb", LOCAL_TEST_DB_MARKER))
    with pytest.raises(ConfigurationError, match="Neon test branch marker") as raised:
        asyncio.run(confirm_neon_test_database(neon_test_settings(), connection))
    assert_fixed(raised.value)


def test_neon_marker_refused_in_local_mode() -> None:
    connection = FakeConnection(("strativa_test", NEON_TEST_MARKER))
    with pytest.raises(ConfigurationError, match="local test database marker") as raised:
        asyncio.run(confirm_local_test_database(local_settings(), connection))
    assert_fixed(raised.value)


@pytest.mark.parametrize("marker", BAD_MARKERS)
def test_bad_markers_refused_in_neon_mode(marker: str | None) -> None:
    connection = FakeConnection(("neondb", marker))
    with pytest.raises(ConfigurationError, match="marker") as raised:
        asyncio.run(confirm_neon_test_database(neon_test_settings(), connection))
    assert_fixed(raised.value)


@pytest.mark.parametrize("marker", BAD_MARKERS)
def test_bad_markers_refused_in_local_mode(marker: str | None) -> None:
    connection = FakeConnection(("strativa_test", marker))
    with pytest.raises(ConfigurationError, match="marker") as raised:
        asyncio.run(confirm_local_test_database(local_settings(), connection))
    assert_fixed(raised.value)


def test_database_name_mismatch_refused_in_neon_mode() -> None:
    connection = FakeConnection(("production", NEON_TEST_MARKER))
    with pytest.raises(ConfigurationError, match="does not match") as raised:
        asyncio.run(confirm_neon_test_database(neon_test_settings(), connection))
    assert_fixed(raised.value)


def test_neon_live_check_has_no_host_pattern_rule() -> None:
    source = inspect.getsource(guard_module)
    assert "neon.tech" not in source
    assert "-pooler" not in source


def _spy(monkeypatch: pytest.MonkeyPatch) -> list[bool]:
    calls: list[bool] = []

    async def fake(settings: Settings, *, neon: bool) -> None:
        calls.append(neon)

    monkeypatch.setattr(guard_module, "_verify_test_database", fake)
    return calls


def test_live_check_runs_in_neon_mode_for_test_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = _spy(monkeypatch)
    verify_test_database(neon_test_settings())
    assert calls == [True]


def test_live_check_runs_in_local_mode(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = _spy(monkeypatch)
    verify_test_database(local_settings())
    assert calls == [False]


@pytest.mark.parametrize(
    ("environment", "label"),
    [(AppEnvironment.DEV, "dev"), (AppEnvironment.PROD, "production")],
)
def test_live_check_unreachable_for_dev_and_prod(
    monkeypatch: pytest.MonkeyPatch, environment: AppEnvironment, label: str
) -> None:
    calls = _spy(monkeypatch)
    settings = Settings(
        _env_file=None,
        app_env=environment,
        neon_branch_name=label,
        database_url=NEON_URL,
        database_url_direct=NEON_URL,
    )
    verify_test_database(settings)
    assert calls == []


def test_live_check_not_run_when_static_rules_refuse(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = _spy(monkeypatch)
    url = f"postgresql://owner:{PASSWORD}@localhost/neondb"
    settings = neon_test_settings(database_url=url, database_url_direct=url)
    with pytest.raises(ConfigurationError, match="loopback"):
        verify_test_database(settings)
    assert calls == []


def test_no_public_name_contains_token() -> None:
    assert db_migrations.confirm_neon_test_database is confirm_neon_test_database
    for module in (guard_module, audit_teardown, db_migrations):
        for name in dir(module):
            if not name.startswith("_"):
                assert "token" not in name.lower(), name


class _Result:
    def __init__(self, value: object) -> None:
        self._value = value

    def scalar(self) -> object:
        return self._value

    def scalar_one_or_none(self) -> object:
        return self._value


class _Session:
    def __init__(self, marker: object, trigger: object = "O", fail_delete: bool = False) -> None:
        self.marker = marker
        self.trigger = trigger
        self.fail_delete = fail_delete
        self.statements: list[str] = []

    async def execute(self, statement: Any, params: Any = None) -> _Result:
        sql = str(statement)
        self.statements.append(sql)
        if "current_setting" in sql:
            return _Result(self.marker)
        if "pg_trigger" in sql:
            return _Result(self.trigger)
        if self.fail_delete and sql.startswith("DELETE"):
            raise RuntimeError("boom")
        return _Result(None)


def _teardown(session: _Session) -> None:
    asyncio.run(delete_audit_rows(session, resource_type="ai_budget", resource_ids=["x"]))


@pytest.mark.parametrize(
    ("mode", "marker"), [("local", LOCAL_TEST_DB_MARKER), ("neon", NEON_TEST_MARKER)]
)
def test_teardown_accepts_the_marker_of_the_active_mode(
    monkeypatch: pytest.MonkeyPatch, mode: str, marker: str
) -> None:
    monkeypatch.setenv("TEST_DB_MODE", mode)
    session = _Session(marker)
    _teardown(session)
    assert any("DISABLE TRIGGER" in sql for sql in session.statements)
    assert "pg_trigger" in session.statements[-1]


def test_teardown_unset_mode_means_neon(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("TEST_DB_MODE", raising=False)
    _teardown(_Session(NEON_TEST_MARKER))
    with pytest.raises(AuditTeardownError):
        _teardown(_Session(LOCAL_TEST_DB_MARKER))


@pytest.mark.parametrize(
    ("mode", "wrong"),
    [("local", NEON_TEST_MARKER), ("neon", LOCAL_TEST_DB_MARKER), ("local", None), ("neon", "")],
)
def test_teardown_refuses_the_wrong_marker(
    monkeypatch: pytest.MonkeyPatch, mode: str, wrong: str | None
) -> None:
    monkeypatch.setenv("TEST_DB_MODE", mode)
    session = _Session(wrong)
    with pytest.raises(AuditTeardownError) as raised:
        _teardown(session)
    assert str(raised.value) == REFUSED_MESSAGE
    assert not any("DISABLE TRIGGER" in sql or "DELETE" in sql for sql in session.statements)


def test_teardown_unknown_mode_refused(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TEST_DB_MODE", "remote")
    with pytest.raises(AuditTeardownError):
        _teardown(_Session(NEON_TEST_MARKER))


@pytest.mark.parametrize("trigger", ["D", None])
def test_teardown_verifies_the_trigger_is_enabled_afterwards(
    monkeypatch: pytest.MonkeyPatch, trigger: str | None
) -> None:
    monkeypatch.setenv("TEST_DB_MODE", "neon")
    session = _Session(NEON_TEST_MARKER, trigger=trigger)
    with pytest.raises(AuditTeardownError) as raised:
        _teardown(session)
    assert str(raised.value) == NOT_ENABLED_MESSAGE
    assert any("ENABLE TRIGGER" in sql for sql in session.statements)


def test_teardown_failure_propagates_so_the_caller_rolls_back_as_a_whole(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("TEST_DB_MODE", "neon")
    session = _Session(NEON_TEST_MARKER, fail_delete=True)
    with pytest.raises(RuntimeError):
        _teardown(session)
    # The helper opens no transaction of its own and swallows nothing: the caller's single
    # transaction rolls back, taking the DISABLE TRIGGER with it.
    assert not any(s.startswith(("COMMIT", "BEGIN")) for s in session.statements)
    assert not any("ENABLE TRIGGER" in sql for sql in session.statements)
