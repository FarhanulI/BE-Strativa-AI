from __future__ import annotations

from collections.abc import Awaitable, Callable

from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import Clock, SystemClock
from app.events_outbox.contracts import EventEnvelope
from app.events_outbox.models import ProcessedEvent

EventHandler = Callable[[AsyncSession, EventEnvelope], Awaitable[None]]


async def handle_once(
    session: AsyncSession,
    *,
    consumer_name: str,
    event: EventEnvelope,
    handler: EventHandler,
    clock: Clock | None = None,
) -> bool:
    statement = (
        insert(ProcessedEvent)
        .values(
            consumer_name=consumer_name,
            event_id=event.event_id,
            processed_at=(clock or SystemClock()).now(),
        )
        .on_conflict_do_nothing(index_elements=["consumer_name", "event_id"])
        .returning(ProcessedEvent.event_id)
    )
    inserted = await session.scalar(statement)
    if inserted is None:
        return False
    await handler(session, event)
    return True