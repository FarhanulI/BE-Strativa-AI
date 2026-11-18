"""Circuit breaker per (provider, model) (spec 10.4). INTERNAL module.

In-process only, per worker, guarded by one lock. All time comes from the injected ``Clock``
(INV-22); this module never reads the system time itself. States:

- closed: attempts are allowed.
- open: ``now < open_until``; attempts are refused.
- half_open: ``now >= open_until``; exactly one caller is let through as the probe. A probe
  with no outcome for longer than ``breaker_open_seconds`` is treated as lost.

The breaker is an availability aid, not a correctness mechanism: budgets and ledgers live in
the database.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any, Literal

import structlog

from app.ai_platform.config import AiPlatformConfig
from app.ai_platform.failure_policy import ProviderFailureKind, classify
from app.core.clock import Clock

BreakerState = Literal["closed", "open", "half_open"]
ModelKey = tuple[str, str]


def _log() -> Any:
    """A fresh bound logger per use, so log capture and later logging configuration apply."""
    return structlog.get_logger("app.ai_platform.circuit_breaker")


@dataclass(slots=True)
class _Entry:
    failures: list[datetime] = field(default_factory=list)
    open_until: datetime | None = None
    probe_started: datetime | None = None


class CircuitBreakerRegistry:
    def __init__(self, clock: Clock, config: AiPlatformConfig) -> None:
        self._clock = clock
        self._threshold = config.breaker_failure_threshold
        self._window = timedelta(seconds=config.breaker_window_seconds)
        self._open_for = timedelta(seconds=config.breaker_open_seconds)
        self._lock = threading.Lock()
        self._entries: dict[ModelKey, _Entry] = {}
        self._auth_failed: set[ModelKey] = set()

    # --- internal helpers (the lock is held by the callers) ---

    def _entry(self, key: ModelKey) -> _Entry:
        entry = self._entries.get(key)
        if entry is None:
            entry = _Entry()
            self._entries[key] = entry
        return entry

    def _state_of(self, key: ModelKey, now: datetime) -> BreakerState:
        if key in self._auth_failed:
            return "open"
        entry = self._entries.get(key)
        if entry is None or entry.open_until is None:
            return "closed"
        return "open" if now < entry.open_until else "half_open"

    def _probe_in_flight(self, entry: _Entry, now: datetime) -> bool:
        started = entry.probe_started
        return started is not None and now - started <= self._open_for

    def _prune(self, entry: _Entry, now: datetime) -> None:
        entry.failures = [at for at in entry.failures if now - at <= self._window]

    @staticmethod
    def _emit(key: ModelKey, state: str, failure_count: int) -> None:
        _log().info(
            "ai_platform.circuit_breaker.transition",
            provider=key[0],
            model=key[1],
            state=state,
            failure_count=failure_count,
        )

    # --- public interface ---

    def begin_attempt(self, key: ModelKey) -> bool:
        with self._lock:
            now = self._clock.now()
            state = self._state_of(key, now)
            if key in self._auth_failed or state == "open":
                return False
            if state == "closed":
                return True
            entry = self._entry(key)
            if self._probe_in_flight(entry, now):
                return False
            entry.probe_started = now
            return True

    def record_success(self, key: ModelKey) -> None:
        closed = False
        with self._lock:
            now = self._clock.now()
            entry = self._entry(key)
            entry.failures = []
            if self._state_of(key, now) == "half_open" and self._probe_in_flight(entry, now):
                entry.open_until = None
                entry.probe_started = None
                closed = True
        if closed:
            self._emit(key, "closed", 0)

    def record_failure(self, key: ModelKey, kind: ProviderFailureKind) -> None:
        failure_class = classify(kind)
        opened_with: int | None = None
        with self._lock:
            now = self._clock.now()
            if failure_class.marks_unavailable_for_process:
                self._auth_failed.add(key)
                return
            entry = self._entry(key)
            state = self._state_of(key, now)
            probing = state == "half_open" and self._probe_in_flight(entry, now)
            if failure_class.counts_toward_breaker:
                entry.failures.append(now)
                self._prune(entry, now)
                if probing:
                    entry.open_until = now + self._open_for
                    entry.probe_started = None
                    opened_with = len(entry.failures)
                elif state == "closed" and len(entry.failures) >= self._threshold:
                    entry.open_until = now + self._open_for
                    opened_with = len(entry.failures)
            elif probing:
                # A neutral outcome neither closes nor reopens; it only releases the probe.
                entry.probe_started = None
        if opened_with is not None:
            self._emit(key, "open", opened_with)

    def abandon_attempt(self, key: ModelKey) -> None:
        with self._lock:
            entry = self._entries.get(key)
            if entry is not None:
                entry.probe_started = None

    def unavailable_models(self) -> frozenset[ModelKey]:
        with self._lock:
            now = self._clock.now()
            result = set(self._auth_failed)
            for key, entry in self._entries.items():
                state = self._state_of(key, now)
                if state == "open" or (state == "half_open" and self._probe_in_flight(entry, now)):
                    result.add(key)
            return frozenset(result)

    def state(self, key: ModelKey) -> BreakerState:
        with self._lock:
            return self._state_of(key, self._clock.now())
