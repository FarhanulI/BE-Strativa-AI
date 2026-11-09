# Importing the models registers the ai_* tables on the shared metadata (alembic, tenant-scope
# validation). The ORM classes are not exported: they are not part of the public surface (spec 5.6).
from app.ai_platform import models as _models  # noqa: F401
from app.ai_platform.config import AiPlatformConfig
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

__all__ = [
    "AiBudgetExceeded",
    "AiContentRefused",
    "AiErrorCode",
    "AiInputTooLarge",
    "AiModalityNotSupported",
    "AiNoRoute",
    "AiOutputInvalid",
    "AiPlatformConfig",
    "AiProviderNotConfigured",
    "AiProviderUnavailable",
    "AiTaskNotReady",
]
