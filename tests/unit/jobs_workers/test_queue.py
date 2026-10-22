from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import AsyncMock

import pytest

from app.core import get_request_context
from app.core.clock import FakeClock
from app.jobs_workers import JobEnvelope, JobQueue, JobRegistry


@pytest.mark.asyncio
async def test_failed_job_is_scheduled_with_bounded_exponential_backoff() -> None:
    redis = AsyncMock()
    clock = FakeClock(datetime(2026, 1, 1, tzinfo=UTC))
    queue = JobQueue(redis, clock=clock, max_attempts=3)
    registry = JobRegistry()

    async def fail(_: JobEnvelope) -> None:
        raise RuntimeError("safe failure")

    registry.register("demo", 1, fail)
    outcome = await queue.process_fields(
        {
            "job_id": "00000000-0000-7000-8000-000000000001",
            "job_type": "demo",
            "job_version": "1",
            "payload": "{}",
            "metadata": "{}",
            "attempt": "0",
        },
        registry=registry,
    )

    assert outcome == "retried"
    redis.zadd.assert_awaited_once()
    _, scheduled = redis.zadd.await_args.args
    member = next(iter(scheduled))
    assert '"attempt":1' in member
    assert scheduled[member] == datetime(2026, 1, 1, tzinfo=UTC).timestamp() + 2


@pytest.mark.asyncio
async def test_job_is_dead_lettered_at_attempt_limit() -> None:
    redis = AsyncMock()
    queue = JobQueue(redis, max_attempts=2)
    registry = JobRegistry()

    async def fail(_: JobEnvelope) -> None:
        raise RuntimeError("failure")

    registry.register("demo", 1, fail)
    fields = {
        "job_id": "00000000-0000-7000-8000-000000000001",
        "job_type": "demo",
        "job_version": "1",
        "payload": "{}",
        "metadata": "{}",
        "attempt": "1",
    }

    assert await queue.process_fields(fields, registry=registry) == "dead_lettered"
    redis.xadd.assert_awaited_once()
    assert redis.xadd.await_args.args[0] == "jobs:dead"


@pytest.mark.asyncio
async def test_worker_recovers_pending_consumer_group_messages() -> None:
    redis = AsyncMock()
    redis.xautoclaim.return_value = (
        "0-0",
        [
            (
                "1-0",
                {
                    "job_id": "00000000-0000-7000-8000-000000000001",
                    "job_type": "demo",
                    "job_version": "1",
                    "payload": "{}",
                    "metadata": "{}",
                    "attempt": "0",
                },
            )
        ],
        [],
    )
    queue = JobQueue(redis)
    registry = JobRegistry()
    handled: list[str] = []

    async def handler(job: JobEnvelope) -> None:
        handled.append(job.job_type)

    registry.register("demo", 1, handler)

    assert await queue.run_once(group="workers", consumer="one", registry=registry) == 1
    assert handled == ["demo"]
    redis.xack.assert_awaited_once_with("jobs", "workers", "1-0")


@pytest.mark.asyncio
async def test_job_handler_receives_and_resets_request_context() -> None:
    queue = JobQueue(AsyncMock())
    registry = JobRegistry()
    observed: list[str | None] = []

    async def handler(_: JobEnvelope) -> None:
        context = get_request_context(required=True)
        observed.append(context.request_id)

    registry.register("demo", 1, handler)
    result = await queue.process_fields(
        {
            "job_id": "00000000-0000-7000-8000-000000000005",
            "job_type": "demo",
            "job_version": "1",
            "payload": "{}",
            "metadata": '{"request_id":"request-job"}',
            "attempt": "0",
        },
        registry=registry,
    )

    assert result == "processed"
    assert observed == ["request-job"]
    assert get_request_context() is None