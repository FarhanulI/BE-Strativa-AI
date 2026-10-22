from __future__ import annotations

import json
from collections.abc import Awaitable, Callable
from datetime import timedelta
from typing import Any
from uuid import UUID

import structlog
from pydantic import BaseModel, ConfigDict, Field
from redis.asyncio import Redis
from redis.exceptions import ResponseError

from app.core import (
    Clock,
    RequestContext,
    SystemClock,
    UUID7Factory,
    reset_request_context,
    set_request_context,
)

JobHandler = Callable[["JobEnvelope"], Awaitable[None]]


class JobEnvelope(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    job_id: UUID = Field(default_factory=lambda: UUID7Factory(SystemClock()).new())
    job_type: str = Field(min_length=1)
    job_version: int = Field(default=1, ge=1)
    payload: dict[str, Any]
    metadata: dict[str, str] = Field(default_factory=dict)
    attempt: int = Field(default=0, ge=0)


class JobRegistry:
    def __init__(self) -> None:
        self._handlers: dict[tuple[str, int], JobHandler] = {}

    def register(self, job_type: str, version: int, handler: JobHandler) -> None:
        key = (job_type, version)
        if key in self._handlers:
            raise ValueError(f"Job handler already registered: {job_type} v{version}")
        self._handlers[key] = handler

    def get(self, job_type: str, version: int) -> JobHandler:
        try:
            return self._handlers[(job_type, version)]
        except KeyError as error:
            raise ValueError("No handler registered for job type/version") from error


class JobQueue:
    def __init__(
        self,
        redis: Redis,
        *,
        stream: str = "jobs",
        dead_letter_stream: str = "jobs:dead",
        clock: Clock | None = None,
        max_attempts: int = 5,
    ) -> None:
        self.redis = redis
        self.stream = stream
        self.dead_letter_stream = dead_letter_stream
        self.clock = clock or SystemClock()
        self.max_attempts = max_attempts

    async def enqueue(self, job: JobEnvelope) -> str:
        return await self.redis.xadd(self.stream, self._fields(job))

    @staticmethod
    def _fields(job: JobEnvelope) -> dict[str, str]:
        return {
            "job_id": str(job.job_id),
            "job_type": job.job_type,
            "job_version": str(job.job_version),
            "payload": json.dumps(job.payload, separators=(",", ":")),
            "metadata": json.dumps(job.metadata, separators=(",", ":")),
            "attempt": str(job.attempt),
        }

    async def process_fields(
        self,
        fields: dict[str, str | bytes],
        *,
        registry: JobRegistry,
    ) -> str:
        decoded = {
            key.decode() if isinstance(key, bytes) else key:
            value.decode() if isinstance(value, bytes) else value
            for key, value in fields.items()
        }
        decoded["payload"] = json.loads(decoded["payload"])
        decoded["metadata"] = json.loads(decoded["metadata"])
        job = JobEnvelope.model_validate(decoded)
        handler = registry.get(job.job_type, job.job_version)
        request_id = job.metadata.get("request_id", str(job.job_id))
        context_token = set_request_context(
            RequestContext(request_id=request_id, actor_type="worker")
        )
        log_tokens = structlog.contextvars.bind_contextvars(
            request_id=request_id,
            traceparent=job.metadata.get("traceparent"),
            job_id=str(job.job_id),
        )
        try:
            await handler(job)
        except Exception as error:
            next_attempt = job.attempt + 1
            if next_attempt >= self.max_attempts:
                await self.redis.xadd(
                    self.dead_letter_stream,
                    {"job": job.model_dump_json(), "failure_code": type(error).__name__},
                )
                return "dead_lettered"
            retry = job.model_copy(update={"attempt": next_attempt})
            due_at = self.clock.now() + timedelta(seconds=min(300, 2**next_attempt))
            await self.redis.zadd(
                f"{self.stream}:scheduled",
                {retry.model_dump_json(): due_at.timestamp()},
            )
            return "retried"
        finally:
            reset_request_context(context_token)
            structlog.contextvars.reset_contextvars(**log_tokens)
        return "processed"

    async def promote_due_retries(self, *, limit: int = 100) -> int:
        scheduled = f"{self.stream}:scheduled"
        members = await self.redis.zrangebyscore(
            scheduled,
            min="-inf",
            max=self.clock.now().timestamp(),
            start=0,
            num=limit,
        )
        promoted = 0
        for member in members:
            raw_job = member.decode() if isinstance(member, bytes) else member
            job = JobEnvelope.model_validate_json(raw_job)
            await self.redis.xadd(self.stream, self._fields(job))
            await self.redis.zrem(scheduled, member)
            promoted += 1
        return promoted

    async def run_once(self, *, group: str, consumer: str, registry: JobRegistry) -> int:
        try:
            await self.redis.xgroup_create(self.stream, group, id="0", mkstream=True)
        except ResponseError as error:
            if "BUSYGROUP" not in str(error):
                raise

        await self.promote_due_retries()
        claimed = await self.redis.xautoclaim(
            self.stream,
            group,
            consumer,
            min_idle_time=60_000,
            start_id="0-0",
            count=10,
        )
        entries = list(claimed[1])
        if not entries:
            messages = await self.redis.xreadgroup(
                group,
                consumer,
                {self.stream: ">"},
                count=10,
                block=1,
            )
            entries = [entry for _, batch in messages for entry in batch]

        processed = 0
        for message_id, fields in entries:
            await self.process_fields(fields, registry=registry)
            await self.redis.xack(self.stream, group, message_id)
            processed += 1
        return processed