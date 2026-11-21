"""DB-free tests for the real-Redis test target helper (T-015).

No requirement ID: the helper is test infrastructure for JOB-AC-2, OUT-AC-3 and OBS-AC-3.
"""

from __future__ import annotations

import pytest

from tests.helpers.redis_setup import (
    HOST_MESSAGE,
    INDEX_MESSAGE,
    INVALID_MESSAGE,
    MISSING_MESSAGE,
    SCHEME_MESSAGE,
    RedisTestScope,
    RedisTestTargetError,
    resolve_redis_test_url,
    validate_redis_test_url,
)


@pytest.mark.parametrize(
    "url",
    ["redis://127.0.0.1:6379/15", "redis://localhost/1", "redis://[::1]:6380/9"],
)
def test_loopback_url_with_a_dedicated_index_is_accepted(url: str) -> None:
    assert validate_redis_test_url(url) == url


@pytest.mark.parametrize(
    ("url", "message"),
    [
        ("redis://redis.example.test:6379/15", HOST_MESSAGE),
        ("redis://10.0.0.5/15", HOST_MESSAGE),
        ("rediss://127.0.0.1/15", SCHEME_MESSAGE),
        ("http://127.0.0.1/15", SCHEME_MESSAGE),
        ("redis://127.0.0.1:6379", INDEX_MESSAGE),
        ("redis://127.0.0.1:6379/0", INDEX_MESSAGE),
        ("redis://127.0.0.1:6379/abc", INDEX_MESSAGE),
        ("redis://127.0.0.1:notaport/15", INVALID_MESSAGE),
    ],
)
def test_unsafe_url_is_refused_with_a_fixed_message(url: str, message: str) -> None:
    with pytest.raises(RedisTestTargetError) as error:
        validate_redis_test_url(url)
    assert str(error.value) == message
    assert "example.test" not in str(error.value)
    assert "10.0.0.5" not in str(error.value)


def test_unset_url_skips_unless_redis_tests_are_required() -> None:
    assert resolve_redis_test_url({}) is None
    assert resolve_redis_test_url({"TEST_REDIS_URL": ""}) is None
    with pytest.raises(RedisTestTargetError) as error:
        resolve_redis_test_url({"REQUIRE_REDIS_TESTS": "1"})
    assert str(error.value) == MISSING_MESSAGE


def test_set_url_is_validated_even_when_not_required() -> None:
    with pytest.raises(RedisTestTargetError):
        resolve_redis_test_url({"TEST_REDIS_URL": "redis://redis.example.test/15"})
    assert (
        resolve_redis_test_url({"TEST_REDIS_URL": "redis://127.0.0.1:6379/15"})
        == "redis://127.0.0.1:6379/15"
    )


def test_scope_names_are_unique_and_prefixed() -> None:
    first, second = RedisTestScope(client=None), RedisTestScope(client=None)  # type: ignore[arg-type]
    assert first.prefix != second.prefix
    assert first.name("jobs") == f"{first.prefix}:jobs"
    assert first.name("jobs") != second.name("jobs")
