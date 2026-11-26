"""Scripted in-memory provider for tests (spec 5.5).

Exported from the package root with ``ScriptedResponse`` so other modules' tests can drive the
AI platform without a network. It never reads the environment, never touches the network and
never logs content. It records the exact request and the exact ``api_key`` argument of every call
so tests can assert the request shape (11.1) and that keys are passed explicitly (D-22).
"""

from __future__ import annotations

import asyncio
from collections import deque
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass

from pydantic import SecretStr

from app.ai_platform.failure_policy import ProviderFailureKind
from app.ai_platform.provider import (
    ProviderCallError,
    ProviderGenerationRequest,
    ProviderGenerationResponse,
)

_EXHAUSTED_MESSAGE = "FakeAiProvider script is exhausted"


@dataclass(frozen=True, slots=True)
class ScriptedResponse:
    """One scripted outcome: a success (``failure_kind`` is None) or a failure."""

    raw_text: str = ""
    input_units: int | None = None
    output_units: int | None = None
    finish_reason: str = "stop"
    failure_kind: ProviderFailureKind | None = None
    delay_seconds: float = 0.0

    def __post_init__(self) -> None:
        if self.delay_seconds < 0:
            raise ValueError("delay_seconds must not be negative")

    @classmethod
    def ok(
        cls,
        raw_text: str,
        *,
        input_units: int | None = None,
        output_units: int | None = None,
        finish_reason: str = "stop",
        delay_seconds: float = 0.0,
    ) -> ScriptedResponse:
        return cls(
            raw_text=raw_text,
            input_units=input_units,
            output_units=output_units,
            finish_reason=finish_reason,
            delay_seconds=delay_seconds,
        )

    @classmethod
    def fail(
        cls,
        kind: ProviderFailureKind,
        *,
        input_units: int | None = None,
        output_units: int | None = None,
        delay_seconds: float = 0.0,
    ) -> ScriptedResponse:
        return cls(
            input_units=input_units,
            output_units=output_units,
            failure_kind=kind,
            delay_seconds=delay_seconds,
        )


@dataclass(frozen=True, slots=True)
class RecordedCall:
    """A call as the provider received it: the request and the exact api_key argument."""

    request: ProviderGenerationRequest
    api_key: SecretStr | None


class FakeAiProvider:
    """Implements ``ProviderClient``.

    Selection order for each call: a per-``(provider, model)`` FIFO when one exists for the
    request's pair (it is then the only source for that pair), otherwise the responder callable
    when one was given, otherwise the global FIFO. An exhausted FIFO raises ``AssertionError``.
    """

    def __init__(
        self,
        script: Iterable[ScriptedResponse] = (),
        *,
        per_model: Mapping[tuple[str, str], Iterable[ScriptedResponse]] | None = None,
        responder: Callable[[ProviderGenerationRequest], ScriptedResponse] | None = None,
    ) -> None:
        self._global: deque[ScriptedResponse] = deque(script)
        self._per_model: dict[tuple[str, str], deque[ScriptedResponse]] = {
            key: deque(items) for key, items in (per_model or {}).items()
        }
        if responder is not None and self._global:
            raise ValueError("give either a script or a responder, not both")
        self._responder = responder
        self._calls: list[RecordedCall] = []

    @property
    def calls(self) -> tuple[RecordedCall, ...]:
        """Every call received so far, in order (read-only)."""
        return tuple(self._calls)

    def _next(self, request: ProviderGenerationRequest) -> ScriptedResponse:
        queue = self._per_model.get((request.provider, request.model))
        if queue is None:
            if self._responder is not None:
                return self._responder(request)
            queue = self._global
        if not queue:
            raise AssertionError(_EXHAUSTED_MESSAGE)
        return queue.popleft()

    async def generate(
        self, request: ProviderGenerationRequest, *, api_key: SecretStr | None
    ) -> ProviderGenerationResponse:
        # Recorded before anything can fail or wait, so a timed-out call is still visible.
        self._calls.append(RecordedCall(request=request, api_key=api_key))
        scripted = self._next(request)
        if scripted.delay_seconds > 0:
            await asyncio.sleep(scripted.delay_seconds)
        if scripted.failure_kind is not None:
            raise ProviderCallError(
                scripted.failure_kind, scripted.input_units, scripted.output_units
            )
        return ProviderGenerationResponse(
            raw_text=scripted.raw_text,
            input_units=scripted.input_units,
            output_units=scripted.output_units,
            finish_reason=scripted.finish_reason,
        )
