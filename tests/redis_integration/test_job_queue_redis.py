"""Real-Redis tests for the job queue (T-015).

Requirement: JOB-AC-2 (Redis integration tests cover enqueue/claim/ack, redelivery after consumer
failure, and DLQ after exhaustion). Synthetic payloads only. Each test uses a unique stream, dead
letter stream and consumer group (``redis_scope``) and deletes only its own keys.

Redelivery after a consumer crash is driven with ``XCLAIM ... IDLE`` to age one pending message, so
the test needs no 60 second sleep and ``JobQueue`` is unchanged.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta

import pytest

from app.core import FakeClock
from app.jobs_workers import JobEnvelope, JobQueue, JobRegistry

pytestmark = pytest.mark.redis

JOB_TYPE = "t015.synthetic"


async def _pending(scope, stream: str, group: str) -> int:
    summary = await scope.client.xpending(stream, group)
    return int(summary["pending"])


def _registry(handler) -> JobRegistry:
    registry = JobRegistry()
    registry.register(JOB_TYPE, 1, handler)
    return registry


def _job(**overrides) -> JobEnvelope:
    return JobEnvelope(
        job_type=JOB_TYPE,
        payload={"n": 1},
        metadata={"request_id": "req-t015"},
        **overrides,
    )


@pytest.mark.asyncio
async def test_enqueue_claim_ack_through_real_redis(redis_scope) -> None:
    stream, dead, group = (redis_scope.name(x) for x in ("jobs", "dead", "group"))
    queue = JobQueue(redis_scope.client, stream=stream, dead_letter_stream=dead)
    seen: list[JobEnvelope] = []

    async def handler(job: JobEnvelope) -> None:
        seen.append(job)

    job = _job()
    await queue.enqueue(job)
    assert await queue.run_once(group=group, consumer="c1", registry=_registry(handler)) == 1

    assert [item.job_id for item in seen] == [job.job_id]
    assert seen[0].metadata["request_id"] == "req-t015"
    assert await _pending(redis_scope, stream, group) == 0
    assert await redis_scope.client.xlen(dead) == 0
    assert await queue.run_once(group=group, consumer="c1", registry=_registry(handler)) == 0
    assert len(seen) == 1


@pytest.mark.asyncio
async def test_unacknowledged_job_is_redelivered_after_consumer_failure(redis_scope) -> None:
    client = redis_scope.client
    stream, dead, group = (redis_scope.name(x) for x in ("jobs", "dead", "group"))
    queue = JobQueue(client, stream=stream, dead_letter_stream=dead)
    seen: list[JobEnvelope] = []

    async def handler(job: JobEnvelope) -> None:
        seen.append(job)

    job = _job()
    await queue.enqueue(job)
    await client.xgroup_create(stream, group, id="0", mkstream=True)
    delivered = await client.xreadgroup(group, "crashed-consumer", {stream: ">"}, count=10)
    message_id = delivered[0][1][0][0]
    assert await _pending(redis_scope, stream, group) == 1

    registry = _registry(handler)
    assert await queue.run_once(group=group, consumer="rescuer", registry=registry) == 0
    assert seen == []
    assert await _pending(redis_scope, stream, group) == 1

    await client.xclaim(
        stream, group, "crashed-consumer", min_idle_time=0, message_ids=[message_id], idle=61_000
    )
    assert await queue.run_once(group=group, consumer="rescuer", registry=registry) == 1
    assert [item.job_id for item in seen] == [job.job_id]
    assert await _pending(redis_scope, stream, group) == 0


@pytest.mark.asyncio
async def test_failed_handler_is_retried_with_backoff_then_succeeds(redis_scope) -> None:
    client = redis_scope.client
    stream, dead, group = (redis_scope.name(x) for x in ("jobs", "dead", "group"))
    start = datetime.now(UTC)
    clock = FakeClock(start)
    queue = JobQueue(client, stream=stream, dead_letter_stream=dead, clock=clock, max_attempts=3)
    attempts: list[int] = []

    async def flaky(job: JobEnvelope) -> None:
        attempts.append(job.attempt)
        if len(attempts) == 1:
            raise RuntimeError("synthetic failure")

    registry = _registry(flaky)
    await queue.enqueue(_job())
    assert await queue.run_once(group=group, consumer="c1", registry=registry) == 1
    assert attempts == [0]
    assert await _pending(redis_scope, stream, group) == 0
    scheduled = await client.zrange(f"{stream}:scheduled", 0, -1, withscores=True)
    assert len(scheduled) == 1
    assert scheduled[0][1] == pytest.approx((start + timedelta(seconds=2)).timestamp())

    assert await queue.run_once(group=group, consumer="c1", registry=registry) == 0
    clock.advance(timedelta(seconds=3))
    assert await queue.run_once(group=group, consumer="c1", registry=registry) == 1
    assert attempts == [0, 1]
    assert await client.zcard(f"{stream}:scheduled") == 0
    assert await client.xlen(dead) == 0


@pytest.mark.asyncio
async def test_job_goes_to_dead_letter_stream_after_exhaustion(redis_scope) -> None:
    client = redis_scope.client
    stream, dead, group = (redis_scope.name(x) for x in ("jobs", "dead", "group"))
    start = datetime.now(UTC)
    clock = FakeClock(start)
    queue = JobQueue(client, stream=stream, dead_letter_stream=dead, clock=clock, max_attempts=4)
    attempts: list[int] = []

    async def always_fails(job: JobEnvelope) -> None:
        attempts.append(job.attempt)
        raise RuntimeError("synthetic failure")

    registry = _registry(always_fails)
    job = _job()
    await queue.enqueue(job)

    expected_delays = [2, 4, 8]
    for delay in expected_delays:
        assert await queue.run_once(group=group, consumer="c1", registry=registry) == 1
        scheduled = await client.zrange(f"{stream}:scheduled", 0, -1, withscores=True)
        assert len(scheduled) == 1
        assert scheduled[0][1] == pytest.approx(
            (clock.now() + timedelta(seconds=delay)).timestamp()
        )
        assert await client.xlen(dead) == 0
        clock.advance(timedelta(seconds=delay + 1))

    assert await queue.run_once(group=group, consumer="c1", registry=registry) == 1
    assert attempts == [0, 1, 2, 3]
    assert await client.zcard(f"{stream}:scheduled") == 0
    assert await _pending(redis_scope, stream, group) == 0
    entries = await client.xrange(dead)
    assert len(entries) == 1
    fields = {key.decode(): value.decode() for key, value in entries[0][1].items()}
    assert fields["failure_code"] == "RuntimeError"
    dead_job = json.loads(fields["job"])
    assert dead_job["job_id"] == str(job.job_id)
    assert dead_job["attempt"] == 3
    assert await queue.run_once(group=group, consumer="c1", registry=registry) == 0
