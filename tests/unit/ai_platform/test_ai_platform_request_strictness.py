from __future__ import annotations

from typing import Any

import pytest
from pydantic import ValidationError

from app.ai_platform import AiTaskName, AiTaskRequest, QualityClass


def _data(**overrides: Any) -> dict[str, Any]:
    data: dict[str, Any] = {"task": "GENERATE_CONTENT_DRAFT", "instructions": "x"}
    data.update(overrides)
    return data


@pytest.mark.parametrize("value", ["5", 5.0, 5.5, True, False])
def test_max_output_units_rejects_non_int(value: object) -> None:
    with pytest.raises(ValidationError):
        AiTaskRequest.model_validate(_data(max_output_units=value))


def test_max_output_units_default_and_explicit_none_are_allowed() -> None:
    assert AiTaskRequest.model_validate(_data()).max_output_units is None
    assert AiTaskRequest.model_validate(_data(max_output_units=None)).max_output_units is None


@pytest.mark.parametrize("value", ["true", "false", 1, 0, "yes", None])
def test_persist_result_rejects_non_bool(value: object) -> None:
    with pytest.raises(ValidationError):
        AiTaskRequest.model_validate(_data(persist_result=value))


def test_valid_scalars_and_enum_strings_still_accepted() -> None:
    request = AiTaskRequest.model_validate(
        _data(max_output_units=7, persist_result=True, quality_floor="high")
    )
    assert request.max_output_units == 7
    assert request.persist_result is True
    assert request.quality_floor is QualityClass.HIGH
    assert request.task is AiTaskName.GENERATE_CONTENT_DRAFT
