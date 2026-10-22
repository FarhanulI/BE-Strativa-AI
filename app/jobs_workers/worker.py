from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from typing import Any

from app.jobs_workers.queue import JobQueue, JobRegistry


async def run_worker(
    queue: JobQueue,
    registry: JobRegistry,
    *,
    group: str,
    consumer: str,
    shutdown: asyncio.Event,
    before_stop: Callable[[], Awaitable[None]] | None = None,
) -> None:
    while not shutdown.is_set():
        await queue.run_once(group=group, consumer=consumer, registry=registry)
    if before_stop is not None:
        async with asyncio.timeout(30):
            await before_stop()


def run_worker_process(
    worker: Callable[[], Awaitable[Any]],
) -> None:
    asyncio.run(worker())