"""The internal provider boundary (spec 5.5, 10.3, 11, 11.1, 12.1; decisions D-22, D-25, D-31).

INTERNAL module, not exported from the package root. It defines the only shapes that cross
between the orchestrator and a provider implementation: a request, a response, one failure
exception and the ``ProviderClient`` protocol. Nothing here names a provider or a model as a
type, reads the environment or the clock, or touches the network.

There is deliberately no field for tools, functions, a tool choice or a model override
(INV-24, INV-2). The provider key is passed explicitly on every call (D-22).
"""

from __future__ import annotations

from typing import Literal, Protocol

from pydantic import BaseModel, ConfigDict, Field, SecretStr

from app.ai_platform.failure_policy import ProviderFailureKind

_STRICT = ConfigDict(frozen=True, extra="forbid", strict=True)


class ChatMessage(BaseModel):
    """One message. The ``assistant`` role only carries invalid output in a repair call (11)."""

    model_config = _STRICT

    role: Literal["system", "user", "assistant"]
    content: str


class ProviderGenerationRequest(BaseModel):
    model_config = _STRICT

    provider: str = Field(min_length=1)
    model: str = Field(min_length=1)
    messages: tuple[ChatMessage, ...] = Field(min_length=1)
    response_mode: Literal["json_schema", "json_mode"]
    # The JSON schema of the output model. Must be JSON-serialisable.
    response_schema: dict[str, object]
    # Exactly the candidate's effective_max_output_units (D-31).
    max_output_units: int = Field(ge=1)
    timeout_seconds: float = Field(gt=0)


class ProviderGenerationResponse(BaseModel):
    model_config = _STRICT

    raw_text: str
    input_units: int | None = Field(default=None, ge=0)
    output_units: int | None = Field(default=None, ge=0)
    finish_reason: str


_FIXED_MESSAGES: dict[ProviderFailureKind, str] = {
    ProviderFailureKind.TIMEOUT: "the provider call timed out",
    ProviderFailureKind.CONNECTION_ERROR: "the provider connection failed",
    ProviderFailureKind.HTTP_5XX: "the provider reported a server error",
    ProviderFailureKind.RATE_LIMITED: "the provider rate limit or quota was reached",
    ProviderFailureKind.AUTH_FAILED: "the provider rejected the credentials",
    ProviderFailureKind.BAD_REQUEST: "the provider rejected the request",
    ProviderFailureKind.CONTENT_REFUSED: "the provider declined to process the content",
    ProviderFailureKind.TRUNCATED: "the provider output was truncated",
    ProviderFailureKind.INVALID_OUTPUT: "the provider output was invalid",
    ProviderFailureKind.MISSING_CREDENTIALS: "the provider credentials are missing",
}


def _check_units(value: int | None) -> int | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError("reported units must be a non-negative integer or None")
    return value


class ProviderCallError(Exception):
    """The only failure signal a provider implementation raises.

    The message is fixed text derived from the kind, never provider text. The units are the
    usage the provider reported for the failed call, when it reported any (12.1).
    """

    def __init__(
        self,
        kind: ProviderFailureKind,
        input_units: int | None = None,
        output_units: int | None = None,
    ) -> None:
        super().__init__(_FIXED_MESSAGES[kind])
        self.kind = kind
        self.input_units = _check_units(input_units)
        self.output_units = _check_units(output_units)


class ProviderClient(Protocol):
    """Generation boundary. The key is passed per call and never read from the environment."""

    async def generate(
        self, request: ProviderGenerationRequest, *, api_key: SecretStr | None
    ) -> ProviderGenerationResponse: ...


def failure_kind_for_finish_reason(finish_reason: str) -> ProviderFailureKind | None:
    """Maps a finish reason to a failure kind. Anything unrecognised is not a failure here."""
    if finish_reason == "length":
        return ProviderFailureKind.TRUNCATED
    if finish_reason == "content_filter":
        return ProviderFailureKind.CONTENT_REFUSED
    return None
