from __future__ import annotations

import json
from collections.abc import Awaitable, Callable
from typing import Any

import structlog
from redis.asyncio import Redis
from redis.exceptions import ResponseError
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.core import RequestContext, reset_request_context, set_request_context
from app.events_outbox import EventEnvelope, handle_once

EventHandler = Callable[[Any, EventEnvelope], Awaitable[None]]


class EventWorker:
    def __init__(
        self,
        sessions: async_sessionmaker,
        redis: Redis,
        *,
        consumer_name: str,
        stream: str = "domain-events",
        group: str = "domain-workers",
    ) -> None:
        self.sessions = sessions
        self.redis = redis
        self.consumer_name = consumer_name
        self.stream = stream
        self.group = group

    async def run_once(self, handler: EventHandler, *, count: int = 10) -> int:
        try:
            await self.redis.xgroup_create(self.stream, self.group, id="0", mkstream=True)
        except ResponseError as error:
            if "BUSYGROUP" not in str(error):
                raise

        claimed = await self.redis.xautoclaim(
            self.stream,
            self.group,
            self.consumer_name,
            min_idle_time=60_000,
            start_id="0-0",
            count=count,
        )
        entries = list(claimed[1])
        if not entries:
            messages = await self.redis.xreadgroup(
                self.group,
                self.consumer_name,
                {self.stream: ">"},
                count=count,
                block=1,
            )
            entries = [entry for _, batch in messages for entry in batch]

        processed = 0
        logger = structlog.get_logger()
        for message_id, fields in entries:
            decoded = {
                (key.decode() if isinstance(key, bytes) else key):
                (value.decode() if isinstance(value, bytes) else value)
                for key, value in fields.items()
            }
            envelope = EventEnvelope(
                event_id=decoded["event_id"],
                event_type=decoded["event_type"],
                event_version=int(decoded["event_version"]),
                aggregate_type=decoded["aggregate_type"],
                aggregate_id=decoded["aggregate_id"],
                workspace_id=decoded["workspace_id"] or None,
                occurred_at=decoded["occurred_at"],
                payload=json.loads(decoded["payload"]),
                metadata=json.loads(decoded["metadata"]),
            )
            request_id = envelope.metadata.get("request_id", str(envelope.event_id))
            context_token = set_request_context(
                RequestContext(request_id=request_id, actor_type="worker")
            )
            log_tokens = structlog.contextvars.bind_contextvars(
                request_id=request_id,
                traceparent=envelope.metadata.get("traceparent"),
                event_id=str(envelope.event_id),
            )
            try:
                async with self.sessions.begin() as session:
                    await handle_once(
                        session,
                        consumer_name=self.group,
                        event=envelope,
                        handler=handler,
                    )
                await self.redis.xack(self.stream, self.group, message_id)
                processed += 1
            except Exception as error:
                logger.error(
                    "event_processing_failed",
                    event_type=envelope.event_type,
                    error_type=type(error).__name__,
                )
                raise
            finally:
                reset_request_context(context_token)
                structlog.contextvars.reset_contextvars(**log_tokens)
        return processed