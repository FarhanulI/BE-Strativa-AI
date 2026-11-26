"""Strict output validation (spec 11, INV-8; request-side mode choice D-25).

INTERNAL module, pure: no I/O, no clock, no environment. Validation is the only gate for model
output. An outcome carries error locations and error type names only, never input values,
messages, context or URLs from the validation library, so nothing in it can leak model output
(INV-18, INV-24).
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Literal

from pydantic import BaseModel, ValidationError

JSON_INVALID = "json_invalid"
# A path segment is kept only when it looks like a field name or a list index. Anything else
# (for example a key that came from the model output) is replaced, so output text cannot reach
# an outcome through a location.
_SAFE_SEGMENT = re.compile(r"^[A-Za-z0-9_\-]{1,64}$")
_REDACTED_SEGMENT = "?"
_EXTRA_FORBIDDEN = "extra_forbidden"


@dataclass(frozen=True, slots=True)
class ValidationIssue:
    path: str  # dotted location such as "items.2.title"; "" for the document root
    error_type: str  # the library's error type name such as "missing"


@dataclass(frozen=True, slots=True)
class ValidationOutcome:
    ok: bool
    # Repr is hidden so printing an outcome never prints model output.
    instance: BaseModel | None = field(default=None, repr=False)
    issues: tuple[ValidationIssue, ...] = ()
    error_count: int = 0
    error_types: tuple[str, ...] = ()


def _failed(issues: tuple[ValidationIssue, ...]) -> ValidationOutcome:
    return ValidationOutcome(
        ok=False,
        instance=None,
        issues=issues,
        error_count=len(issues),
        error_types=tuple(sorted({issue.error_type for issue in issues})),
    )


def _path(location: tuple[int | str, ...], error_type: str) -> str:
    segments = [str(part) for part in location]
    if error_type == _EXTRA_FORBIDDEN and segments:
        segments[-1] = _REDACTED_SEGMENT  # the last segment is an unexpected key from the output
    return ".".join(
        segment if _SAFE_SEGMENT.fullmatch(segment) else _REDACTED_SEGMENT for segment in segments
    )


def validate_output(raw_text: str, schema: type[BaseModel]) -> ValidationOutcome:
    """Parses and validates ``raw_text`` strictly: no coercion, no extra keys, no partial result."""
    if schema.model_config.get("extra") != "forbid":
        raise ValueError("output schema must forbid extra fields")
    if not raw_text.strip():
        return _failed((ValidationIssue(path="", error_type=JSON_INVALID),))
    try:
        instance = schema.model_validate_json(raw_text, strict=True)
    except ValidationError as error:
        issues = tuple(
            ValidationIssue(path=_path(item["loc"], item["type"]), error_type=item["type"])
            for item in error.errors(include_url=False, include_context=False, include_input=False)
        )
        return _failed(issues)
    return ValidationOutcome(ok=True, instance=instance)


def response_mode_for(model_supports_json_schema: bool) -> Literal["json_schema", "json_mode"]:
    """The request-side choice (D-25): a schema when the model supports it, JSON mode otherwise."""
    return "json_schema" if model_supports_json_schema else "json_mode"


def response_schema_for(schema: type[BaseModel]) -> dict[str, object]:
    return dict(schema.model_json_schema())
