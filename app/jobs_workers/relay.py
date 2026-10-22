from __future__ import annotations

from uuid import UUID

from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.core import Clock, SystemClock
from app.events_outbox import EventEnvelope, claim_batch, mark_delivery_failed, mark_published


class OutboxRelay:
    def __init__(
        self,
        sessions: async_sessionmaker,
        redis: Redis,
        *,
        stream: str = "domain-events",
        relay_id: str,
        clock: Clock | None = None,
    ) -> None:
        self.sessions = sessions
        self.redis = redis
        self.stream = stream
        self.relay_id = relay_id
        self.clock = clock or SystemClock()

    async def run_once(
        self,
        *,
        limit: int = 100,
        event_ids: list[UUID] | None = None,
    ) -> int:
        async with self.sessions.begin() as session:
            rows = await claim_batch(
                session,
                relay_id=self.relay_id,
                now=self.clock.now(),
                limit=limit,
                event_ids=event_ids,
            )

        for row in rows:
            envelope = EventEnvelope(
                event_id=row.event_id,
                event_type=row.event_type,
                event_version=row.event_version,
                aggregate_type=row.aggregate_type,
                aggregate_id=row.aggregate_id,
                workspace_id=row.workspace_id,
                occurred_at=row.occurred_at,
                payload=row.payload,
                metadata=row.event_metadata,
            )
            try:
                await self.redis.xadd(self.stream, envelope.stream_fields())
            except Exception:
                delay = min(300, 2 ** min(row.attempts, 8))
                async with self.sessions.begin() as session:
                    await mark_delivery_failed(
                        session,
                        event_id=row.event_id,
                        relay_id=self.relay_id,
                        now=self.clock.now(),
                        retry_after_seconds=delay,
                    )
            else:
                async with self.sessions.begin() as session:
                    await mark_published(
                        session,
                        event_id=row.event_id,
                        relay_id=self.relay_id,
                        published_at=self.clock.now(),
                    )
        return len(rows)