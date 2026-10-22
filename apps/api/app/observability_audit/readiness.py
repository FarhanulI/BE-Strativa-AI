from __future__ import annotations

import asyncio
import random
from typing import Literal

from redis.asyncio import Redis
from sqlalchemy import text

from app.core import ConfigurationError, Settings
from app.db_migrations import runtime_engine

DependencyStatus = Literal["ok", "unavailable", "not_configured"]


async def check_database(settings: Settings) -> DependencyStatus:
    try:
        engine = runtime_engine(settings)
    except ConfigurationError:
        return "not_configured"

    loop = asyncio.get_running_loop()
    deadline = loop.time() + 10.0
    delay = 0.2
    try:
        while loop.time() < deadline:
            try:
                async with asyncio.timeout(min(5.0, max(0.05, deadline - loop.time()))):
                    async with engine.connect() as connection:
                        await connection.execute(text("SELECT 1"))
                return "ok"
            except Exception:
                remaining = deadline - loop.time()
                if remaining <= 0:
                    break
                await asyncio.sleep(min(delay * random.uniform(0.8, 1.2), remaining))
                delay = min(delay * 2, 0.8)
        return "unavailable"
    finally:
        await engine.dispose()


async def check_redis(settings: Settings) -> DependencyStatus:
    if settings.redis_url is None:
        return "not_configured"
    client = Redis.from_url(
        settings.require_redis_url(),
        socket_connect_timeout=1,
        socket_timeout=1,
    )
    try:
        async with asyncio.timeout(1.5):
            await client.ping()
        return "ok"
    except Exception:
        return "unavailable"
    finally:
        await client.aclose()