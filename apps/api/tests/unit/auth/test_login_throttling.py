from __future__ import annotations

from datetime import UTC, datetime

import pytest
from redis.asyncio import Redis
from redis.exceptions import RedisError

from app.auth.service import allow_login_attempt
from app.core import ConfigurationError, ExternalServiceError, RateLimited, Settings


class FakeRedis:
    def __init__(self, result: int) -> None:
        self.result = result
        self.arguments: tuple[object, ...] = ()
        self.closed = False

    async def eval(self, *arguments: object) -> int:
        self.arguments = arguments
        return self.result

    async def aclose(self) -> None:
        self.closed = True


@pytest.mark.asyncio
async def test_login_throttle_uses_hashed_email_ip_and_denies_over_limit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    redis = FakeRedis(result=0)
    monkeypatch.setattr(Redis, "from_url", lambda *args, **kwargs: redis)
    settings = Settings(_env_file=None, redis_url="redis://localhost/1")

    with pytest.raises(RateLimited):
        await allow_login_attempt(
            settings,
            email="Private@example.test",
            ip="192.0.2.77",
            now=datetime(2026, 10, 14, tzinfo=UTC),
        )

    assert redis.closed
    key = str(redis.arguments[2])
    assert "private@example.test" not in key.lower()
    assert "192.0.2.77" not in key
    assert redis.arguments[4:6] == ("900", "10")


@pytest.mark.asyncio
async def test_login_throttle_allows_attempt_under_limit(monkeypatch: pytest.MonkeyPatch) -> None:
    redis = FakeRedis(result=1)
    monkeypatch.setattr(Redis, "from_url", lambda *args, **kwargs: redis)
    settings = Settings(_env_file=None, redis_url="redis://localhost/1")

    await allow_login_attempt(
        settings,
        email="person@example.test",
        ip="192.0.2.78",
        now=datetime(2026, 10, 14, tzinfo=UTC),
    )

    assert redis.closed


@pytest.mark.asyncio
async def test_login_throttle_fails_closed_without_redis_configuration() -> None:
    with pytest.raises(ConfigurationError):
        await allow_login_attempt(
            Settings(_env_file=None),
            email="person@example.test",
            ip="192.0.2.79",
            now=datetime(2026, 10, 14, tzinfo=UTC),
        )


@pytest.mark.asyncio
async def test_redis_diagnostics_are_not_exposed_on_throttle_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class BrokenRedis(FakeRedis):
        async def eval(self, *arguments: object) -> int:
            raise RedisError("redis://secret-host/private")

    redis = BrokenRedis(result=0)
    monkeypatch.setattr(Redis, "from_url", lambda *args, **kwargs: redis)

    with pytest.raises(ExternalServiceError) as error:
        await allow_login_attempt(
            Settings(_env_file=None, redis_url="redis://localhost/1"),
            email="person@example.test",
            ip="192.0.2.80",
            now=datetime(2026, 10, 14, tzinfo=UTC),
        )

    assert redis.closed
    assert "secret-host" not in error.value.detail