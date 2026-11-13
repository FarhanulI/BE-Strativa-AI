# Importing the models registers the ai_* tables on the shared metadata (alembic, tenant-scope
# validation). The ORM classes are not exported: they are not part of the public surface (spec 5.6).
from app.ai_platform import models as _models  # noqa: F401
from app.ai_platform.config import AiPlatformConfig, EmbeddingLimits
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

__all__ = [
    "AiBudgetExceeded",
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
    "AudioPart",
    "CostClass",
    "EmbeddingLimits",
    "ImagePart",
    "LatencyClass",
    "MediaRef",
    "OutputSchemaRegistry",
    "QualityClass",
    "TaskScope",
    "TextPart",
    "VideoPart",
]
