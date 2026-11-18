"""Provider boundary types (spec 5.5, 10.3; INV-2, INV-24). Pure, no I/O."""

from __future__ import annotations

import json

import pytest
from pydantic import BaseModel, ValidationError

from app.ai_platform.failure_policy import ProviderFailureKind
from app.ai_platform.provider import (
    ChatMessage,
    ProviderCallError,
    ProviderClient,
    ProviderGenerationRequest,
    ProviderGenerationResponse,
    failure_kind_for_finish_reason,
)

TYPES: list[type[BaseModel]] = [ChatMessage, ProviderGenerationRequest, ProviderGenerationResponse]
FORBIDDEN_FIELDS = {"tools", "functions", "tool_choice", "model_override", "function_call"}


def _request(**overrides: object) -> ProviderGenerationRequest:
    values: dict[str, object] = {
        "provider": "p",
        "model": "m",
        "messages": (ChatMessage(role="system", content="s"),),
        "response_mode": "json_schema",
        "response_schema": {"type": "object"},
        "max_output_units": 10,
        "timeout_seconds": 1.5,
    }
    values.update(overrides)
    return ProviderGenerationRequest(**values)  # type: ignore[arg-type]


@pytest.mark.parametrize("cls", TYPES, ids=lambda c: c.__name__)
def test_no_tool_or_override_field_anywhere(cls: type[BaseModel]) -> None:
    names = {name.lower() for name in cls.model_fields}
    assert not names & FORBIDDEN_FIELDS
    assert not any("tool" in name or "function" in name or "override" in name for name in names)


@pytest.mark.parametrize("name", sorted(FORBIDDEN_FIELDS))
def test_request_rejects_tool_like_extra_fields(name: str) -> None:
    with pytest.raises(ValidationError):
        _request(**{name: 1})


def test_types_are_frozen_and_strict() -> None:
    request = _request()
    with pytest.raises(ValidationError):
        request.model = "other"  # type: ignore[misc]
    with pytest.raises(ValidationError):
        _request(max_output_units="10")
    with pytest.raises(ValidationError):
        _request(max_output_units=True)
    with pytest.raises(ValidationError):
        _request(messages=[ChatMessage(role="system", content="s")])  # a list, not a tuple
    with pytest.raises(ValidationError):
        ChatMessage(role="tool", content="x")  # type: ignore[arg-type]


@pytest.mark.parametrize(
    "overrides",
    [
        {"max_output_units": 0},
        {"timeout_seconds": 0},
        {"timeout_seconds": -1.0},
        {"response_mode": "text"},
        {"messages": ()},
        {"provider": ""},
        {"model": ""},
    ],
)
def test_request_bounds(overrides: dict[str, object]) -> None:
    with pytest.raises(ValidationError):
        _request(**overrides)


def test_request_schema_is_json_serialisable() -> None:
    json.dumps(_request().response_schema)


def test_response_rules() -> None:
    ok = ProviderGenerationResponse(
        raw_text="x", input_units=1, output_units=2, finish_reason="stop"
    )
    assert (ok.input_units, ok.output_units) == (1, 2)
    assert ProviderGenerationResponse(raw_text="x", finish_reason="stop").input_units is None
    with pytest.raises(ValidationError):
        ProviderGenerationResponse(raw_text="x", input_units=-1, finish_reason="stop")
    with pytest.raises(ValidationError):
        ProviderGenerationResponse(raw_text="x", finish_reason="stop", extra=1)  # type: ignore[call-arg]


@pytest.mark.parametrize("kind", list(ProviderFailureKind))
def test_provider_call_error_message_is_fixed_per_kind(kind: ProviderFailureKind) -> None:
    error = ProviderCallError(kind)
    assert str(error) == str(ProviderCallError(kind, 1, 2))
    assert str(error)
    assert error.kind is kind
    assert (error.input_units, error.output_units) == (None, None)


def test_provider_call_error_messages_are_distinct_and_carry_reported_units() -> None:
    messages = {str(ProviderCallError(kind)) for kind in ProviderFailureKind}
    assert len(messages) == len(ProviderFailureKind)
    error = ProviderCallError(ProviderFailureKind.HTTP_5XX, input_units=3, output_units=0)
    assert (error.input_units, error.output_units) == (3, 0)


@pytest.mark.parametrize("bad", [-1, True, 1.5, "1"])
def test_provider_call_error_rejects_bad_units(bad: object) -> None:
    with pytest.raises(ValueError):
        ProviderCallError(ProviderFailureKind.TIMEOUT, input_units=bad)  # type: ignore[arg-type]


@pytest.mark.parametrize(
    ("reason", "kind"),
    [
        ("length", ProviderFailureKind.TRUNCATED),
        ("content_filter", ProviderFailureKind.CONTENT_REFUSED),
        ("stop", None),
        ("tool_calls", None),
        ("", None),
        ("LENGTH", None),
    ],
)
def test_failure_kind_for_finish_reason(reason: str, kind: ProviderFailureKind | None) -> None:
    assert failure_kind_for_finish_reason(reason) is kind


def test_protocol_takes_an_explicit_api_key() -> None:
    import inspect

    parameters = inspect.signature(ProviderClient.generate).parameters
    assert parameters["api_key"].kind is inspect.Parameter.KEYWORD_ONLY
    assert parameters["api_key"].default is inspect.Parameter.empty
