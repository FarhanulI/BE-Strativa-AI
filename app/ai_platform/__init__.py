# Importing the models registers the ai_* tables on the shared metadata (alembic, tenant-scope
# validation). The ORM classes are not exported: they are not part of the public surface (spec 5.6).
# Importing the events registers the ai.* event models in DEFAULT_EVENT_REGISTRY (spec 7), the same
# import-time registration as app.profile.events. The event classes stay importable from
# app.ai_platform.events only.
from app.ai_platform import events as _events  # noqa: F401
from app.ai_platform import models as _models  # noqa: F401
from app.ai_platform.budget_service import AiBudgetService
from app.ai_platform.config import AiPlatformConfig, EmbeddingLimits
from app.ai_platform.context import AiCallContext
from app.ai_platform.enums import (
    AiCapability,
    AiModality,
    AiTaskName,
    CostClass,
    LatencyClass,
    QualityClass,
    TaskScope,
)
from app.ai_platform.errors import (
    AiBudgetExceeded,
    AiContentRefused,
    AiErrorCode,
    AiInputTooLarge,
    AiModalityNotSupported,
    AiNoRoute,
    AiOutputInvalid,
    AiProviderNotConfigured,
    AiProviderUnavailable,
    AiTaskNotReady,
)
from app.ai_platform.fake_provider import FakeAiProvider, ScriptedResponse
from app.ai_platform.requests import (
    AiContextBlock,
    AiPart,
    AiTaskRequest,
    AudioPart,
    ImagePart,
    MediaRef,
    TextPart,
    VideoPart,
)
from app.ai_platform.schemas import OutputSchemaRegistry
from app.ai_platform.tasks import AiTaskDefinition, AiTaskRegistry
from app.ai_platform.usage_service import AiUsageService
from app.ai_platform.usage_types import AiBudgetStatus, AiUsageReport, AiUsageSummary

__all__ = [
    "AiBudgetExceeded",
    "AiBudgetService",
    "AiBudgetStatus",
    "AiCallContext",
    "AiCapability",
    "AiContentRefused",
    "AiContextBlock",
    "AiErrorCode",
    "AiInputTooLarge",
    "AiModality",
    "AiModalityNotSupported",
    "AiNoRoute",
    "AiOutputInvalid",
    "AiPart",
    "AiPlatformConfig",
    "AiProviderNotConfigured",
    "AiProviderUnavailable",
    "AiTaskDefinition",
    "AiTaskName",
    "AiTaskNotReady",
    "AiTaskRegistry",
    "AiTaskRequest",
    "AiUsageReport",
    "AiUsageService",
    "AiUsageSummary",
    "AudioPart",
    "CostClass",
    "EmbeddingLimits",
    "FakeAiProvider",
    "ImagePart",
    "LatencyClass",
    "MediaRef",
    "OutputSchemaRegistry",
    "QualityClass",
    "ScriptedResponse",
    "TaskScope",
    "TextPart",
    "VideoPart",
]
