"""Real-Redis test target (T-015).

The URL comes only from the process environment (``TEST_REDIS_URL``), never from an ``.env*`` file.
It must be a plain ``redis://`` URL on a loopback host that names a dedicated, non-zero database
index (for example ``redis://127.0.0.1:6379/15``), so a test can never touch a shared database.

Missing Redis:

* ``TEST_REDIS_URL`` unset: the test is skipped with a visible reason, unless
  ``REQUIRE_REDIS_TESTS=1`` is set (for CI), in which case it fails loudly.
* ``TEST_REDIS_URL`` set but invalid, or Redis unreachable: the test fails.

Error messages are fixed text and never echo the URL.
"""

from __future__ import annotations

import os
from collections.abc import Mapping
from urllib.parse import urlsplit
from uuid import uuid4

from redis.asyncio import Redis

URL_VARIABLE = "TEST_REDIS_URL"
REQUIRE_VARIABLE = "REQUIRE_REDIS_TESTS"
LOOPBACK_HOSTS = frozenset({"localhost", "127.0.0.1", "::1"})

SKIP_REASON = f"{URL_VARIABLE} is not set; start a local Redis and export it to run this test"
MISSING_MESSAGE = f"{URL_VARIABLE} is required because {REQUIRE_VARIABLE}=1 is set"
INVALID_MESSAGE = f"{URL_VARIABLE} is not a valid Redis URL"
SCHEME_MESSAGE = f"{URL_VARIABLE} must use the plain redis:// scheme"
HOST_MESSAGE = f"{URL_VARIABLE} must use a loopback host"
INDEX_MESSAGE = f"{URL_VARIABLE} must name a dedicated non-zero database index, for example /15"
UNREACHABLE_MESSAGE = f"{URL_VARIABLE} is set but Redis is not reachable"


class RedisTestTargetError(RuntimeError):
    """Fixed message only: no URL, host or credentials."""


def validate_redis_test_url(url: str) -> str:
    try:
        parts = urlsplit(url)
        host = parts.hostname
        _ = parts.port
    except ValueError:
        raise RedisTestTargetError(INVALID_MESSAGE) from None
    if parts.scheme != "redis":
        raise RedisTestTargetError(SCHEME_MESSAGE)
    if host not in LOOPBACK_HOSTS:
        raise RedisTestTargetError(HOST_MESSAGE)
    index = parts.path.lstrip("/")
    if not index.isdigit() or int(index) == 0:
        raise RedisTestTargetError(INDEX_MESSAGE)
    return url


def resolve_redis_test_url(environ: Mapping[str, str] | None = None) -> str | None:
    """The validated URL, or ``None`` when unset and not required. Raises when it must fail."""
    source = os.environ if environ is None else environ
    value = source.get(URL_VARIABLE)
    if not value:
        if source.get(REQUIRE_VARIABLE) == "1":
            raise RedisTestTargetError(MISSING_MESSAGE)
        return None
    return validate_redis_test_url(value)


class RedisTestScope:
    """A connected client plus unique key names; teardown deletes only this scope's keys."""

    def __init__(self, client: Redis) -> None:
        self.client = client
        self.prefix = f"t015:{uuid4().hex}"

    def name(self, label: str) -> str:
        return f"{self.prefix}:{label}"

    async def cleanup(self) -> None:
        keys = [key async for key in self.client.scan_iter(match=f"{self.prefix}:*")]
        if keys:
            await self.client.delete(*keys)


async def connect(url: str) -> Redis:
    client = Redis.from_url(url, socket_connect_timeout=2, socket_timeout=5)
    try:
        await client.ping()
    except Exception:
        await client.aclose()
        raise RedisTestTargetError(UNREACHABLE_MESSAGE) from None
    return client
