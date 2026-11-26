"""Database test for outbox lease reclaim (T-015).

Requirement: OUT-AC-2, the clause "expired leases can be reclaimed". The existing
``test_outbox_claim_uses_skip_locked_for_concurrent_relays`` covers an uncommitted claim; this test
covers a committed lease: live (not claimable) and expired (claimable by another relay). Time is
passed to ``claim_batch``, so the test does not sleep.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from sqlalchemy import delete
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.core import SystemClock, UUID7Factory
from app.db_migrations import build_async_engine
from app.events_outbox import DemoPingRequested, OutboxEvent, claim_batch, publish

pytestmark = pytest.mark.db


@pytest.mark.asyncio
async def test_expired_lease_is_reclaimed_and_live_lease_is_not(migrated_test_schema) -> None:
    engine = build_async_engine(
        migrated_test_schema.require_database_url(direct=True), pooled=False
    )
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    event_id = None
    try:
        async with sessions.begin() as session:
            row = await publish(
                session,
                DemoPingRequested(
                    aggregate_type="t015-lease",
                    aggregate_id=UUID7Factory(SystemClock()).new(),
                    message=str(uuid4()),
                ),
            )
            event_id = row.event_id

        start = datetime.now(UTC)
        async with sessions.begin() as session:
            first = await claim_batch(
                session,
                relay_id="relay-one",
                now=start,
                lease_seconds=60,
                limit=1,
                event_ids=[event_id],
            )
        assert [(r.event_id, r.claimed_by, r.attempts) for r in first] == [
            (event_id, "relay-one", 1)
        ]

        async with sessions.begin() as session:
            during_lease = await claim_batch(
                session,
                relay_id="relay-two",
                now=start + timedelta(seconds=30),
                limit=1,
                event_ids=[event_id],
            )
        assert during_lease == []

        async with sessions.begin() as session:
            after_expiry = await claim_batch(
                session,
                relay_id="relay-two",
                now=start + timedelta(seconds=61),
                limit=1,
                event_ids=[event_id],
            )
        assert [(r.event_id, r.claimed_by, r.attempts) for r in after_expiry] == [
            (event_id, "relay-two", 2)
        ]
    finally:
        if event_id is not None:
            async with sessions.begin() as cleanup:
                await cleanup.execute(delete(OutboxEvent).where(OutboxEvent.event_id == event_id))
        await engine.dispose()
