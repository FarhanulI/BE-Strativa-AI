from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from app.core.clock import FakeClock
from app.db_migrations import validate_tenant_scope
from app.events_outbox import DemoPingRequested, ProcessedEvent, publish
from app.events_outbox.consumers import handle_once
from app.events_outbox.models import OutboxEvent
from app.observability_audit import AuditRecord, append_audit
from app.observability_audit.models import AuditLog

pytestmark = pytest.mark.db


@pytest.mark.asyncio
async def test_required_extensions_and_tenant_scope_metadata(db_session) -> None:
    extensions = await db_session.scalars(
        text("SELECT extname FROM pg_extension WHERE extname IN ('citext', 'pgcrypto', 'vector')")
    )
    assert set(extensions) == {"citext", "pgcrypto", "vector"}
    assert await db_session.scalar(
        text("SELECT 'Mixed@Example.test'::citext = 'mixed@example.test'")
    )
    assert isinstance(await db_session.scalar(text("SELECT gen_random_uuid()")), UUID)
    vector_columns = await db_session.scalar(
        text(
            "SELECT count(*) FROM information_schema.columns "
            "WHERE table_schema = current_schema() "
            "AND udt_name IN ('vector', 'halfvec', 'sparsevec')"
        )
    )
    assert vector_columns == 0
    assert OutboxEvent.__table__.info["tenant_scope"] == "global"
    assert ProcessedEvent.__table__.info["tenant_scope"] == "global"
    assert AuditLog.__table__.info["tenant_scope"] == "global"
    validate_tenant_scope()


@pytest.mark.asyncio
async def test_event_publication_rolls_back_with_caller_transaction(db_session) -> None:
    event = DemoPingRequested(
        aggregate_type="demo",
        aggregate_id=UUID("00000000-0000-7000-8000-000000000001"),
        message="atomic",
    )
    savepoint = await db_session.begin_nested()
    row = await publish(db_session, event, metadata={"request_id": "req-atomic"})
    producer_state = await append_audit(
        db_session,
        AuditRecord(
            actor_type="system",
            action="foundation.atomicity_verified",
            resource_type="test",
            request_id="req-atomic",
            event_id=row.event_id,
        ),
    )
    await db_session.flush()
    event_id = row.event_id
    state_id = producer_state.id
    await savepoint.rollback()

    assert await db_session.get(OutboxEvent, event_id) is None
    assert await db_session.get(AuditLog, state_id) is None


@pytest.mark.asyncio
async def test_processed_event_is_idempotent(db_session) -> None:
    envelope = DemoPingRequested(
        aggregate_type="demo",
        aggregate_id=UUID("00000000-0000-7000-8000-000000000002"),
        message="once",
    ).envelope()
    handled = 0

    async def handler(session, event) -> None:
        nonlocal handled
        handled += 1
        await append_audit(
            session,
            AuditRecord(
                actor_type="worker",
                action="foundation.idempotency_verified",
                resource_type="test",
                request_id="req-idempotent",
                event_id=event.event_id,
            ),
        )

    clock = FakeClock(datetime(2026, 1, 1, tzinfo=UTC))
    assert await handle_once(
        db_session,
        consumer_name="test-consumer",
        event=envelope,
        handler=handler,
        clock=clock,
    )
    assert not await handle_once(
        db_session,
        consumer_name="test-consumer",
        event=envelope,
        handler=handler,
        clock=clock,
    )
    assert handled == 1
    await db_session.flush()
    assert await db_session.scalar(
        text("SELECT count(*) FROM audit_log WHERE event_id = :event_id"),
        {"event_id": envelope.event_id},
    ) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "statement",
    [
        "UPDATE audit_log SET action='changed' WHERE id=:id",
        "DELETE FROM audit_log WHERE id=:id",
    ],
)
async def test_audit_log_rejects_mutation(db_session, statement: str) -> None:
    record = AuditRecord(
        actor_type="system",
        action="foundation.test",
        resource_type="test",
        request_id="req-audit",
    )
    row = await append_audit(db_session, record)
    await db_session.flush()

    savepoint = await db_session.begin_nested()
    with pytest.raises(DBAPIError, match="audit_log is append-only"):
        await db_session.execute(text(statement), {"id": row.id})
    await savepoint.rollback()
    assert await db_session.get(AuditLog, row.id) is not None