"""Strict output validator (spec 11; AC-22 to AC-25 validator part, INV-8). Pure."""

from __future__ import annotations

import json

import pytest
from pydantic import BaseModel, ConfigDict

from app.ai_platform.validation import (
    ValidationIssue,
    ValidationOutcome,
    response_mode_for,
    response_schema_for,
    validate_output,
)

SENTINEL = "LEAK-SENTINEL-9f3"


class Item(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str
    count: int


class Doc(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str
    items: list[Item] = []
    scores: dict[str, int] = {}


def _types(raw: str) -> tuple[tuple[str, str], ...]:
    outcome = validate_output(raw, Doc)
    assert not outcome.ok and outcome.instance is None
    return tuple((i.path, i.error_type) for i in outcome.issues)


def test_valid_json_gives_an_instance() -> None:
    outcome = validate_output('{"name": "n", "items": [{"title": "t", "count": 2}]}', Doc)
    assert outcome.ok and isinstance(outcome.instance, Doc)
    assert outcome.instance.items[0].count == 2
    assert (outcome.issues, outcome.error_count, outcome.error_types) == ((), 0, ())


def test_missing_field() -> None:
    assert _types("{}") == (("name", "missing"),)


def test_wrong_type() -> None:
    assert _types('{"name": 5}') == (("name", "string_type"),)


def test_extra_key_is_rejected_and_its_name_is_not_reported() -> None:
    assert _types(f'{{"name": "n", "{SENTINEL}": 1}}') == (("?", "extra_forbidden"),)


def test_string_for_int_is_not_coerced() -> None:
    assert _types('{"name": "n", "items": [{"title": "t", "count": "2"}]}') == (
        ("items.0.count", "int_type"),
    )
    assert _types('{"name": "n", "items": [{"title": "t", "count": 2.0}]}') == (
        ("items.0.count", "int_type"),
    )
    assert _types('{"name": 1.5}') == (("name", "string_type"),)


@pytest.mark.parametrize("raw", ["", "   ", "\n\t "])
def test_empty_or_blank_text_is_json_invalid(raw: str) -> None:
    assert _types(raw) == (("", "json_invalid"),)


@pytest.mark.parametrize(
    "raw", ["not json", '{"name": "n"', '{"name": "n", "items": [', "{'a': 1}"]
)
def test_invalid_and_truncated_json_is_json_invalid(raw: str) -> None:
    assert _types(raw) == (("", "json_invalid"),)


def test_nested_paths_are_dotted_with_list_indices() -> None:
    raw = '{"name": "n", "items": [{"title": "t", "count": 1}, {"title": "u"}, {"count": 3}]}'
    assert _types(raw) == (("items.1.count", "missing"), ("items.2.title", "missing"))


def test_dict_keys_from_the_output_are_not_reported() -> None:
    assert _types(f'{{"name": "n", "scores": {{"{SENTINEL} x": "bad"}}}}') == (
        ("scores.?", "int_type"),
    )


def test_error_types_are_distinct_and_sorted_and_counts_match() -> None:
    raw = '{"items": [{"title": 1}, {"title": 2}], "zzz": 1}'
    outcome = validate_output(raw, Doc)
    assert outcome.error_types == ("extra_forbidden", "missing", "string_type")
    assert outcome.error_count == len(outcome.issues) == 6


def test_no_input_value_message_or_url_ever_appears_in_the_outcome() -> None:
    raw = json.dumps(
        {"name": 1, "items": [{"title": SENTINEL, "count": SENTINEL, "x": SENTINEL}], SENTINEL: 1}
    )
    outcome = validate_output(raw, Doc)
    assert not outcome.ok
    blob = " ".join(
        [repr(outcome), str(outcome), *(repr(i) for i in outcome.issues)]
        + [i.path + i.error_type for i in outcome.issues]
        + list(outcome.error_types)
    )
    assert SENTINEL not in blob
    assert "http" not in blob and "pydantic.dev" not in blob
    assert all(i.error_type.replace("_", "").isalnum() for i in outcome.issues)


def test_a_valid_outcome_does_not_print_the_instance() -> None:
    outcome = validate_output(f'{{"name": "{SENTINEL}"}}', Doc)
    assert outcome.ok and SENTINEL not in repr(outcome)


def test_schema_without_extra_forbid_is_a_programming_error() -> None:
    class Loose(BaseModel):
        name: str

    class Ignoring(BaseModel):
        model_config = ConfigDict(extra="ignore")
        name: str

    for schema in (Loose, Ignoring):
        with pytest.raises(ValueError):
            validate_output('{"name": "n"}', schema)


def test_outcome_and_issue_are_frozen() -> None:
    outcome = validate_output("{}", Doc)
    with pytest.raises(AttributeError):
        outcome.ok = True  # type: ignore[misc]  # frozen dataclass: assignment must fail
    with pytest.raises(AttributeError):
        outcome.issues[0].path = "x"  # type: ignore[misc]  # frozen dataclass
    assert isinstance(outcome, ValidationOutcome) and isinstance(outcome.issues[0], ValidationIssue)


def test_response_mode_for_both_values() -> None:
    assert response_mode_for(True) == "json_schema"
    assert response_mode_for(False) == "json_mode"


def test_response_schema_for_is_a_json_serialisable_dict() -> None:
    schema = response_schema_for(Doc)
    assert isinstance(schema, dict) and schema.get("additionalProperties") is False
    assert json.loads(json.dumps(schema)) == schema
