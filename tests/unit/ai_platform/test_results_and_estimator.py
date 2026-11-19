"""Result types (spec 5.2) and the unit-estimator interface (5b-1)."""

from __future__ import annotations

import inspect
from typing import Any, get_args
from uuid import uuid4

import pytest
from pydantic import BaseModel, ConfigDict, ValidationError

import app.ai_platform as ai_platform
import app.ai_platform.estimator as estimator_module
import app.ai_platform.results as results_module
from app.ai_platform import AiRequestStatus, AiTaskName, AiTaskResult, AiUsageSummary
from app.ai_platform.estimator import UnitEstimator
from app.ai_platform.provider import ChatMessage
from tests.helpers.char_estimator import CharCountEstimator

FORBIDDEN_FIELD_FRAGMENTS = ("provider", "model", "token", "gemini", "perplexity", "litellm")


class _Output(BaseModel):
    model_config = ConfigDict(extra="forbid")
    value: int


def _usage() -> AiUsageSummary:
    return AiUsageSummary(input_units=1, output_units=2, cost_micro_usd=3, call_count=1)


def _result(**overrides: Any) -> AiTaskResult:
    data: dict[str, Any] = {
        "request_id": uuid4(),
        "task": AiTaskName.GENERATE_HOOK_VARIATIONS,
        "output": _Output(value=1),
        "output_schema_name": "HookVariationSet",
        "output_schema_version": 1,
        "usage": _usage(),
        "routing_id": uuid4(),
    }
    data.update(overrides)
    return AiTaskResult(**data)


def _status(**overrides: Any) -> AiRequestStatus:
    data: dict[str, Any] = {
        "request_id": uuid4(),
        "task": AiTaskName.GENERATE_HOOK_VARIATIONS,
        "status": "running",
        "error_code": None,
        "usage": _usage(),
    }
    data.update(overrides)
    return AiRequestStatus(**data)


def test_exported_from_the_package_root() -> None:
    assert ai_platform.AiTaskResult is AiTaskResult
    assert ai_platform.AiRequestStatus is AiRequestStatus
    assert {"AiTaskResult", "AiRequestStatus"} <= set(ai_platform.__all__)


def test_task_result_is_frozen_and_keeps_the_output_instance() -> None:
    output = _Output(value=7)
    result = _result(output=output)
    assert result.output is output
    with pytest.raises(ValidationError):
        result.output_schema_name = "x"  # type: ignore[misc]


def test_task_result_forbids_extra_fields() -> None:
    with pytest.raises(ValidationError):
        _result(provider="x")
    with pytest.raises(ValidationError):
        _result(model="x")


def test_task_result_rejects_a_non_model_output_and_a_bad_version() -> None:
    with pytest.raises(ValidationError):
        _result(output={"value": 1})
    with pytest.raises(ValidationError):
        _result(output_schema_version=0)


def test_request_status_is_frozen_forbids_extras_and_has_no_output() -> None:
    status = _status(status="failed", error_code="budget_exceeded")
    with pytest.raises(ValidationError):
        status.status = "running"  # type: ignore[misc]
    with pytest.raises(ValidationError):
        _status(output=_Output(value=1))
    assert "output" not in AiRequestStatus.model_fields


@pytest.mark.parametrize("value", ["queued", "running", "succeeded", "failed"])
def test_status_literal_accepts_the_four_values(value: str) -> None:
    assert _status(status=value).status == value


@pytest.mark.parametrize("value", ["done", "RUNNING", "abandoned", "", None])
def test_status_literal_rejects_anything_else(value: Any) -> None:
    with pytest.raises(ValidationError):
        _status(status=value)


def test_status_literal_matches_the_database_statuses() -> None:
    assert set(get_args(results_module.RequestStatusName)) == {
        "queued",
        "running",
        "succeeded",
        "failed",
    }


@pytest.mark.parametrize("model", [AiTaskResult, AiRequestStatus])
def test_no_provider_model_or_token_field(model: type[BaseModel]) -> None:
    for name in model.model_fields:
        lowered = name.lower()
        assert not any(fragment in lowered for fragment in FORBIDDEN_FIELD_FRAGMENTS), name


@pytest.mark.parametrize("module", [results_module, estimator_module])
def test_no_token_in_names(module: Any) -> None:
    names = {n for n in vars(module) if not n.startswith("__")}
    for _, cls in inspect.getmembers(module, inspect.isclass):
        if cls.__module__ == module.__name__:
            names |= {n for n in vars(cls) if not n.startswith("__")}
            names |= set(getattr(cls, "model_fields", {}))
    assert [n for n in names if "token" in n.lower()] == []


# --- estimator ---


def test_char_estimator_conforms_to_the_protocol() -> None:
    assert isinstance(CharCountEstimator(), UnitEstimator)


def test_protocol_rejects_an_object_missing_a_method() -> None:
    class Partial:
        def estimate_text(self, text: str) -> int:
            return 0

    assert not isinstance(Partial(), UnitEstimator)


@pytest.mark.parametrize(
    ("text", "units"), [("", 0), ("a", 1), ("abcd", 1), ("abcde", 2), ("x" * 40, 10)]
)
def test_char_estimator_text(text: str, units: int) -> None:
    assert CharCountEstimator().estimate_text(text) == units


def test_char_estimator_counts_message_contents() -> None:
    messages = [
        ChatMessage(role="system", content="abcd"),
        ChatMessage(role="user", content="efghi"),
    ]
    assert CharCountEstimator().estimate_messages(messages) == 3  # ceil(9 / 4)
    assert CharCountEstimator().estimate_messages(messages[:1]) == 1
    assert isinstance(CharCountEstimator().estimate_messages(messages), int)


def test_estimator_module_has_no_default_implementation() -> None:
    classes = [
        c
        for _, c in inspect.getmembers(estimator_module, inspect.isclass)
        if c.__module__ == estimator_module.__name__
    ]
    assert classes == [UnitEstimator]
