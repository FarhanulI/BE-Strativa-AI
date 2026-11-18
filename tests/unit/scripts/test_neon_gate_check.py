"""scripts/neon_gate_check.py with fake connections and settings. No network, no database."""

from __future__ import annotations

import asyncio
import importlib.util
import json
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

from app.core.config import AppEnvironment, Settings
from app.db_migrations.guard import LOCAL_TEST_DB_MARKER, NEON_TEST_MARKER

ROOT = Path(__file__).resolve().parents[3]
PASSWORD = "gate-pw-distinct-7731"
HOST = "ep-gate-host-123-pooler.region.aws.neon.tech"
URL = f"postgresql://gate_user:{PASSWORD}@{HOST}/neondb"
BASE_KEYS = {
    "mode",
    "label_ok",
    "marker_ok",
    "pooled_DATABASE_URL",
    "pooled_DATABASE_URL_DIRECT",
    "test_connection_variable",
    "server_major_version",
    "extensions",
    "audit_trigger_enabled",
}


def load() -> ModuleType:
    path = ROOT / "scripts" / "neon_gate_check.py"
    spec = importlib.util.spec_from_file_location("neon_gate_check", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


gate = load()


class _Result:
    def __init__(self, value: Any = None, rows: list[Any] | None = None) -> None:
        self._value = value
        self._rows = rows or []

    def one(self) -> Any:
        return self._value

    def scalar(self) -> Any:
        return self._value

    def scalars(self) -> _Result:
        return self

    def all(self) -> list[Any]:
        return self._rows


class FakeConnection:
    def __init__(self, marker: str | None = NEON_TEST_MARKER, trigger: str | None = "O") -> None:
        self.marker = marker
        self.trigger = trigger
        self.statements: list[str] = []

    async def execute(self, statement: Any) -> _Result:
        sql = str(statement)
        self.statements.append(sql)
        if "current_database()" in sql:
            return _Result(("neondb", self.marker))
        if "server_version_num" in sql:
            return _Result("170002")
        if "pg_extension" in sql:
            return _Result(rows=["pgcrypto", "plpgsql", "vector"])
        if "pg_trigger" in sql:
            return _Result(self.trigger)
        if "count(*)" in sql:
            return _Result(7)
        raise AssertionError(sql)


def settings(**overrides: Any) -> Settings:
    values: dict[str, Any] = {
        "_env_file": None,
        "app_env": AppEnvironment.TEST,
        "neon_branch_name": "test",
        "database_url": URL,
        "database_url_direct": URL,
    }
    values.update(overrides)
    return Settings(**values)


def collect(connection: FakeConnection, *, counts: bool = False) -> dict[str, Any]:
    return asyncio.run(gate.collect(settings(), connection, counts=counts))


def test_report_has_exactly_the_documented_keys_and_values() -> None:
    report = collect(FakeConnection())
    assert set(report) == BASE_KEYS
    assert report == {
        "mode": "neon",
        "label_ok": True,
        "marker_ok": True,
        "pooled_DATABASE_URL": True,
        "pooled_DATABASE_URL_DIRECT": True,
        "test_connection_variable": "DATABASE_URL_DIRECT",
        "server_major_version": 17,
        "extensions": ["pgcrypto", "plpgsql", "vector"],
        "audit_trigger_enabled": True,
    }


def test_pooled_flags_are_reported_per_variable_name() -> None:
    direct = f"postgresql://u:{PASSWORD}@ep-direct-1.region.aws.neon.tech/neondb"
    report = asyncio.run(
        gate.collect(settings(database_url_direct=direct), FakeConnection(), counts=False)
    )
    assert report["pooled_DATABASE_URL"] is True
    assert report["pooled_DATABASE_URL_DIRECT"] is False
    assert "pooled_DATABASE_URL_UNPOOLED" not in report


def test_unpooled_variable_gets_its_own_flag() -> None:
    direct = f"postgresql://u:{PASSWORD}@ep-direct-1.region.aws.neon.tech/neondb"
    report = asyncio.run(
        gate.collect(
            settings(database_url_direct=None, database_url_unpooled=direct),
            FakeConnection(),
            counts=False,
        )
    )
    assert report["pooled_DATABASE_URL_UNPOOLED"] is False
    assert report["pooled_DATABASE_URL_DIRECT"] is False
    assert set(report) - BASE_KEYS == {"pooled_DATABASE_URL_UNPOOLED"}


def test_test_connection_variable_matches_what_the_test_setup_reads() -> None:
    sources = [
        (ROOT / name).read_text(encoding="utf-8")
        for name in ("tests/conftest.py", "tests/helpers/database_setup.py")
    ]
    assert "require_database_url(direct=True)" in sources[0]
    assert gate.TEST_CONNECTION_VARIABLE == "DATABASE_URL_DIRECT"


def test_disabled_or_missing_trigger_reports_false() -> None:
    assert collect(FakeConnection(trigger="D"))["audit_trigger_enabled"] is False
    assert collect(FakeConnection(trigger=None))["audit_trigger_enabled"] is False


def test_counts_flag_adds_only_integer_counts_with_plain_selects() -> None:
    connection = FakeConnection()
    report = collect(connection, counts=True)
    assert set(report) == BASE_KEYS | {"counts"}
    assert list(report["counts"]) == list(gate.COUNT_TABLES)
    assert all(type(value) is int for value in report["counts"].values())
    selects = [s for s in connection.statements if "count(*)" in s]
    assert selects == [f"SELECT count(*) FROM {t}" for t in gate.COUNT_TABLES]


def test_without_counts_flag_no_count_is_issued() -> None:
    connection = FakeConnection()
    collect(connection)
    assert not any("count(*)" in s for s in connection.statements)


@pytest.mark.parametrize("marker", [None, "", LOCAL_TEST_DB_MARKER, "NEON-TEST-BRANCH-V1"])
def test_bad_marker_reports_false_and_runs_no_further_query(marker: str | None) -> None:
    connection = FakeConnection(marker=marker)
    report = collect(connection, counts=True)
    assert report == {"mode": "neon", "label_ok": True, "marker_ok": False}
    assert len(connection.statements) == 1


def test_statements_are_read_only() -> None:
    connection = FakeConnection()
    collect(connection, counts=True)
    for sql in connection.statements:
        assert sql.lstrip().upper().startswith(("SELECT", "SHOW")), sql


def test_static_refusal_reports_label_false_without_connecting(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def boom(*args: Any, **kwargs: Any) -> None:
        raise AssertionError("must not connect")

    monkeypatch.setattr(gate, "build_async_engine", boom)
    bad = f"postgresql://u:{PASSWORD}@localhost/neondb"
    report = asyncio.run(
        gate.run(settings(database_url=bad, database_url_direct=bad), counts=False)
    )
    assert report == {"mode": "neon", "label_ok": False, "marker_ok": False}


def _patch_run(monkeypatch: pytest.MonkeyPatch, report: dict[str, Any] | Exception) -> None:
    async def fake(settings_: Settings, *, counts: bool) -> dict[str, Any]:
        if isinstance(report, Exception):
            raise report
        return report

    monkeypatch.setattr(gate, "run", fake)
    monkeypatch.setattr(gate, "Settings", lambda: settings())


@pytest.mark.parametrize(
    ("label_ok", "marker_ok", "code"),
    [(True, True, 0), (True, False, 1), (False, True, 1), (False, False, 1)],
)
def test_exit_code_zero_only_when_both_booleans_are_true(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    label_ok: bool,
    marker_ok: bool,
    code: int,
) -> None:
    _patch_run(monkeypatch, {"mode": "neon", "label_ok": label_ok, "marker_ok": marker_ok})
    assert gate.main([]) == code
    out = capsys.readouterr().out
    assert json.loads(out) == {"mode": "neon", "label_ok": label_ok, "marker_ok": marker_ok}


def test_main_output_never_contains_url_host_or_password(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    async def fake(settings_: Settings, *, counts: bool) -> dict[str, Any]:
        return await gate.collect(settings_, FakeConnection(), counts=counts)

    monkeypatch.setattr(gate, "run", fake)
    monkeypatch.setattr(gate, "Settings", lambda: settings())
    assert gate.main(["--counts"]) == 0
    captured = capsys.readouterr()
    text = (captured.out + captured.err).lower()
    for forbidden in (PASSWORD.lower(), HOST, "gate_user", "postgresql://", "neon.tech", "token"):
        assert forbidden not in text


def test_errors_print_only_class_name_and_fixed_message(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _patch_run(monkeypatch, RuntimeError(f"{URL} {PASSWORD}"))
    assert gate.main([]) == 3
    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err.strip() == "RuntimeError: neon_gate_check failed"


LOCAL = "postgresql://u:pw@127.0.0.1:55432/strativa_test"


@pytest.mark.parametrize(
    "overrides",
    [
        {
            "test_db_mode": "local",
            "database_url": LOCAL,
            "database_url_direct": LOCAL,
            "neon_branch_name": None,
        },
        {"app_env": AppEnvironment.DEV, "neon_branch_name": "dev"},
        {"app_env": AppEnvironment.PROD, "neon_branch_name": "production"},
    ],
)
def test_refuses_local_mode_and_dev_prod(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    overrides: dict[str, Any],
) -> None:
    async def boom(*args: Any, **kwargs: Any) -> None:
        raise AssertionError("must not run")

    monkeypatch.setattr(gate, "run", boom)
    monkeypatch.setattr(gate, "Settings", lambda: settings(**overrides))
    assert gate.main([]) == 2
    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err.strip() == gate.NOT_NEON_MESSAGE


def test_no_public_name_contains_token() -> None:
    for name in dir(gate):
        if not name.startswith("_"):
            assert "token" not in name.lower(), name
