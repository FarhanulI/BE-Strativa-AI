"""The task registry (spec 9): static, in code, read-only.

A definition says what a task needs, never which provider or model serves it. Class values are
turned into numbers by ``AiPlatformConfig``, not here.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict

from app.ai_platform.enums import (
    AiCapability,
    AiModality,
    AiTaskName,
    CostClass,
    LatencyClass,
    QualityClass,
    TaskScope,
)


class AiTaskDefinition(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    name: AiTaskName
    capabilities: frozenset[AiCapability]
    output_schema_name: str | None  # None only for EMBED_TEXT
    default_output_schema_version: int = 1
    quality: QualityClass
    latency: LatencyClass
    cost: CostClass
    input_modalities: frozenset[AiModality]
    output_modalities: frozenset[AiModality]
    allowed_scopes: frozenset[TaskScope]


_C = AiCapability
_Q, _L, _K = QualityClass, LatencyClass, CostClass
_TEXT = frozenset({AiModality.TEXT})
_WORKSPACE = frozenset({TaskScope.WORKSPACE})
_GROUNDED = {_C.TEXT_GENERATION, _C.RETRIEVAL_GROUNDING, _C.STRUCTURED_OUTPUT}
_GROUNDED_REASONING = _GROUNDED | {_C.REASONING}


def _text_task(
    name: AiTaskName,
    capabilities: set[AiCapability],
    schema: str,
    quality: QualityClass,
    latency: LatencyClass,
    cost: CostClass,
) -> AiTaskDefinition:
    return AiTaskDefinition(
        name=name,
        capabilities=frozenset(capabilities),
        output_schema_name=schema,
        quality=quality,
        latency=latency,
        cost=cost,
        input_modalities=_TEXT,
        output_modalities=_TEXT,
        allowed_scopes=_WORKSPACE,
    )


_DEFINITIONS: tuple[AiTaskDefinition, ...] = (
    _text_task(
        AiTaskName.ANALYZE_MARKET_TRENDS,
        _GROUNDED_REASONING,
        "MarketTrendAnalysis",
        _Q.STANDARD,
        _L.BATCH,
        _K.MEDIUM,
    ),
    _text_task(
        AiTaskName.GENERATE_CONTENT_BRIEF,
        _GROUNDED_REASONING,
        "ContentBriefDraft",
        _Q.HIGH,
        _L.STANDARD,
        _K.HIGH,
    ),
    _text_task(
        AiTaskName.GENERATE_CHANNEL_EXECUTION,
        _GROUNDED,
        "ChannelExecutionDraft",
        _Q.STANDARD,
        _L.STANDARD,
        _K.MEDIUM,
    ),
    _text_task(
        AiTaskName.GENERATE_CONTENT_DRAFT,
        _GROUNDED,
        "ContentDraftOutput",
        _Q.HIGH,
        _L.STANDARD,
        _K.HIGH,
    ),
    _text_task(
        AiTaskName.GENERATE_HOOK_VARIATIONS,
        {_C.TEXT_GENERATION, _C.STRUCTURED_OUTPUT},
        "HookVariationSet",
        _Q.STANDARD,
        _L.INTERACTIVE,
        _K.LOW,
    ),
    _text_task(
        AiTaskName.ANALYZE_PERFORMANCE,
        _GROUNDED_REASONING,
        "PerformanceAnalysis",
        _Q.HIGH,
        _L.BATCH,
        _K.MEDIUM,
    ),
    _text_task(
        AiTaskName.EXTRACT_AUDIENCE_SIGNALS,
        _GROUNDED,
        "AudienceSignalExtraction",
        _Q.STANDARD,
        _L.BATCH,
        _K.LOW,
    ),
    _text_task(
        AiTaskName.SYNTHESIZE_SIGNALS,
        {_C.TEXT_GENERATION, _C.REASONING, _C.STRUCTURED_OUTPUT},
        "SignalSynthesisResult",
        _Q.STANDARD,
        _L.BATCH,
        _K.MEDIUM,
    ),
    AiTaskDefinition(
        name=AiTaskName.EMBED_TEXT,
        capabilities=frozenset({_C.EMBEDDING}),
        output_schema_name=None,
        quality=_Q.STANDARD,
        latency=_L.STANDARD,
        cost=_K.LOW,
        input_modalities=_TEXT,
        # Judgment call: embeddings are not a generated modality, so the output set is empty.
        output_modalities=frozenset(),
        allowed_scopes=frozenset({TaskScope.WORKSPACE, TaskScope.SYSTEM}),
    ),
)


class AiTaskRegistry:
    """Read-only view of the built-in tasks. There is no runtime registration (spec 9)."""

    def __init__(self) -> None:
        self._by_name = {definition.name: definition for definition in _DEFINITIONS}

    def get(self, task: AiTaskName) -> AiTaskDefinition:
        return self._by_name[task]

    def list(self) -> list[AiTaskDefinition]:
        return list(self._by_name.values())
