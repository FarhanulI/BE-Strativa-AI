"""Provider failure policy (spec 10.3, 11, 5.4): pure and deterministic.

INTERNAL module, not exported from the package root. No clock, no I/O, no randomness and no
module-level mutable state. It states what each kind of provider failure means (the error code,
whether the Router falls back, whether it counts toward the circuit breaker, whether it is
repairable, whether it ends the request) and the attempt and deadline arithmetic. Running the
attempts, and keeping the billing mode inside one mode (INV-29), belong to the orchestrator and
the Router, not here.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from enum import StrEnum

from app.ai_platform.errors import (
    AiContentRefused,
    AiErrorCode,
    AiOutputInvalid,
    AiProviderNotConfigured,
    AiProviderUnavailable,
)


class ProviderFailureKind(StrEnum):
    TIMEOUT = "timeout"
    CONNECTION_ERROR = "connection_error"
    HTTP_5XX = "http_5xx"
    RATE_LIMITED = "rate_limited"
    AUTH_FAILED = "auth_failed"
    BAD_REQUEST = "bad_request"
    CONTENT_REFUSED = "content_refused"
    TRUNCATED = "truncated"
    INVALID_OUTPUT = "invalid_output"
    MISSING_CREDENTIALS = "missing_credentials"


@dataclass(frozen=True, slots=True)
class FailureClass:
    """One row of the classification table in spec 10.3."""

    error_code: AiErrorCode
    falls_back: bool
    counts_toward_breaker: bool
    marks_unavailable_for_process: bool
    repairable: bool
    terminal_on_first_failure: bool
    # False only for missing credentials: no reservation and no provider call.
    makes_provider_call_counted: bool = True
    max_attempts_note: str | None = None


@dataclass(frozen=True, slots=True)
class FinalError:
    """The outcome when every candidate that was tried has ended in failure."""

    error_class: type[Exception]
    error_code: AiErrorCode


# Request-level codes that are not a provider failure and never fall back (spec 10.3).
NEVER_FALL_BACK_CODES: frozenset[AiErrorCode] = frozenset(
    {
        AiErrorCode.BUDGET_EXCEEDED,
        AiErrorCode.NO_ROUTE,
        AiErrorCode.INPUT_TOO_LARGE,
        AiErrorCode.LEASE_LOST,
        AiErrorCode.EXECUTION_ABANDONED,
    }
)

_ONE_PER_MODEL = "one attempt per model; at most max_provider_attempts distinct models"


def classify(kind: ProviderFailureKind) -> FailureClass:
    """The classification row for a failure kind (spec 10.3)."""
    match kind:
        case ProviderFailureKind.TIMEOUT:
            return FailureClass(
                error_code=AiErrorCode.PROVIDER_TIMEOUT,
                falls_back=True,
                counts_toward_breaker=True,
                marks_unavailable_for_process=False,
                repairable=False,
                terminal_on_first_failure=False,
                max_attempts_note=_ONE_PER_MODEL + "; bounded by the request deadline",
            )
        case ProviderFailureKind.CONNECTION_ERROR | ProviderFailureKind.HTTP_5XX:
            return FailureClass(
                error_code=AiErrorCode.PROVIDER_UNAVAILABLE,
                falls_back=True,
                counts_toward_breaker=True,
                marks_unavailable_for_process=False,
                repairable=False,
                terminal_on_first_failure=False,
                max_attempts_note=_ONE_PER_MODEL,
            )
        case ProviderFailureKind.RATE_LIMITED:
            # The same-billing-mode restriction (INV-29) is applied by the Router.
            return FailureClass(
                error_code=AiErrorCode.PROVIDER_RATE_LIMITED,
                falls_back=True,
                counts_toward_breaker=True,
                marks_unavailable_for_process=False,
                repairable=False,
                terminal_on_first_failure=False,
                max_attempts_note=_ONE_PER_MODEL,
            )
        case ProviderFailureKind.AUTH_FAILED:
            return FailureClass(
                error_code=AiErrorCode.PROVIDER_AUTH_FAILED,
                falls_back=True,
                counts_toward_breaker=False,
                marks_unavailable_for_process=True,
                repairable=False,
                terminal_on_first_failure=False,
                max_attempts_note=_ONE_PER_MODEL,
            )
        case ProviderFailureKind.BAD_REQUEST:
            return FailureClass(
                error_code=AiErrorCode.PROVIDER_BAD_REQUEST,
                falls_back=False,
                counts_toward_breaker=False,
                marks_unavailable_for_process=False,
                repairable=False,
                terminal_on_first_failure=True,
                max_attempts_note="one attempt",
            )
        case ProviderFailureKind.CONTENT_REFUSED:
            return FailureClass(
                error_code=AiErrorCode.CONTENT_REFUSED,
                falls_back=False,
                counts_toward_breaker=False,
                marks_unavailable_for_process=False,
                repairable=False,
                terminal_on_first_failure=True,
                max_attempts_note="one attempt",
            )
        case ProviderFailureKind.TRUNCATED:
            return FailureClass(
                error_code=AiErrorCode.OUTPUT_TRUNCATED,
                falls_back=True,
                counts_toward_breaker=False,
                marks_unavailable_for_process=False,
                repairable=False,
                terminal_on_first_failure=False,
                max_attempts_note=_ONE_PER_MODEL,
            )
        case ProviderFailureKind.INVALID_OUTPUT:
            return FailureClass(
                error_code=AiErrorCode.OUTPUT_INVALID,
                falls_back=True,
                counts_toward_breaker=False,
                marks_unavailable_for_process=False,
                repairable=True,
                terminal_on_first_failure=False,
                max_attempts_note="repair calls to the same model, then fall back",
            )
        case ProviderFailureKind.MISSING_CREDENTIALS:
            return FailureClass(
                error_code=AiErrorCode.PROVIDER_NOT_CONFIGURED,
                falls_back=False,
                counts_toward_breaker=False,
                marks_unavailable_for_process=False,
                repairable=False,
                terminal_on_first_failure=True,
                makes_provider_call_counted=False,
                max_attempts_note="zero calls, no reservation",
            )


def terminal_error_class(kind: ProviderFailureKind) -> type[Exception]:
    """The error raised when this failure ends the request at once. ValueError otherwise."""
    match kind:
        case ProviderFailureKind.BAD_REQUEST:
            return AiProviderUnavailable
        case ProviderFailureKind.CONTENT_REFUSED:
            return AiContentRefused
        case ProviderFailureKind.MISSING_CREDENTIALS:
            return AiProviderNotConfigured
        case _:
            raise ValueError("this failure kind is not terminal")


def final_error(failures: Sequence[ProviderFailureKind]) -> FinalError:
    """The error when all candidates are exhausted (D-32).

    ``failures`` holds one entry per candidate that was tried and ended, in order. The raised
    class is ``AiOutputInvalid`` only when every entry is an invalid output; otherwise
    ``AiProviderUnavailable``. The persisted code is the code of the last failure.
    """
    if not failures:
        raise ValueError("at least one failure is required")
    error_class: type[Exception] = (
        AiOutputInvalid
        if all(kind is ProviderFailureKind.INVALID_OUTPUT for kind in failures)
        else AiProviderUnavailable
    )
    return FinalError(error_class=error_class, error_code=classify(failures[-1]).error_code)


def _require_non_negative(**values: int) -> None:
    for value in values.values():
        if isinstance(value, bool) or not isinstance(value, int) or value < 0:
            raise ValueError("values must be non-negative integers")


def next_attempt_allowed(
    attempts_made: int,
    max_provider_attempts: int,
    remaining_ms: int,
    next_latency_p50_ms: int,
) -> bool:
    """Whether another candidate may be tried (10.3): attempt cap and request deadline.

    False when the attempt cap is reached, or when the remaining time is below the next
    candidate's median latency (equal is allowed).
    """
    _require_non_negative(
        attempts_made=attempts_made,
        max_provider_attempts=max_provider_attempts,
        remaining_ms=remaining_ms,
        next_latency_p50_ms=next_latency_p50_ms,
    )
    if attempts_made >= max_provider_attempts:
        return False
    return remaining_ms >= next_latency_p50_ms


def deadline_stop_error_code() -> AiErrorCode:
    """The code a request fails with when the deadline stops further attempts (10.3)."""
    return AiErrorCode.PROVIDER_TIMEOUT


def max_total_calls(max_provider_attempts: int, max_repair_attempts: int) -> int:
    """The hard cap on provider calls per request (INV-9)."""
    _require_non_negative(
        max_provider_attempts=max_provider_attempts, max_repair_attempts=max_repair_attempts
    )
    return max_provider_attempts * (1 + max_repair_attempts)
