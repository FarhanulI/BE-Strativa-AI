"""Real-Redis plus local-Postgres tests for the outbox relay and event worker (T-015).

Requirements: OUT-AC-3 (the relay publishes correlation metadata and retries with bounded backoff)
and OBS-AC-3 (one correlation ID follows outbox, relay, worker and audit).

Coverage limit for OBS-AC-3: these tests supply the request ID to ``publish`` explicitly, as
``scripts/demo_ping.py`` does. They do not cover an API request that reaches the outbox, because
the route handlers that publish events (for example ``app/auth/routes.py`` ``register``) call
``publish`` without request metadata, so no request ID reaches the outbox row. That is reported as
a finding on T-015, not fixed here.

The tests are marked ``db`` and ``redis``: they skip without ``TEST_REDIS_URL`` (visible reason) and
fail when Redis is configured but wrong or unreachable. Synthetic data only; every committed row is
removed in teardown (audit rows through the guarded ``tests.helpers.audit_teardown`` helper).
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.core import FakeClock, SystemClock, UUID7Factory, get_request_context
from app.db_migrations import build_async_engine
from app.events_outbox import DemoPingRequested, OutboxEvent, ProcessedEvent, publish
from app.jobs_workers import EventWorker, OutboxRelay
from app.observability_audit import AuditLog, AuditRecord, append_audit
from tests.helpers.audit_teardown import delete_audit_rows

pytestmark = [pytest.mark.db, pytest.mark.redis]


@pytest.fixture
async def sessions(migrated_test_schema):
    engine = build_async_engine(
        migrated_test_schema.require_database_url(direct=True), pooled=False
    )
    try:
        yield async_sessionmaker(engine, expire_on_commit=False)
    finally:
        await engine.dispose()


def _decode(fields: dict) -> dict[str, str]:
    return {key.decode(): value.decode() for key, value in fields.items()}


async def _publish_demo(sessions, metadata: dict[str, str]) -> tuple[UUID, UUID]:
    aggregate_id = UUID7Factory(SystemClock()).new()
    async with sessions.begin() as session:
        row = await publish(
            session,
            DemoPingRequested(
                aggregate_type="t015", aggregate_id=aggregate_id, message=str(uuid4())
            ),
            metadata=metadata,
        )
        return row.event_id, aggregate_id


async def _fetch(sessions, event_id: UUID) -> OutboxEvent:
    async with sessions() as session:
        row = await session.get(OutboxEvent, event_id)
        assert row is not None
        return row


async def _remove_outbox(sessions, event_id: UUID) -> None:
    async with sessions.begin() as session:
        await session.execute(delete(OutboxEvent).where(OutboxEvent.event_id == event_id))


@pytest.mark.asyncio
async def test_relay_publishes_correlation_metadata_to_the_stream(redis_scope, sessions) -> None:
    """OUT-AC-3: correlation metadata survives the outbox row and reaches the Redis stream."""
    request_id = f"req-{uuid4()}"
    traceparent = "00-0af7651916cd43dd8448eb211c80319c-b7ad6b7169203331-01"
    stream = redis_scope.name("events")
    event_id, _ = await _publish_demo(
        sessions, {"request_id": request_id, "traceparent": traceparent}
    )
    try:
        relay = OutboxRelay(sessions, redis_scope.client, stream=stream, relay_id="relay-t015")
        assert await relay.run_once(limit=1, event_ids=[event_id]) == 1

        entries = await redis_scope.client.xrange(stream)
        assert len(entries) == 1
        fields = _decode(entries[0][1])
        assert fields["event_id"] == str(event_id)
        assert json.loads(fields["metadata"]) == {
            "request_id": request_id,
            "traceparent": traceparent,
        }
        row = await _fetch(sessions, event_id)
        assert row.published_at is not None
        assert row.claimed_by is None and row.claimed_until is None
    finally:
        await _remove_outbox(sessions, event_id)


@pytest.mark.asyncio
async def test_relay_retries_with_bounded_backoff_then_publishes(redis_scope, sessions) -> None:
    """OUT-AC-3: a real delivery failure schedules retries with delays capped below 300 seconds.

    The failure is real, not mocked: the target key holds a string, so ``XADD`` is refused by
    Redis (WRONGTYPE).
    """
    stream = redis_scope.name("events")
    event_id, _ = await _publish_demo(sessions, {"request_id": f"req-{uuid4()}"})
    try:
        await redis_scope.client.set(stream, "not-a-stream")
        clock = FakeClock(datetime.now(UTC))
        relay = OutboxRelay(
            sessions, redis_scope.client, stream=stream, relay_id="relay-t015", clock=clock
        )
        delays: list[float] = []
        for attempt in range(1, 11):
            assert await relay.run_once(limit=1, event_ids=[event_id]) == 1
            row = await _fetch(sessions, event_id)
            assert row.published_at is None
            assert row.claimed_by is None and row.claimed_until is None
            assert row.last_error == "delivery_failed"
            assert row.attempts == attempt
            delay = (row.available_at - clock.now()).total_seconds()
            delays.append(delay)
            assert await relay.run_once(limit=1, event_ids=[event_id]) == 0
            clock.advance(timedelta(seconds=delay))

        assert delays == pytest.approx([2, 4, 8, 16, 32, 64, 128, 256, 256, 256])
        assert max(delays) <= 300

        await redis_scope.client.delete(stream)
        assert await relay.run_once(limit=1, event_ids=[event_id]) == 1
        assert await redis_scope.client.xlen(stream) == 1
        assert (await _fetch(sessions, event_id)).published_at is not None
    finally:
        await _remove_outbox(sessions, event_id)


@pytest.mark.asyncio
async def test_one_request_id_follows_outbox_relay_worker_and_audit(redis_scope, sessions) -> None:
    """OBS-AC-3 (outbox, relay, worker and audit; the API hop is not covered, see module note)."""
    request_id = f"req-{uuid4()}"
    stream = redis_scope.name("events")
    group = redis_scope.name("group")
    aggregate_id = UUID7Factory(SystemClock()).new()
    event_id = None
    handler_context: list[str] = []
    try:
        async with sessions.begin() as session:
            row = await publish(
                session,
                DemoPingRequested(aggregate_type="t015", aggregate_id=aggregate_id, message="ping"),
                metadata={"request_id": request_id},
            )
            event_id = row.event_id
            await append_audit(
                session,
                AuditRecord(
                    actor_type="system",
                    action="foundation.t015_ping_requested",
                    resource_type="t015",
                    resource_id=str(aggregate_id),
                    request_id=request_id,
                    event_id=event_id,
                ),
            )

        relay = OutboxRelay(sessions, redis_scope.client, stream=stream, relay_id="relay-t015")
        assert await relay.run_once(limit=1, event_ids=[event_id]) == 1

        async def consume(session, envelope) -> None:
            handler_context.append(get_request_context().request_id)
            await append_audit(
                session,
                AuditRecord(
                    actor_type="worker",
                    action="foundation.t015_ping_processed",
                    resource_type="t015",
                    resource_id=str(envelope.aggregate_id),
                    request_id=envelope.metadata["request_id"],
                    event_id=envelope.event_id,
                ),
            )

        worker = EventWorker(
            sessions, redis_scope.client, consumer_name="worker-t015", stream=stream, group=group
        )
        assert await worker.run_once(consume) == 1

        assert handler_context == [request_id]
        async with sessions() as session:
            outbox = await session.get(OutboxEvent, event_id)
            audits = list(
                await session.scalars(select(AuditLog).where(AuditLog.request_id == request_id))
            )
            processed = list(
                await session.scalars(
                    select(ProcessedEvent).where(ProcessedEvent.event_id == event_id)
                )
            )
        assert outbox is not None and outbox.event_metadata["request_id"] == request_id
        assert sorted(audit.action for audit in audits) == [
            "foundation.t015_ping_processed",
            "foundation.t015_ping_requested",
        ]
        assert {audit.event_id for audit in audits} == {event_id}
        assert len(processed) == 1
    finally:
        async with sessions.begin() as session:
            await delete_audit_rows(session, resource_type="t015", resource_ids=[str(aggregate_id)])
            if event_id is not None:
                await session.execute(
                    delete(ProcessedEvent).where(ProcessedEvent.event_id == event_id)
                )
                await session.execute(delete(OutboxEvent).where(OutboxEvent.event_id == event_id))
