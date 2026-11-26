"""Database test for the audit-trigger teardown helper (tests/helpers/audit_teardown.py)."""

from __future__ import annotations

from typing import Any

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.core import Settings
from app.db_migrations.engine import build_async_engine
from tests.helpers.audit_teardown import (
    NOT_ENABLED_MESSAGE,
    REFUSED_MESSAGE,
    AuditTeardownError,
    active_marker,
    current_trigger_state,
    delete_audit_rows,
)

pytestmark = pytest.mark.db


class _Result:
    def __init__(self, value: object) -> None:
        self._value = value

    def scalar(self) -> object:
        return self._value

    def scalar_one_or_none(self) -> object:
        return self._value


class _FakeSession:
    """Answers the marker query with ``marker`` and the pg_trigger query with ``trigger``."""

    def __init__(self, marker: object, trigger: object = "O") -> None:
        self.marker = marker
        self.trigger = trigger
        self.statements: list[str] = []

    async def execute(self, statement: Any, params: Any = None) -> _Result:
        sql = str(statement)
        self.statements.append(sql)
        if "current_setting" in sql:
            return _Result(self.marker)
        if "pg_trigger" in sql:
            return _Result(self.trigger)
        return _Result(None)


async def test_trigger_is_enabled_after_the_teardown_helper_ran(
    migrated_test_schema: Settings,
) -> None:
    engine = build_async_engine(
        migrated_test_schema.require_database_url(direct=True), pooled=False
    )
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    try:
        async with sessions() as session, session.begin():
            await delete_audit_rows(
                session,
                resource_type="ai_budget",
                resource_ids=["00000000-0000-0000-0000-000000000000"],
            )
        async with sessions() as session, session.begin():
            state = await current_trigger_state(session)
        assert state is not None
        assert state != "D"
    finally:
        await engine.dispose()


@pytest.mark.parametrize("marker", [None, "", "not-the-marker"])
async def test_helper_refuses_on_a_database_without_the_marker(marker: object) -> None:
    fake = _FakeSession(marker)
    with pytest.raises(AuditTeardownError) as raised:
        await delete_audit_rows(fake, resource_type="ai_budget", resource_ids=["x"])
    assert str(raised.value) == REFUSED_MESSAGE
    assert not any("DISABLE TRIGGER" in sql or "DELETE" in sql for sql in fake.statements)


async def test_helper_fails_when_the_trigger_is_still_disabled_afterwards() -> None:
    fake = _FakeSession(active_marker(), trigger="D")
    with pytest.raises(AuditTeardownError) as raised:
        await delete_audit_rows(fake, resource_type="ai_budget", resource_ids=["x"])
    assert str(raised.value) == NOT_ENABLED_MESSAGE
