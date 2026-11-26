"""Circuit breaker tests (spec 10.4, AC-20, AC-64, D-37, INV-22). Driven only by FakeClock."""

from __future__ import annotations

import threading
from datetime import UTC, datetime, timedelta

import pytest
import structlog

from app.ai_platform.catalog import ModelCatalog
from app.ai_platform.circuit_breaker import AttemptHandle, CircuitBreakerRegistry
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
LEASE = 330  # longest default deadline (300 s) plus the fixed 30 s margin


def make(**overrides: int) -> tuple[CircuitBreakerRegistry, FakeClock]:
    clock = FakeClock(START)
    config = AiPlatformConfig(_env_file=None, **overrides)
    return CircuitBreakerRegistry(clock, config), clock


def begin(registry: CircuitBreakerRegistry, key: tuple[str, str] = KEY) -> AttemptHandle:
    handle = registry.begin_attempt(key)
    assert handle is not None
    return handle


def fail(
    registry: CircuitBreakerRegistry,
    key: tuple[str, str] = KEY,
    count: int = 1,
    kind: ProviderFailureKind = K.TIMEOUT,
) -> None:
    """Each failure comes from its own attempt admitted while the breaker is closed."""
    for _ in range(count):
        registry.record_failure(begin(registry, key), kind)


def seconds(clock: FakeClock, amount: float) -> None:
    clock.advance(timedelta(seconds=amount))


def open_it(registry: CircuitBreakerRegistry, key: tuple[str, str] = KEY) -> None:
    fail(registry, key, 5)
    assert registry.state(key) == "open"


def claim_probe(registry: CircuitBreakerRegistry, clock: FakeClock) -> AttemptHandle:
    """Open the breaker, wait for half-open and claim the probe."""
    open_it(registry)
    seconds(clock, 30)
    probe = begin(registry)
    assert probe.probe
    return probe


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
    assert registry.begin_attempt(KEY) is not None
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
    fail(registry, count=5, kind=kind)
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
    registry.record_success(begin(registry))
    fail(registry, count=4)
    assert registry.state(KEY) == "closed"
    fail(registry)
    assert registry.state(KEY) == "open"


def test_open_refuses_attempts_and_is_unavailable() -> None:
    registry, clock = make()
    open_it(registry)
    seconds(clock, 29)
    assert registry.begin_attempt(KEY) is None
    assert registry.state(KEY) == "open"
    assert registry.unavailable_models() == frozenset({KEY})


def test_exactly_at_open_until_is_half_open_with_one_probe() -> None:
    registry, clock = make()
    open_it(registry)
    seconds(clock, 30)
    assert registry.state(KEY) == "half_open"
    assert registry.unavailable_models() == frozenset()
    probe = registry.begin_attempt(KEY)
    assert probe is not None and probe.probe
    assert registry.begin_attempt(KEY) is None
    assert registry.unavailable_models() == frozenset({KEY})


def test_exactly_one_probe_under_concurrent_callers() -> None:
    """AC-64 (d): under concurrent acquisition exactly one handle is the current probe."""
    registry, clock = make()
    open_it(registry)
    seconds(clock, 30)
    results: list[AttemptHandle | None] = []
    barrier = threading.Barrier(32)

    def caller() -> None:
        barrier.wait()
        results.append(registry.begin_attempt(KEY))

    threads = [threading.Thread(target=caller) for _ in range(32)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    granted = [handle for handle in results if handle is not None]
    assert len(granted) == 1 and granted[0].probe
    assert results.count(None) == 31


def test_claim_ids_are_unique_across_attempts_and_keys() -> None:
    registry, _ = make()
    handles = [begin(registry, KEY), begin(registry, KEY), begin(registry, OTHER)]
    assert len({handle.claim_id for handle in handles}) == 3
    assert not any(handle.probe for handle in handles)


def test_probe_success_closes_and_clears() -> None:
    registry, clock = make()
    probe = claim_probe(registry, clock)
    registry.record_success(probe)
    assert registry.state(KEY) == "closed"
    assert registry.unavailable_models() == frozenset()
    assert registry.begin_attempt(KEY) is not None
    assert registry.begin_attempt(KEY) is not None
    fail(registry, count=4)  # the failure list was cleared
    assert registry.state(KEY) == "closed"


def test_probe_failure_reopens_for_a_full_period() -> None:
    registry, clock = make()
    probe = claim_probe(registry, clock)
    seconds(clock, 5)
    registry.record_failure(probe, K.HTTP_5XX)
    assert registry.state(KEY) == "open"
    seconds(clock, 29)
    assert registry.state(KEY) == "open"
    assert registry.begin_attempt(KEY) is None
    seconds(clock, 1)
    assert registry.state(KEY) == "half_open"
    assert registry.begin_attempt(KEY) is not None


def test_lost_probe_lets_a_new_probe_start_after_the_lease() -> None:
    """AC-64 (d): the lease only decides when another attempt may claim a replacement."""
    registry, clock = make()
    first = claim_probe(registry, clock)
    seconds(clock, LEASE)  # exactly the lease: still in flight
    assert registry.begin_attempt(KEY) is None
    seconds(clock, 1)  # longer than the lease: lost
    assert registry.unavailable_models() == frozenset()
    second = begin(registry)
    assert second.probe and second.claim_id != first.claim_id


def test_abandon_releases_the_probe() -> None:
    registry, clock = make()
    probe = claim_probe(registry, clock)
    registry.abandon_attempt(probe)
    assert registry.state(KEY) == "half_open"
    assert registry.unavailable_models() == frozenset()
    assert registry.begin_attempt(KEY) is not None


def test_abandon_on_unknown_key_is_harmless() -> None:
    registry, _ = make()
    registry.abandon_attempt(AttemptHandle(KEY, 1, probe=True))
    assert registry.state(KEY) == "closed"


@pytest.mark.parametrize(
    "kind", [K.INVALID_OUTPUT, K.TRUNCATED, K.CONTENT_REFUSED, K.BAD_REQUEST, K.MISSING_CREDENTIALS]
)
def test_neutral_outcomes_neither_count_nor_reset(kind: ProviderFailureKind) -> None:
    registry, _ = make()
    fail(registry, count=4)
    fail(registry, count=10, kind=kind)
    assert registry.state(KEY) == "closed"  # did not count
    fail(registry)  # the four earlier counted failures were not reset
    assert registry.state(KEY) == "open"


@pytest.mark.parametrize("kind", [K.INVALID_OUTPUT, K.TRUNCATED, K.CONTENT_REFUSED, K.BAD_REQUEST])
def test_neutral_outcome_releases_a_probe_without_closing_or_reopening(
    kind: ProviderFailureKind,
) -> None:
    registry, clock = make()
    probe = claim_probe(registry, clock)
    registry.record_failure(probe, kind)
    assert registry.state(KEY) == "half_open"
    assert registry.begin_attempt(KEY) is not None


def test_auth_failure_is_permanently_unavailable_and_not_counted() -> None:
    """AC-64 (g): the model stays unavailable for the process and counts nothing."""
    registry, clock = make()
    fail(registry, count=4)
    handle = begin(registry)
    registry.record_failure(handle, K.AUTH_FAILED)
    assert registry.begin_attempt(KEY) is None
    assert registry.unavailable_models() == frozenset({KEY})
    seconds(clock, 10_000)
    assert registry.begin_attempt(KEY) is None
    assert registry.unavailable_models() == frozenset({KEY})
    assert registry.state(KEY) == "open"  # never half-open
    registry.record_success(handle)
    assert registry.begin_attempt(KEY) is None


def test_auth_failure_does_not_affect_the_counted_failures_of_another_key() -> None:
    registry, _ = make()
    registry.record_failure(begin(registry, OTHER), K.AUTH_FAILED)
    fail(registry, count=4)
    assert registry.state(KEY) == "closed"
    assert registry.begin_attempt(KEY) is not None
    assert registry.unavailable_models() == frozenset({OTHER})


def test_keys_are_independent() -> None:
    registry, clock = make()
    open_it(registry)
    assert registry.begin_attempt(OTHER) is not None
    assert registry.state(OTHER) == "closed"
    seconds(clock, 30)
    assert registry.begin_attempt(KEY) is not None
    assert registry.begin_attempt(OTHER) is not None


def test_custom_settings_come_from_the_config() -> None:
    registry, clock = make(
        breaker_failure_threshold=2, breaker_window_seconds=10, breaker_open_seconds=5
    )
    fail(registry, count=2)
    assert registry.state(KEY) == "open"
    seconds(clock, 5)
    assert registry.state(KEY) == "half_open"
    registry.record_success(begin(registry))
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
        registry.record_success(begin(registry))
    assert [(e["state"], e["failure_count"]) for e in logs] == [("open", 5), ("closed", 0)]
    for event in logs:
        assert set(event) == {"event", "log_level", "provider", "model", "state", "failure_count"}
        assert (event["provider"], event["model"]) == KEY


# --- probe ownership and lease (AC-64, D-37) ---


def test_a_released_attempt_cannot_clear_a_newer_probe_claim() -> None:
    """AC-64 (a), (e). A releases its probe by a neutral outcome, E claims a new probe, then A's
    cleanup and late outcomes run (for example after a failed settlement). E must still own the
    probe, and A can neither close nor re-open the breaker."""
    registry, clock = make()
    a = claim_probe(registry, clock)
    registry.record_failure(a, K.INVALID_OUTPUT)  # neutral: A releases the probe
    e = begin(registry)  # E claims a new probe
    assert e.probe
    registry.abandon_attempt(a)  # A's cleanup runs late
    assert registry.begin_attempt(KEY) is None  # F is denied: E still owns the probe
    registry.record_failure(a, K.TIMEOUT)  # A's late outcomes must not re-open or close it
    registry.record_success(a)
    assert registry.state(KEY) == "half_open"
    assert registry.begin_attempt(KEY) is None  # E still owns the probe
    registry.record_success(e)  # and E can still close the breaker
    assert registry.state(KEY) == "closed"


def test_an_attempt_started_while_closed_cannot_release_the_probe_later() -> None:
    """AC-64 (a), (f). A starts while the breaker is closed and holds no probe. The breaker
    opens, goes half-open and C claims the probe. A's cleanup must not release C's claim."""
    registry, clock = make()
    a = begin(registry)  # A starts while closed (not a probe)
    assert not a.probe
    c = claim_probe(registry, clock)
    registry.abandon_attempt(a)  # A raised and cleans up
    assert registry.begin_attempt(KEY) is None  # D is denied: C still owns the probe
    registry.abandon_attempt(c)
    assert registry.begin_attempt(KEY) is not None


def test_an_attempt_started_while_closed_cannot_close_the_breaker_as_a_probe() -> None:
    """AC-64 (f). A non-probe success while the breaker is half-open changes nothing."""
    registry, clock = make()
    a = begin(registry)
    c = claim_probe(registry, clock)
    registry.record_success(a)  # A finishes late: not the probe
    assert registry.state(KEY) == "half_open"
    assert registry.begin_attempt(KEY) is None  # C still owns the probe
    registry.record_success(c)
    assert registry.state(KEY) == "closed"


@pytest.mark.parametrize("kind", [K.TIMEOUT, K.HTTP_5XX, K.RATE_LIMITED])
def test_a_non_probe_counted_failure_cannot_reopen_a_half_open_breaker(
    kind: ProviderFailureKind,
) -> None:
    """AC-64 (f). Counted failures of non-probe handles are ignored while open or half-open."""
    registry, clock = make()
    a = begin(registry)
    c = claim_probe(registry, clock)
    registry.record_failure(a, kind)
    assert registry.state(KEY) == "half_open"
    assert registry.begin_attempt(KEY) is None
    registry.record_failure(c, kind)  # the probe's own failure still re-opens
    assert registry.state(KEY) == "open"


def test_a_non_probe_outcome_cannot_change_an_open_state() -> None:
    """AC-64 (f). Neither a success nor a failure of a non-probe handle moves an open breaker."""
    registry, clock = make()
    a, b = begin(registry), begin(registry)
    open_it(registry)
    registry.record_success(a)
    registry.record_failure(b, K.TIMEOUT)
    assert registry.state(KEY) == "open"
    seconds(clock, 29)
    assert registry.state(KEY) == "open"  # the open period was not extended or cleared
    seconds(clock, 1)
    assert registry.state(KEY) == "half_open"


def test_a_non_probe_success_clears_the_history_only_while_closed() -> None:
    registry, _ = make()
    fail(registry, count=4)
    registry.record_success(begin(registry))  # closed: clears
    fail(registry, count=4)
    assert registry.state(KEY) == "closed"


def test_a_superseded_probe_cannot_record_against_a_newer_probe() -> None:
    """AC-64 (b). After the lease expired E superseded A; A's late outcome has no effect."""
    registry, clock = make()
    a = claim_probe(registry, clock)
    seconds(clock, LEASE + 1)
    e = begin(registry)  # E supersedes A
    assert e.probe and e.claim_id != a.claim_id
    registry.record_success(a)
    assert registry.state(KEY) == "half_open" and registry.begin_attempt(KEY) is None
    registry.record_failure(a, K.TIMEOUT)
    assert registry.state(KEY) == "half_open" and registry.begin_attempt(KEY) is None
    registry.abandon_attempt(a)
    assert registry.begin_attempt(KEY) is None  # E still owns the probe
    registry.record_success(e)
    assert registry.state(KEY) == "closed"


def test_an_unsuperseded_probe_can_complete_after_the_lease_expired_with_success() -> None:
    """AC-64 (c). Lease expiry does not invalidate a handle nobody has superseded (H2)."""
    registry, clock = make()
    a = claim_probe(registry, clock)
    seconds(clock, LEASE + 60)
    assert registry.state(KEY) == "half_open"
    registry.record_success(a)
    assert registry.state(KEY) == "closed"


def test_an_unsuperseded_probe_can_complete_after_the_lease_expired_with_failure() -> None:
    """AC-64 (c). A late failure re-opens the breaker for a full open period."""
    registry, clock = make()
    a = claim_probe(registry, clock)
    seconds(clock, LEASE + 60)
    registry.record_failure(a, K.HTTP_5XX)
    assert registry.state(KEY) == "open"
    seconds(clock, 29)
    assert registry.state(KEY) == "open"
    seconds(clock, 1)
    assert registry.state(KEY) == "half_open"


def test_repeated_cleanup_is_idempotent() -> None:
    """AC-64 (e). Recording then releasing, or releasing twice, changes nothing the second time."""
    registry, clock = make()
    a = claim_probe(registry, clock)
    registry.record_success(a)
    registry.abandon_attempt(a)
    registry.abandon_attempt(a)
    assert registry.state(KEY) == "closed"

    registry2, clock2 = make()
    b = claim_probe(registry2, clock2)
    registry2.record_failure(b, K.TIMEOUT)  # re-opens
    registry2.abandon_attempt(b)
    assert registry2.state(KEY) == "open"

    registry3, clock3 = make()
    c = claim_probe(registry3, clock3)
    registry3.abandon_attempt(c)
    d = begin(registry3)  # a new probe
    registry3.abandon_attempt(c)  # the old handle again: no effect
    registry3.abandon_attempt(c)
    assert registry3.begin_attempt(KEY) is None
    registry3.abandon_attempt(d)
    assert registry3.begin_attempt(KEY) is not None


def test_an_auth_failure_leaves_another_probe_claim_untouched() -> None:
    """AC-64 (g). An auth failure reported by a non-owner does not release the owner's probe,
    and an owner's auth failure releases only its own claim."""
    registry, clock = make()
    a = begin(registry)  # closed-state attempt
    c = claim_probe(registry, clock)
    registry.record_failure(a, K.AUTH_FAILED)
    assert registry.unavailable_models() == frozenset({KEY})
    assert registry._entries[KEY].probe_claim == c.claim_id  # not released by the non-owner
    registry.record_failure(c, K.AUTH_FAILED)
    assert registry._entries[KEY].probe_claim is None  # the owner released its own claim
    assert registry.state(KEY) == "open"


def test_the_probe_lease_is_the_longest_deadline_plus_a_fixed_margin() -> None:
    """AC-64 (h). 330 s with the defaults; independent of the breaker open period."""
    assert AiPlatformConfig(_env_file=None).probe_lease_seconds == LEASE
    assert AiPlatformConfig(_env_file=None, breaker_open_seconds=5).probe_lease_seconds == LEASE
    assert AiPlatformConfig(_env_file=None, breaker_open_seconds=300).probe_lease_seconds == LEASE
    longer = AiPlatformConfig(_env_file=None, batch_deadline_seconds=400)
    assert longer.probe_lease_seconds == 430


def test_the_lease_used_by_the_registry_ignores_the_breaker_open_period() -> None:
    registry, clock = make(breaker_open_seconds=5)
    open_it(registry)
    seconds(clock, 5)
    first = begin(registry)
    assert first.probe
    seconds(clock, LEASE)  # far beyond the 5 s open period, still within the lease
    assert registry.begin_attempt(KEY) is None
    seconds(clock, 1)
    assert registry.begin_attempt(KEY) is not None


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

    assert registry.begin_attempt(KEY) is not None  # probe in flight: excluded again
    result = route(_routing_input(registry.unavailable_models()))
    assert "model-a" not in {c.model for c in result.candidates}
