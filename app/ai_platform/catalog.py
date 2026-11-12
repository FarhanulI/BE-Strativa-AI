"""The model catalog: structure, validation and loader (spec 10.1).

Internal to ai_platform (spec 5.6): not exported from the package root. This module holds no
data and no provider or model identifiers. It never reads the clock (INV-22).

Every failure raises ``ConfigurationError`` with a fixed message that names field paths only,
never values: the catalog file is configuration, but its values must not leak into logs.
"""

from __future__ import annotations

import json
from datetime import date, datetime
from pathlib import Path
from typing import Any

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    ValidationError,
    field_validator,
    model_validator,
)

from app.ai_platform.enums import AiCapability, AiModality, QualityClass
from app.core import ConfigurationError

_PROVIDER_PATTERN = r"^[a-z][a-z0-9_-]*$"

_INVALID_MESSAGE = "Invalid AI model catalog; offending fields: "
_UNREADABLE_MESSAGE = "The AI model catalog file could not be read"
_NOT_JSON_MESSAGE = "The AI model catalog file is not valid JSON"

_RULE_PREFIX = "Value error, "


class CatalogModel(BaseModel):
    """One model entry. There is deliberately no billing-mode field (D-19)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    provider: str = Field(pattern=_PROVIDER_PATTERN)
    model: str = Field(min_length=1)
    enabled: bool = Field(strict=True)
    capabilities: frozenset[AiCapability]
    input_modalities: frozenset[AiModality]
    output_modalities: frozenset[AiModality]
    quality_tier: QualityClass
    context_window_units: int = Field(gt=0, strict=True)
    max_output_units: int | None = Field(default=None, gt=0, strict=True)
    supports_json_schema: bool = Field(strict=True)
    latency_p50_ms: int = Field(gt=0, strict=True)
    input_micro_usd_per_million_units: int = Field(ge=0, strict=True)
    output_micro_usd_per_million_units: int = Field(ge=0, strict=True)
    price_source_url: str
    price_checked_on: date

    @field_validator("model")
    @classmethod
    def _model_not_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("")
        return value

    @field_validator("price_source_url")
    @classmethod
    def _https_only(cls, value: str) -> str:
        if not value.startswith("https://"):
            raise ValueError("")
        return value

    @field_validator("price_checked_on", mode="before")
    @classmethod
    def _date_not_timestamp(cls, value: Any) -> Any:
        # A date or an ISO string only: lax date parsing would also accept numbers and datetimes.
        if isinstance(value, datetime) or not isinstance(value, date | str):
            raise ValueError("")
        return value

    @model_validator(mode="after")
    def _check_rules(self) -> CatalogModel:
        capabilities = self.capabilities
        is_embedding = AiCapability.EMBEDDING in capabilities
        if is_embedding and AiCapability.TEXT_GENERATION in capabilities:
            raise ValueError("capabilities")
        if (
            AiCapability.STRUCTURED_OUTPUT in capabilities
            and AiCapability.TEXT_GENERATION not in capabilities
        ):
            raise ValueError("capabilities")
        if self.enabled and not capabilities:
            raise ValueError("capabilities")
        # A generation model is any model that is not embedding-only; embeddings have no output cap.
        if self.enabled and capabilities and not is_embedding and self.max_output_units is None:
            raise ValueError("max_output_units")
        return self


class ModelCatalog(BaseModel):
    """The versioned list of models. Immutable once built."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    catalog_version: str = Field(min_length=1)
    price_version: str = Field(min_length=1)
    entries: tuple[CatalogModel, ...] = Field(validation_alias="models")

    @field_validator("catalog_version", "price_version")
    @classmethod
    def _version_not_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("")
        return value

    @model_validator(mode="after")
    def _unique_models(self) -> ModelCatalog:
        seen: set[tuple[str, str]] = set()
        for index, entry in enumerate(self.entries):
            key = (entry.provider, entry.model)
            if key in seen:
                raise ValueError(f"models.{index}")
            seen.add(key)
        return self

    @classmethod
    def from_dict(cls, data: Any) -> ModelCatalog:
        try:
            return cls.model_validate(data)
        except ValidationError as error:
            raise ConfigurationError(_INVALID_MESSAGE + _field_paths(error)) from None

    def models(self) -> tuple[CatalogModel, ...]:
        return self.entries

    def get(self, provider: str, model: str) -> CatalogModel | None:
        for entry in self.entries:
            if entry.provider == provider and entry.model == model:
                return entry
        return None

    def models_for_provider(self, provider: str) -> tuple[CatalogModel, ...]:
        return tuple(entry for entry in self.entries if entry.provider == provider)

    def enabled_models(self) -> tuple[CatalogModel, ...]:
        return tuple(entry for entry in self.entries if entry.enabled)


def load_catalog(path: Path) -> ModelCatalog:
    """Read and validate a catalog JSON file (standard-library ``json``, no new dependency)."""
    try:
        text = Path(path).read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        raise ConfigurationError(_UNREADABLE_MESSAGE) from None
    try:
        data = json.loads(text)
    except ValueError:
        raise ConfigurationError(_NOT_JSON_MESSAGE) from None
    return ModelCatalog.from_dict(data)


def _field_paths(error: ValidationError) -> str:
    paths: set[str] = set()
    for item in error.errors(include_url=False, include_context=False, include_input=False):
        parts = [str(part) for part in item["loc"]]
        kind = item["type"]
        if kind == "extra_forbidden" and parts:
            parts[-1] = "<unexpected field>"  # the key name is file content, not a field path
        elif kind == "value_error":
            message = item["msg"]
            rule = message[len(_RULE_PREFIX) :] if message.startswith(_RULE_PREFIX) else ""
            if rule:  # field validators leave it empty: their loc already names the field
                parts.append(rule)
        paths.add(".".join(parts) or "<root>")
    return ", ".join(sorted(paths))
