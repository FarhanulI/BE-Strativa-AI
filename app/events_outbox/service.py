from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.events_outbox.contracts import DEFAULT_EVENT_REGISTRY, DomainEvent, EventRegistry
from app.events_outbox.models import OutboxEvent


async def publish(
    session: AsyncSession,
    event: DomainEvent,
    *,
    metadata: dict[str, str] | None = None,
    registry: EventRegistry = DEFAULT_EVENT_REGISTRY,
) -> OutboxEvent:
    registry.validate(event)
    envelope = event.envelope(metadata)
    row = OutboxEvent(
        event_id=envelope.event_id,
        event_type=envelope.event_type,
        event_version=envelope.event_version,
        aggregate_type=envelope.aggregate_type,
        aggregate_id=envelope.aggregate_id,
        workspace_id=envelope.workspace_id,
        occurred_at=envelope.occurred_at,
        payload=envelope.payload,
        event_metadata=envelope.metadata,
        available_at=envelope.occurred_at,
    )
    session.add(row)
    return row


async def claim_batch(
    session: AsyncSession,
    *,
    relay_id: str,
    now: datetime,
    lease_seconds: int = 60,
    limit: int = 100,
    event_ids: list[UUID] | None = None,
) -> list[OutboxEvent]:
    from datetime import timedelta

    from sqlalchemy import or_, select

    conditions = [
        OutboxEvent.published_at.is_(None),
        OutboxEvent.available_at <= now,
        or_(OutboxEvent.claimed_until.is_(None), OutboxEvent.claimed_until <= now),
    ]
    if event_ids is not None:
        conditions.append(OutboxEvent.event_id.in_(event_ids))
    statement = (
        select(OutboxEvent)
        .where(*conditions)
        .order_by(OutboxEvent.available_at, OutboxEvent.created_at)
        .limit(limit)
        .with_for_update(skip_locked=True)
    )
    result = await session.scalars(statement)
    rows = list(result)
    for row in rows:
        row.claimed_by = relay_id
        row.claimed_until = now + timedelta(seconds=lease_seconds)
        row.attempts += 1
    await session.flush()
    return rows


async def mark_published(
    session: AsyncSession,
    *,
    event_id: Any,
    relay_id: str,
    published_at: datetime,
) -> None:
    from sqlalchemy import update

    await session.execute(
        update(OutboxEvent)
        .where(OutboxEvent.event_id == event_id, OutboxEvent.claimed_by == relay_id)
        .values(
            published_at=published_at,
            claimed_by=None,
            claimed_until=None,
            last_error=None,
        )
    )


async def mark_delivery_failed(
    session: AsyncSession,
    *,
    event_id: Any,
    relay_id: str,
    now: datetime,
    retry_after_seconds: int,
) -> None:
    from datetime import timedelta

    from sqlalchemy import update

    await session.execute(
        update(OutboxEvent)
        .where(OutboxEvent.event_id == event_id, OutboxEvent.claimed_by == relay_id)
        .values(
            available_at=now + timedelta(seconds=retry_after_seconds),
            claimed_by=None,
            claimed_until=None,
            last_error="delivery_failed",
        )
    )