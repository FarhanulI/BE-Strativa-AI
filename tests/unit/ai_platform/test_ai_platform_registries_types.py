# ruff: noqa: E501  (SPEC_TABLE mirrors the spec table row by row)
from __future__ import annotations

import inspect
from typing import Any

import pytest
from pydantic import BaseModel, ConfigDict, TypeAdapter, ValidationError

import app.ai_platform as ai_platform
import app.ai_platform.config as config_module
import app.ai_platform.enums as enums_module
import app.ai_platform.requests as requests_module
import app.ai_platform.schemas as schemas_module
import app.ai_platform.tasks as tasks_module
from app.ai_platform import (
    AiCapability,
    AiContextBlock,
    AiModality,
    AiPart,
    AiPlatformConfig,
    AiTaskDefinition,
    AiTaskName,
    AiTaskNotReady,
    AiTaskRegistry,
    AiTaskRequest,
    AudioPart,
    CostClass,
    ImagePart,
    LatencyClass,
    MediaRef,
    OutputSchemaRegistry,
    QualityClass,
    TaskScope,
    TextPart,
    VideoPart,
)
from app.core import ConfigurationError

C, Q, L, K = AiCapability, QualityClass, LatencyClass, CostClass
_GROUNDED = {C.TEXT_GENERATION, C.RETRIEVAL_GROUNDING, C.STRUCTURED_OUTPUT}
_REASONING = _GROUNDED | {C.REASONING}
TEXT = {AiModality.TEXT}
WS = {TaskScope.WORKSPACE}

# (task, capabilities, schema, quality, latency, cost): the table of spec section 9.
SPEC_TABLE = {
    AiTaskName.ANALYZE_MARKET_TRENDS: (_REASONING, "MarketTrendAnalysis", Q.STANDARD, L.BATCH, K.MEDIUM),
    AiTaskName.GENERATE_CONTENT_BRIEF: (_REASONING, "ContentBriefDraft", Q.HIGH, L.STANDARD, K.HIGH),
    AiTaskName.GENERATE_CHANNEL_EXECUTION: (_GROUNDED, "ChannelExecutionDraft", Q.STANDARD, L.STANDARD, K.MEDIUM),
    AiTaskName.GENERATE_CONTENT_DRAFT: (_GROUNDED, "ContentDraftOutput", Q.HIGH, L.STANDARD, K.HIGH),
    AiTaskName.GENERATE_HOOK_VARIATIONS: ({C.TEXT_GENERATION, C.STRUCTURED_OUTPUT}, "HookVariationSet", Q.STANDARD, L.INTERACTIVE, K.LOW),
    AiTaskName.ANALYZE_PERFORMANCE: (_REASONING, "PerformanceAnalysis", Q.HIGH, L.BATCH, K.MEDIUM),
    AiTaskName.EXTRACT_AUDIENCE_SIGNALS: (_GROUNDED, "AudienceSignalExtraction", Q.STANDARD, L.BATCH, K.LOW),
    AiTaskName.SYNTHESIZE_SIGNALS: ({C.TEXT_GENERATION, C.REASONING, C.STRUCTURED_OUTPUT}, "SignalSynthesisResult", Q.STANDARD, L.BATCH, K.MEDIUM),
}  # fmt: skip


# --- AC-5: task registry ---


def test_registry_has_exactly_nine_entries() -> None:
    names = [d.name for d in AiTaskRegistry().list()]
    assert len(names) == 9
    assert set(names) == set(AiTaskName)


@pytest.mark.parametrize("task", list(SPEC_TABLE))
def test_entry_matches_spec_table(task: AiTaskName) -> None:
    capabilities, schema, quality, latency, cost = SPEC_TABLE[task]
    d = AiTaskRegistry().get(task)
    assert d.capabilities == frozenset(capabilities)
    assert d.output_schema_name == schema
    assert d.default_output_schema_version == 1
    assert (d.quality, d.latency, d.cost) == (quality, latency, cost)
    assert d.input_modalities == frozenset(TEXT)
    assert d.output_modalities == frozenset(TEXT)
    assert d.allowed_scopes == frozenset(WS)


def test_embed_text_entry() -> None:
    d = AiTaskRegistry().get(AiTaskName.EMBED_TEXT)
    assert d.capabilities == {C.EMBEDDING}
    assert d.output_schema_name is None
    assert (d.quality, d.latency, d.cost) == (Q.STANDARD, L.STANDARD, K.LOW)
    assert d.allowed_scopes == {TaskScope.WORKSPACE, TaskScope.SYSTEM}
    assert d.input_modalities == {AiModality.TEXT}
    assert d.output_modalities == frozenset()


def test_only_embed_text_lacks_a_schema_and_only_it_allows_system() -> None:
    for d in AiTaskRegistry().list():
        assert (d.output_schema_name is None) == (d.name is AiTaskName.EMBED_TEXT)
        assert (TaskScope.SYSTEM in d.allowed_scopes) == (d.name is AiTaskName.EMBED_TEXT)


def test_registry_is_read_only() -> None:
    registry = AiTaskRegistry()
    assert not hasattr(registry, "register")
    d = registry.get(AiTaskName.SYNTHESIZE_SIGNALS)
    with pytest.raises(ValidationError):
        d.cost = K.HIGH  # type: ignore[misc]
    registry.list().clear()
    assert len(registry.list()) == 9


def test_definition_forbids_extra_fields() -> None:
    d = AiTaskRegistry().get(AiTaskName.EMBED_TEXT)
    with pytest.raises(ValidationError):
        AiTaskDefinition(**d.model_dump(), model="x")


# --- classes and config ---


def test_quality_ordering() -> None:
    assert Q.BASIC < Q.STANDARD < Q.HIGH
    assert Q.HIGH > Q.STANDARD >= Q.STANDARD > Q.BASIC
    assert sorted([Q.HIGH, Q.BASIC, Q.STANDARD]) == [Q.BASIC, Q.STANDARD, Q.HIGH]
    assert max(Q.BASIC, Q.HIGH) is Q.HIGH
    assert Q.HIGH.value == "high"  # still a str enum


@pytest.fixture
def clean_env(monkeypatch: pytest.MonkeyPatch) -> None:
    import os

    for key in list(os.environ):
        if key.upper().startswith("AI_"):
            monkeypatch.delenv(key)


def test_cost_ceiling_defaults(clean_env: None) -> None:
    config = AiPlatformConfig(_env_file=None)
    assert config.cost_ceiling_micro_usd(K.LOW) == 20_000
    assert config.cost_ceiling_micro_usd(K.MEDIUM) == 100_000
    assert config.cost_ceiling_micro_usd(K.HIGH) == 500_000
    assert config.deadline_seconds(L.INTERACTIVE) == 20
    assert config.deadline_seconds(L.STANDARD) == 60
    assert config.deadline_seconds(L.BATCH) == 300


def test_cost_ceilings_configurable(clean_env: None) -> None:
    config = AiPlatformConfig(
        _env_file=None,
        cost_ceiling_low_micro_usd=1,
        cost_ceiling_medium_micro_usd=2,
        cost_ceiling_high_micro_usd=3,
    )
    assert [config.cost_ceiling_micro_usd(c) for c in K] == [1, 2, 3]


@pytest.mark.parametrize(
    "values",
    [
        {"cost_ceiling_low_micro_usd": 0},
        {"cost_ceiling_low_micro_usd": -5},
        {"cost_ceiling_high_micro_usd": 0},
        {"cost_ceiling_low_micro_usd": 100_000},  # equal to medium: not strictly ascending
        {"cost_ceiling_low_micro_usd": 200_000},  # above medium
        {"cost_ceiling_medium_micro_usd": 500_000},  # equal to high
        {"cost_ceiling_low_micro_usd": "abc"},
    ],
)
def test_cost_ceiling_violations_raise_configuration_error(
    clean_env: None, values: dict[str, Any]
) -> None:
    with pytest.raises(ConfigurationError) as raised:
        AiPlatformConfig(_env_file=None, **values)
    message = str(raised.value)
    assert "cost_ceiling" in message
    for value in values.values():
        assert str(value) not in message or str(value) in ("0",)  # values are not echoed


# --- output schema registry ---


class _Good(BaseModel):
    model_config = ConfigDict(extra="forbid")
    a: int


class _GoodV2(BaseModel):
    model_config = ConfigDict(extra="forbid")
    a: int
    b: int


class _Lax(BaseModel):
    a: int


class _Allows(BaseModel):
    model_config = ConfigDict(extra="allow")
    a: int


def test_register_and_get() -> None:
    registry = OutputSchemaRegistry()
    registry.register("Thing", 1, _Good)
    assert registry.get("Thing", 1) is _Good
    assert registry.get("Thing") is _Good


def test_get_without_version_is_highest_registered() -> None:
    registry = OutputSchemaRegistry()
    registry.register("Thing", 2, _GoodV2)
    registry.register("Thing", 1, _Good)
    assert registry.get("Thing") is _GoodV2
    assert registry.get("Thing", 1) is _Good


@pytest.mark.parametrize("bad", [_Lax, _Allows, int, dict, "nope", None, _Good(a=1)])
def test_register_rejects_bad_models(bad: Any) -> None:
    with pytest.raises((TypeError, ValueError)):
        OutputSchemaRegistry().register("Thing", 1, bad)


@pytest.mark.parametrize("version", [0, -1, True, 1.5, "1"])
def test_register_rejects_bad_versions(version: Any) -> None:
    with pytest.raises(ValueError):
        OutputSchemaRegistry().register("Thing", version, _Good)


def test_register_rejects_duplicates() -> None:
    registry = OutputSchemaRegistry()
    registry.register("Thing", 1, _Good)
    with pytest.raises(ValueError):
        registry.register("Thing", 1, _GoodV2)
    assert registry.get("Thing", 1) is _Good


def test_unknown_name_or_version_is_not_ready() -> None:
    registry = OutputSchemaRegistry()
    with pytest.raises(AiTaskNotReady):
        registry.get("Missing")
    registry.register("Thing", 1, _Good)
    with pytest.raises(AiTaskNotReady):
        registry.get("Thing", 2)
    with pytest.raises(AiTaskNotReady):
        registry.get("Missing", 1)


def test_registries_are_independent_instances() -> None:
    first, second = OutputSchemaRegistry(), OutputSchemaRegistry()
    first.register("Thing", 1, _Good)
    with pytest.raises(AiTaskNotReady):
        second.get("Thing")


# --- request and part types ---


def _request(**overrides: Any) -> dict[str, Any]:
    return {"task": AiTaskName.GENERATE_HOOK_VARIATIONS, "instructions": "do it", **overrides}


def test_minimal_request_defaults() -> None:
    request = AiTaskRequest(**_request())
    assert request.context == [] and request.parts == []
    assert request.output_schema_version is None
    assert request.max_output_units is None
    assert request.quality_floor is None
    assert request.persist_result is False


@pytest.mark.parametrize("field", ["model", "provider", "tools", "api_key", "anything"])
def test_request_rejects_unknown_fields(field: str) -> None:
    with pytest.raises(ValidationError):
        AiTaskRequest(**_request(**{field: "x"}))


def test_request_rejects_embed_text() -> None:
    with pytest.raises(ValidationError):
        AiTaskRequest(**_request(task=AiTaskName.EMBED_TEXT))
    with pytest.raises(ValidationError):
        AiTaskRequest.model_validate({"task": "EMBED_TEXT", "instructions": "x"})


@pytest.mark.parametrize("task", [t for t in AiTaskName if t is not AiTaskName.EMBED_TEXT])
def test_request_accepts_every_other_task(task: AiTaskName) -> None:
    assert AiTaskRequest(**_request(task=task)).task is task


@pytest.mark.parametrize("units", [0, -1])
def test_request_rejects_non_positive_max_output_units(units: int) -> None:
    with pytest.raises(ValidationError):
        AiTaskRequest(**_request(max_output_units=units))


def test_request_rejects_non_positive_schema_version() -> None:
    with pytest.raises(ValidationError):
        AiTaskRequest(**_request(output_schema_version=0))


def test_request_is_frozen() -> None:
    request = AiTaskRequest(**_request())
    with pytest.raises(ValidationError):
        request.instructions = "other"  # type: ignore[misc]


def test_request_round_trips() -> None:
    request = AiTaskRequest(
        **_request(
            context=[AiContextBlock(text="t", source_id="s")],
            parts=[
                TextPart(modality="text", text="hello"),
                ImagePart(
                    modality="image",
                    media=MediaRef(kind="https_url", value="https://x.example/a.png"),
                    mime_type="image/png",
                ),
            ],
            max_output_units=10,
            quality_floor=Q.HIGH,
            persist_result=True,
        )
    )
    assert AiTaskRequest.model_validate_json(request.model_dump_json()) == request
    assert AiTaskRequest.model_validate(request.model_dump(mode="json")) == request


_MEDIA = {"kind": "storage_key", "value": "k/1"}
_PARTS = TypeAdapter(AiPart)


@pytest.mark.parametrize(
    ("payload", "cls"),
    [
        ({"modality": "text", "text": "hi"}, TextPart),
        ({"modality": "image", "media": _MEDIA, "mime_type": "image/png"}, ImagePart),
        ({"modality": "video", "media": _MEDIA, "mime_type": "video/mp4"}, VideoPart),
        ({"modality": "audio", "media": _MEDIA, "mime_type": "audio/mpeg"}, AudioPart),
    ],
)
def test_discriminator_selects_class_and_round_trips(payload: dict[str, Any], cls: type) -> None:
    part = _PARTS.validate_python(payload)
    assert type(part) is cls
    assert _PARTS.validate_json(_PARTS.dump_json(part)) == part
    assert _PARTS.dump_python(part, mode="json") == payload


@pytest.mark.parametrize(
    "payload",
    [
        {"modality": "pdf", "text": "x"},
        {"text": "no modality"},
        {"modality": "image", "mime_type": "image/png"},  # missing media
        {"modality": "image", "media": _MEDIA},  # missing mime_type
        {"modality": "image", "media": _MEDIA, "mime_type": ""},
        {"modality": "image", "media": _MEDIA, "mime_type": "image/png", "extra": 1},
        {"modality": "text", "text": "x", "media": _MEDIA},
        {"modality": "text", "text": 5},
        {"modality": "audio", "media": {"kind": "storage_key", "value": ""}, "mime_type": "a/b"},
        {"modality": "audio", "media": {"kind": "storage_key", "value": "  "}, "mime_type": "a/b"},
        {"modality": "audio", "media": {"kind": "inline", "value": "x"}, "mime_type": "a/b"},
        {
            "modality": "video",
            "media": {"kind": "https_url", "value": "http://x.example/v.mp4"},
            "mime_type": "video/mp4",
        },
    ],
)
def test_bad_parts_are_rejected(payload: dict[str, Any]) -> None:
    with pytest.raises(ValidationError):
        _PARTS.validate_python(payload)


def test_media_ref_rules() -> None:
    assert MediaRef(kind="https_url", value="https://x.example/a").kind == "https_url"
    assert MediaRef(kind="storage_key", value="http-looking-key").value == "http-looking-key"
    for bad in ("http://x.example/a", "HTTPS://x.example/a", "ftp://x", "//x.example/a", ""):
        with pytest.raises(ValidationError):
            MediaRef(kind="https_url", value=bad)


# --- AC-3 reflection: no field names a provider or a model; no "token" anywhere ---

FORBIDDEN_FIELD_NAMES = {"model", "provider", "tools", "tool_choice", "functions", "api_key"}
FORBIDDEN_FRAGMENTS = ("gemini", "openai", "perplexity", "gpt", "claude", "anthropic", "litellm")
MODELS = [
    AiTaskRequest, AiTaskDefinition, AiContextBlock, MediaRef,
    TextPart, ImagePart, VideoPart, AudioPart,
]  # fmt: skip


@pytest.mark.parametrize("cls", MODELS, ids=lambda c: c.__name__)
def test_no_field_names_a_provider_or_model(cls: type[BaseModel]) -> None:
    for name, field in cls.model_fields.items():
        lowered = name.lower()
        assert lowered not in FORBIDDEN_FIELD_NAMES
        assert "provider" not in lowered and "model" not in lowered
        assert not any(fragment in lowered for fragment in FORBIDDEN_FRAGMENTS)
        for alias in (field.alias, field.validation_alias, field.serialization_alias):
            assert alias is None or not any(f in str(alias).lower() for f in FORBIDDEN_FRAGMENTS)


def test_registry_content_names_no_provider_or_model() -> None:
    for d in AiTaskRegistry().list():
        text = d.model_dump_json().lower()
        assert not any(fragment in text for fragment in FORBIDDEN_FRAGMENTS)


def _public_names(module: Any) -> set[str]:
    names = {name for name in vars(module) if not name.startswith("__")}
    for _, obj in inspect.getmembers(module, inspect.isclass):
        if obj.__module__ != module.__name__:
            continue
        names |= {name for name in vars(obj) if not name.startswith("__")}
        for field_name, field in getattr(obj, "model_fields", {}).items():
            names.add(field_name)
            for alias in (field.alias, field.validation_alias):
                if alias is not None:
                    names |= {str(c) for c in getattr(alias, "choices", [alias])}
    return names


@pytest.mark.parametrize(
    "module",
    [config_module, enums_module, tasks_module, schemas_module, requests_module, ai_platform],
)
def test_no_token_in_names(module: Any) -> None:
    assert [n for n in _public_names(module) if "token" in n.lower()] == []


def test_enum_values_contain_no_token() -> None:
    for enum in (AiModality, AiCapability, AiTaskName, QualityClass, LatencyClass, CostClass):
        assert [m for m in enum if "token" in m.value.lower() or "token" in m.name.lower()] == []
