"""Circuit breaker per (provider, model) (spec 10.4, D-37). INTERNAL module.

In-process only, per worker, guarded by one lock. All time comes from the injected ``Clock``
(INV-22); this module never reads the system time itself. States:

- closed: attempts are allowed.
- open: ``now < open_until``; attempts are refused.
- half_open: ``now >= open_until``; exactly one caller is let through as the probe.

``begin_attempt`` returns an ``AttemptHandle`` (or ``None`` when the attempt is denied, D-35).
Ownership decides whose outcome counts (D-37): only the handle that currently owns the half-open
probe can close the breaker, re-open it or release the probe. Any other handle (a superseded
probe, a completed one, or an attempt that started while the breaker was closed) changes no
state, except that a closed breaker still takes its failure history. Time never invalidates a
probe: after ``probe_lease_seconds`` without an outcome another attempt may claim a new probe,
which makes the earlier handle stale. A late outcome of an unsuperseded probe is applied.

The breaker is an availability aid, not a correctness mechanism: budgets and ledgers live in
the database.
"""

from __future__ import annotations

import itertools
import threading
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any, Literal

import structlog

from app.ai_platform.config import AiPlatformConfig
from app.ai_platform.failure_policy import ProviderFailureKind, classify
from app.core import Clock

BreakerState = Literal["closed", "open", "half_open"]
ModelKey = tuple[str, str]


def _log() -> Any:
    """A fresh bound logger per use, so log capture and later logging configuration apply."""
    return structlog.get_logger("app.ai_platform.circuit_breaker")


@dataclass(frozen=True, slots=True)
class AttemptHandle:
    """One admitted attempt. ``probe`` is true only for the single half-open probe.

    ``claim_id`` is unique per registry. It is deliberately not named after a token (INV-18).
    """

    key: ModelKey
    claim_id: int
    probe: bool


@dataclass(slots=True)
class _Entry:
    failures: list[datetime] = field(default_factory=list)
    open_until: datetime | None = None
    probe_started: datetime | None = None
    probe_claim: int | None = None


class CircuitBreakerRegistry:
    def __init__(self, clock: Clock, config: AiPlatformConfig) -> None:
        self._clock = clock
        self._threshold = config.breaker_failure_threshold
        self._window = timedelta(seconds=config.breaker_window_seconds)
        self._open_for = timedelta(seconds=config.breaker_open_seconds)
        self._lease = timedelta(seconds=config.probe_lease_seconds)
        self._lock = threading.Lock()
        self._claims = itertools.count(1)
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
        """A probe is claimed and its lease has not expired (only this lets a new claim wait)."""
        started = entry.probe_started
        return started is not None and now - started <= self._lease

    @staticmethod
    def _owns(entry: _Entry, handle: AttemptHandle) -> bool:
        return handle.probe and entry.probe_claim == handle.claim_id

    @staticmethod
    def _release(entry: _Entry) -> None:
        entry.probe_started = None
        entry.probe_claim = None

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

    def begin_attempt(self, key: ModelKey) -> AttemptHandle | None:
        """Admit an attempt, or return ``None`` when the breaker denies it (D-35)."""
        with self._lock:
            now = self._clock.now()
            state = self._state_of(key, now)
            if key in self._auth_failed or state == "open":
                return None
            claim_id = next(self._claims)
            if state == "closed":
                return AttemptHandle(key, claim_id, probe=False)
            entry = self._entry(key)
            if self._probe_in_flight(entry, now):
                return None
            # Half-open with no live probe: claim it. A claim whose lease expired is superseded.
            entry.probe_started = now
            entry.probe_claim = claim_id
            return AttemptHandle(key, claim_id, probe=True)

    def record_success(self, handle: AttemptHandle) -> None:
        closed = False
        with self._lock:
            entry = self._entry(handle.key)
            if self._owns(entry, handle):
                entry.failures = []
                entry.open_until = None
                self._release(entry)
                closed = True
            elif self._state_of(handle.key, self._clock.now()) == "closed":
                entry.failures = []  # a non-probe success clears the history only while closed
        if closed:
            self._emit(handle.key, "closed", 0)

    def record_failure(self, handle: AttemptHandle, kind: ProviderFailureKind) -> None:
        failure_class = classify(kind)
        opened_with: int | None = None
        with self._lock:
            now = self._clock.now()
            entry = self._entry(handle.key)
            owner = self._owns(entry, handle)
            if failure_class.marks_unavailable_for_process:
                # A process-wide fact about the model, whichever handle reports it. It releases
                # only the reporting handle's own probe claim, never another handle's.
                self._auth_failed.add(handle.key)
                if owner:
                    self._release(entry)
                return
            state = self._state_of(handle.key, now)
            if failure_class.counts_toward_breaker:
                if owner:
                    entry.failures.append(now)
                    self._prune(entry, now)
                    entry.open_until = now + self._open_for
                    self._release(entry)
                    opened_with = len(entry.failures)
                elif state == "closed":
                    entry.failures.append(now)
                    self._prune(entry, now)
                    if len(entry.failures) >= self._threshold:
                        entry.open_until = now + self._open_for
                        opened_with = len(entry.failures)
                # Any other handle while open or half-open: no change (D-37).
            elif owner:
                # A neutral outcome neither closes nor reopens; it only releases the probe.
                self._release(entry)
        if opened_with is not None:
            self._emit(handle.key, "open", opened_with)

    def abandon_attempt(self, handle: AttemptHandle) -> None:
        """Release the probe if (and only if) this handle currently owns it. Idempotent."""
        with self._lock:
            entry = self._entries.get(handle.key)
            if entry is not None and self._owns(entry, handle):
                self._release(entry)

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
