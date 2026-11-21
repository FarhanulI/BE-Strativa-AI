"""Circuit breaker tests (spec 10.4, AC-20, INV-22). Driven only by FakeClock; no real time."""

from __future__ import annotations

import threading
from datetime import UTC, datetime, timedelta

import pytest
import structlog

from app.ai_platform.catalog import ModelCatalog
from app.ai_platform.circuit_breaker import CircuitBreakerRegistry
from app.ai_platform.config import AiPlatformConfig
from app.ai_platform.enums import AiCapability, AiModality, AiTaskName, LatencyClass, QualityClass
from app.ai_platform.failure_policy import ProviderFailureKind
from app.ai_platform.router import RoutingInput, route
from app.ai_platform.tasks import AiTaskRegistry
from app.core import FakeClock
from tests.helpers.synthetic_catalog import (
    FAKE_PROVIDER_P1,
    FAKE_PROVIDER_P2,
    catalog_dict,
    chat_entry,
)

K = ProviderFailureKind
KEY = (FAKE_PROVIDER_P1, "model-a")
OTHER = (FAKE_PROVIDER_P1, "model-b")
START = datetime(2030, 1, 1, tzinfo=UTC)


def make(**overrides: int) -> tuple[CircuitBreakerRegistry, FakeClock]:
    clock = FakeClock(START)
    config = AiPlatformConfig(_env_file=None, **overrides)
    return CircuitBreakerRegistry(clock, config), clock


def fail(registry: CircuitBreakerRegistry, key: tuple[str, str] = KEY, count: int = 1) -> None:
    for _ in range(count):
        registry.record_failure(key, K.TIMEOUT)


def seconds(clock: FakeClock, amount: float) -> None:
    clock.advance(timedelta(seconds=amount))


def open_it(registry: CircuitBreakerRegistry, key: tuple[str, str] = KEY) -> None:
    fail(registry, key, 5)
    assert registry.state(key) == "open"


def test_defaults_come_from_the_config() -> None:
    config = AiPlatformConfig(_env_file=None)
    assert (
        config.breaker_failure_threshold,
        config.breaker_window_seconds,
        config.breaker_open_seconds,
    ) == (5, 60, 30)


def test_four_counted_failures_do_not_open() -> None:
    registry, _ = make()
    fail(registry, count=4)
    assert registry.state(KEY) == "closed"
    assert registry.begin_attempt(KEY) is True
    assert registry.unavailable_models() == frozenset()


def test_fifth_failure_within_window_opens() -> None:
    registry, clock = make()
    for _ in range(5):
        fail(registry)
        seconds(clock, 10)
    # failures at 0, 10, 20, 30, 40 s: all within 60 s of the fifth
    assert registry.state(KEY) == "open"


@pytest.mark.parametrize("kind", [K.TIMEOUT, K.CONNECTION_ERROR, K.HTTP_5XX, K.RATE_LIMITED])
def test_each_counted_kind_opens_after_five(kind: ProviderFailureKind) -> None:
    registry, _ = make()
    for _ in range(5):
        registry.record_failure(KEY, kind)
    assert registry.state(KEY) == "open"


def test_sliding_window_drops_old_failures() -> None:
    registry, clock = make()
    fail(registry, count=4)
    seconds(clock, 61)
    fail(registry)  # the four earlier failures are older than 60 s
    assert registry.state(KEY) == "closed"


def test_failure_exactly_at_window_edge_still_counts() -> None:
    registry, clock = make()
    fail(registry, count=4)
    seconds(clock, 60)
    fail(registry)
    assert registry.state(KEY) == "open"


def test_success_between_failures_resets_the_count() -> None:
    registry, _ = make()
    fail(registry, count=4)
    registry.record_success(KEY)
    fail(registry, count=4)
    assert registry.state(KEY) == "closed"
    fail(registry)
    assert registry.state(KEY) == "open"


def test_open_refuses_attempts_and_is_unavailable() -> None:
    registry, clock = make()
    open_it(registry)
    seconds(clock, 29)
    assert registry.begin_attempt(KEY) is False
    assert registry.state(KEY) == "open"
    assert registry.unavailable_models() == frozenset({KEY})


def test_exactly_at_open_until_is_half_open_with_one_probe() -> None:
    registry, clock = make()
    open_it(registry)
    seconds(clock, 30)
    assert registry.state(KEY) == "half_open"
    assert registry.unavailable_models() == frozenset()
    assert registry.begin_attempt(KEY) is True
    assert registry.begin_attempt(KEY) is False
    assert registry.unavailable_models() == frozenset({KEY})


def test_exactly_one_probe_under_concurrent_callers() -> None:
    registry, clock = make()
    open_it(registry)
    seconds(clock, 30)
    results: list[bool] = []
    barrier = threading.Barrier(32)

    def caller() -> None:
        barrier.wait()
        results.append(registry.begin_attempt(KEY))

    threads = [threading.Thread(target=caller) for _ in range(32)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert results.count(True) == 1
    assert results.count(False) == 31


def test_probe_success_closes_and_clears() -> None:
    registry, clock = make()
    open_it(registry)
    seconds(clock, 30)
    assert registry.begin_attempt(KEY) is True
    registry.record_success(KEY)
    assert registry.state(KEY) == "closed"
    assert registry.unavailable_models() == frozenset()
    assert registry.begin_attempt(KEY) is True
    assert registry.begin_attempt(KEY) is True
    fail(registry, count=4)  # the failure list was cleared
    assert registry.state(KEY) == "closed"


def test_probe_failure_reopens_for_a_full_period() -> None:
    registry, clock = make()
    open_it(registry)
    seconds(clock, 30)
    assert registry.begin_attempt(KEY) is True
    seconds(clock, 5)
    registry.record_failure(KEY, K.HTTP_5XX)
    assert registry.state(KEY) == "open"
    seconds(clock, 29)
    assert registry.state(KEY) == "open"
    assert registry.begin_attempt(KEY) is False
    seconds(clock, 1)
    assert registry.state(KEY) == "half_open"
    assert registry.begin_attempt(KEY) is True


def test_lost_probe_lets_a_new_probe_start() -> None:
    registry, clock = make()
    open_it(registry)
    seconds(clock, 30)
    assert registry.begin_attempt(KEY) is True
    seconds(clock, 30)  # exactly open_seconds: still in flight
    assert registry.begin_attempt(KEY) is False
    seconds(clock, 1)  # longer than open_seconds: lost
    assert registry.unavailable_models() == frozenset()
    assert registry.begin_attempt(KEY) is True


def test_abandon_releases_the_probe() -> None:
    registry, clock = make()
    open_it(registry)
    seconds(clock, 30)
    assert registry.begin_attempt(KEY) is True
    registry.abandon_attempt(KEY)
    assert registry.state(KEY) == "half_open"
    assert registry.unavailable_models() == frozenset()
    assert registry.begin_attempt(KEY) is True


def test_abandon_on_unknown_key_is_harmless() -> None:
    registry, _ = make()
    registry.abandon_attempt(KEY)
    assert registry.state(KEY) == "closed"


@pytest.mark.parametrize(
    "kind", [K.INVALID_OUTPUT, K.TRUNCATED, K.CONTENT_REFUSED, K.BAD_REQUEST, K.MISSING_CREDENTIALS]
)
def test_neutral_outcomes_neither_count_nor_reset(kind: ProviderFailureKind) -> None:
    registry, _ = make()
    fail(registry, count=4)
    for _ in range(10):
        registry.record_failure(KEY, kind)
    assert registry.state(KEY) == "closed"  # did not count
    fail(registry)  # the four earlier counted failures were not reset
    assert registry.state(KEY) == "open"


@pytest.mark.parametrize("kind", [K.INVALID_OUTPUT, K.TRUNCATED, K.CONTENT_REFUSED, K.BAD_REQUEST])
def test_neutral_outcome_releases_a_probe_without_closing_or_reopening(
    kind: ProviderFailureKind,
) -> None:
    registry, clock = make()
    open_it(registry)
    seconds(clock, 30)
    assert registry.begin_attempt(KEY) is True
    registry.record_failure(KEY, kind)
    assert registry.state(KEY) == "half_open"
    assert registry.begin_attempt(KEY) is True


def test_auth_failure_is_permanently_unavailable_and_not_counted() -> None:
    registry, clock = make()
    fail(registry, count=4)
    registry.record_failure(KEY, K.AUTH_FAILED)
    assert registry.begin_attempt(KEY) is False
    assert registry.unavailable_models() == frozenset({KEY})
    seconds(clock, 10_000)
    assert registry.begin_attempt(KEY) is False
    assert registry.unavailable_models() == frozenset({KEY})
    assert registry.state(KEY) == "open"  # never half-open
    registry.record_success(KEY)
    assert registry.begin_attempt(KEY) is False


def test_auth_failure_does_not_affect_the_counted_failures_of_another_key() -> None:
    registry, _ = make()
    registry.record_failure(OTHER, K.AUTH_FAILED)
    fail(registry, count=4)
    assert registry.state(KEY) == "closed"
    assert registry.begin_attempt(KEY) is True
    assert registry.unavailable_models() == frozenset({OTHER})


def test_keys_are_independent() -> None:
    registry, clock = make()
    open_it(registry)
    assert registry.begin_attempt(OTHER) is True
    assert registry.state(OTHER) == "closed"
    seconds(clock, 30)
    assert registry.begin_attempt(KEY) is True
    assert registry.begin_attempt(OTHER) is True


def test_custom_settings_come_from_the_config() -> None:
    registry, clock = make(
        breaker_failure_threshold=2, breaker_window_seconds=10, breaker_open_seconds=5
    )
    fail(registry, count=2)
    assert registry.state(KEY) == "open"
    seconds(clock, 5)
    assert registry.state(KEY) == "half_open"
    registry.begin_attempt(KEY)
    registry.record_success(KEY)
    fail(registry)
    seconds(clock, 11)
    fail(registry)
    assert registry.state(KEY) == "closed"


def test_the_system_clock_is_never_consulted() -> None:
    # Two registries on clocks at different instants behave identically in relative terms.
    for start in (START, datetime(1999, 5, 5, tzinfo=UTC)):
        clock = FakeClock(start)
        registry = CircuitBreakerRegistry(clock, AiPlatformConfig(_env_file=None))
        open_it(registry)
        clock.advance(timedelta(seconds=30))
        assert registry.state(KEY) == "half_open"


def test_transitions_are_logged_with_ids_and_counts_only() -> None:
    registry, clock = make()
    with structlog.testing.capture_logs() as logs:
        open_it(registry)
        seconds(clock, 30)
        registry.begin_attempt(KEY)
        registry.record_success(KEY)
    assert [(e["state"], e["failure_count"]) for e in logs] == [("open", 5), ("closed", 0)]
    for event in logs:
        assert set(event) == {"event", "log_level", "provider", "model", "state", "failure_count"}
        assert (event["provider"], event["model"]) == KEY


# --- feeding the Router ---


def _routing_input(unavailable: frozenset[tuple[str, str]]) -> RoutingInput:
    catalog = ModelCatalog.from_dict(
        catalog_dict(
            chat_entry(provider=FAKE_PROVIDER_P1, model="model-a"),
            chat_entry(provider=FAKE_PROVIDER_P1, model="model-b"),
            chat_entry(provider=FAKE_PROVIDER_P2, model="model-c"),
        )
    )
    task = (
        AiTaskRegistry()
        .get(AiTaskName.GENERATE_HOOK_VARIATIONS)
        .model_copy(
            update={
                "latency": LatencyClass.STANDARD,
                "quality": QualityClass.STANDARD,
                "capabilities": frozenset(
                    {AiCapability.TEXT_GENERATION, AiCapability.STRUCTURED_OUTPUT}
                ),
            }
        )
    )
    providers = {FAKE_PROVIDER_P1, FAKE_PROVIDER_P2}
    return RoutingInput(
        task=task,
        input_modalities_present=frozenset({AiModality.TEXT}),
        estimated_input_units=1_000,
        context_safety_margin_percent=10,
        max_output_units=500,
        quality_floor=None,
        cost_ceiling_micro_usd=1_000_000,
        remaining_budget_micro_usd=10_000_000,
        provider_configured=dict.fromkeys(providers, True),
        provider_billing_mode=dict.fromkeys(providers, "free_tier"),
        unavailable_models=unavailable,
        pinned=None,
        routing_version="rv-test-1",
        catalog=catalog,
    )


def test_open_model_is_excluded_by_the_router_and_half_open_is_routable() -> None:
    registry, clock = make()
    open_it(registry, KEY)
    result = route(_routing_input(registry.unavailable_models()))
    reasons = {str(e["model"]): e["reason_code"] for e in result.snapshot}
    assert reasons["model-a"] == "unavailable"
    assert {c.model for c in result.candidates} == {"model-b", "model-c"}

    seconds(clock, 30)  # half-open with no probe in flight: routable again
    result = route(_routing_input(registry.unavailable_models()))
    assert "model-a" in {c.model for c in result.candidates}

    assert registry.begin_attempt(KEY) is True  # probe in flight: excluded again
    result = route(_routing_input(registry.unavailable_models()))
    assert "model-a" not in {c.model for c in result.candidates}
