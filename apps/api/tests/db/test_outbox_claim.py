from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from uuid import uuid4

import pytest
from sqlalchemy import delete
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.core import SystemClock, UUID7Factory
from app.db_migrations import build_async_engine
from app.events_outbox import DemoPingRequested, OutboxEvent, claim_batch, publish

pytestmark = pytest.mark.db


@pytest.mark.asyncio
async def test_outbox_claim_uses_skip_locked_for_concurrent_relays(
    migrated_test_schema,
) -> None:
    engine = build_async_engine(
        migrated_test_schema.require_database_url(direct=True),
        pooled=False,
    )
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    event_id = None
    first = sessions()
    try:
        async with sessions.begin() as session:
            row = await publish(
                session,
                DemoPingRequested(
                    aggregate_type="claim-test",
                    aggregate_id=UUID7Factory(SystemClock()).new(),
                    message=str(uuid4()),
                ),
            )
            event_id = row.event_id

        await first.begin()
        first_claim = await claim_batch(
            first,
            relay_id="relay-one",
            now=datetime.now(UTC),
            limit=1,
            event_ids=[event_id],
        )
        async with sessions.begin() as second:
            async with asyncio.timeout(5):
                second_claim = await claim_batch(
                    second,
                    relay_id="relay-two",
                    now=datetime.now(UTC),
                    limit=1,
                    event_ids=[event_id],
                )

        assert [row.event_id for row in first_claim] == [event_id]
        assert second_claim == []
    finally:
        await first.rollback()
        await first.close()
        if event_id is not None:
            async with sessions.begin() as cleanup:
                await cleanup.execute(delete(OutboxEvent).where(OutboxEvent.event_id == event_id))
        await engine.dispose()