"""Teardown helper for audit rows created by database tests.

``audit_log`` is append-only by the row trigger ``audit_log_immutable``. A test that committed audit
rows can only remove them by disabling that one trigger for the length of its own transaction. That
is destructive, so the helper:

* refuses unless the connected database carries the local throwaway marker (the same constant the
  migration guard checks), with a fixed message,
* re-enables the trigger and then reads ``pg_trigger`` to verify that it is not disabled.

Both failures raise ``AuditTeardownError``. The caller runs the helper inside a transaction, so a
failure rolls the whole transaction back and the trigger is never left disabled.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from sqlalchemy import text

from app.db_migrations.guard import LOCAL_TEST_DB_MARKER

TRIGGER_NAME = "audit_log_immutable"
REFUSED_MESSAGE = "audit teardown refused: database lacks the local test database marker"
NOT_ENABLED_MESSAGE = "audit teardown failed: the audit_log trigger is not enabled afterwards"


class AuditTeardownError(RuntimeError):
    """Fixed message only: no ids, values or connection details."""


async def current_trigger_state(session: Any) -> str | None:
    """``pg_trigger.tgenabled`` for the audit trigger: 'D' disabled, anything else enabled."""
    result = await session.execute(
        text(
            "SELECT tgenabled FROM pg_trigger "
            "WHERE tgname = :name AND tgrelid = 'audit_log'::regclass"
        ),
        {"name": TRIGGER_NAME},
    )
    value = result.scalar_one_or_none()
    return None if value is None else str(value)


async def delete_audit_rows(
    session: Any, *, resource_type: str, resource_ids: Sequence[str]
) -> None:
    """Delete audit rows of one resource type by id, inside the caller's transaction."""
    marker = (
        await session.execute(text("SELECT current_setting('app.test_db_marker', true)"))
    ).scalar()
    if marker != LOCAL_TEST_DB_MARKER:
        raise AuditTeardownError(REFUSED_MESSAGE)
    await session.execute(text(f"ALTER TABLE audit_log DISABLE TRIGGER {TRIGGER_NAME}"))
    await session.execute(
        text(
            "DELETE FROM audit_log WHERE resource_type = :rt "
            "AND resource_id = ANY(CAST(:ids AS text[]))"
        ),
        {"rt": resource_type, "ids": list(resource_ids)},
    )
    await session.execute(text(f"ALTER TABLE audit_log ENABLE TRIGGER {TRIGGER_NAME}"))
    state = await current_trigger_state(session)
    if state is None or state == "D":
        raise AuditTeardownError(NOT_ENABLED_MESSAGE)
