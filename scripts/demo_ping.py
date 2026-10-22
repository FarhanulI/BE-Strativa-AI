from __future__ import annotations

import asyncio
import json
from uuid import uuid4

from redis.asyncio import Redis
from sqlalchemy import func, select

from app.core import AppEnvironment, ConfigurationError, Settings, SystemClock, UUID7Factory
from app.db_migrations import async_session_factory, runtime_engine
from app.events_outbox import DemoPingRequested, EventEnvelope, ProcessedEvent, publish
from app.jobs_workers import EventWorker, OutboxRelay
from app.observability_audit import AuditLog, AuditRecord, append_audit


async def demo_ping() -> None:
    settings = Settings()
    if settings.app_env not in (AppEnvironment.DEV, AppEnvironment.TEST):
        raise ConfigurationError("The demo is enabled only in dev or test environments")
    engine = runtime_engine(settings)
    sessions = async_session_factory(engine)
    redis = Redis.from_url(
        settings.require_redis_url(),
        socket_connect_timeout=2,
        socket_timeout=2,
    )
    request_id = str(uuid4())
    stream = f"demo:{request_id}"
    aggregate_id = UUID7Factory(SystemClock()).new()
    event = DemoPingRequested(aggregate_type="demo", aggregate_id=aggregate_id, message="ping")
    worker = EventWorker(
        sessions,
        redis,
        consumer_name=f"demo-{request_id}",
        group=f"demo-{request_id}",
        stream=stream,
    )

    try:
        await redis.xgroup_create(
            worker.stream,
            worker.group,
            id="$",
            mkstream=True,
        )
        async with sessions.begin() as session:
            outbox = await publish(session, event, metadata={"request_id": request_id})
            event_id = outbox.event_id
            await append_audit(
                session,
                AuditRecord(
                    actor_type="system",
                    action="foundation.demo_ping_requested",
                    resource_type="demo",
                    resource_id=str(aggregate_id),
                    request_id=request_id,
                    event_id=event_id,
                ),
            )

        relay = OutboxRelay(sessions, redis, relay_id=f"demo-{request_id}", stream=stream)
        await relay.run_once(limit=1, event_ids=[event_id])
        envelope = EventEnvelope(
            event_id=outbox.event_id,
            event_type=outbox.event_type,
            event_version=outbox.event_version,
            aggregate_type=outbox.aggregate_type,
            aggregate_id=outbox.aggregate_id,
            workspace_id=outbox.workspace_id,
            occurred_at=outbox.occurred_at,
            payload=outbox.payload,
            metadata=outbox.event_metadata,
        )

        async def record_consumed_event(session, envelope) -> None:
            await append_audit(
                session,
                AuditRecord(
                    actor_type="worker",
                    action="foundation.demo_ping_processed",
                    resource_type="demo",
                    resource_id=str(envelope.aggregate_id),
                    request_id=envelope.metadata["request_id"],
                    event_id=envelope.event_id,
                    details={"event_type": envelope.event_type},
                ),
            )

        first_delivery = await worker.run_once(record_consumed_event)
        await redis.xadd(stream, envelope.stream_fields())
        redelivery = await worker.run_once(record_consumed_event)
        async with sessions() as session:
            audit_count = await session.scalar(
                select(func.count()).select_from(AuditLog).where(AuditLog.request_id == request_id)
            )
            processed_count = await session.scalar(
                select(func.count()).select_from(ProcessedEvent).where(
                    ProcessedEvent.event_id == event_id,
                    ProcessedEvent.consumer_name == worker.group,
                )
            )
        if audit_count != 2 or processed_count != 1 or first_delivery != 1 or redelivery != 1:
            raise RuntimeError("Demo event/audit correlation could not be verified")
        print(
            json.dumps(
                {
                    "request_id": request_id,
                    "event_id": str(event_id),
                    "audit_records": audit_count,
                    "processed_events": processed_count,
                    "deliveries": first_delivery + redelivery,
                    "redelivery_idempotent": True,
                    "correlation_verified": True,
                },
                sort_keys=True,
            )
        )
    finally:
        try:
            await redis.delete(stream)
        finally:
            await redis.aclose()
            await engine.dispose()


if __name__ == "__main__":
    asyncio.run(demo_ping())