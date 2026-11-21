"""Errors raised by ai_platform (spec 5.4).

Every detail string is fixed text. The constructors take no arguments, so callers cannot put
provider or model names, user text, prompts, URLs or keys into a detail (INV-2). The core
``DomainError`` accepts free text; these classes deliberately narrow that.
"""

from __future__ import annotations

from enum import StrEnum
from typing import ClassVar

from app.core import (
    ConfigurationError,
    DomainError,
    ExternalServiceError,
    RateLimited,
    ValidationFailed,
)


class _FixedDetail:
    """Mixin: the detail comes from the class and cannot be passed in."""

    fixed_detail: ClassVar[str]

    def __init__(self) -> None:
        # The mixin's static base is object, whose __init__ takes no arguments; at runtime the
        # MRO continues into the concrete DomainError, which takes the detail.
        super().__init__(self.fixed_detail)  # type: ignore[call-arg]


class AiBudgetExceeded(_FixedDetail, RateLimited):
    code = "ai_budget_exceeded"
    title = "AI Budget Exceeded"
    fixed_detail = "The AI usage budget for this period has been reached"


class AiNoRoute(_FixedDetail, ExternalServiceError):
    code = "ai_no_route"
    title = "No AI Route Available"
    fixed_detail = "No AI capability is available for this request"


class AiProviderUnavailable(_FixedDetail, ExternalServiceError):
    code = "ai_provider_unavailable"
    title = "AI Service Unavailable"
    fixed_detail = "The AI service is temporarily unavailable"


class AiOutputInvalid(_FixedDetail, ExternalServiceError):
    code = "ai_output_invalid"
    title = "AI Output Invalid"
    fixed_detail = "The AI service returned an invalid result"


class AiContentRefused(_FixedDetail, ExternalServiceError):
    code = "ai_content_refused"
    title = "AI Content Refused"
    fixed_detail = "The AI service declined to process this request"


class AiInputTooLarge(_FixedDetail, ValidationFailed):
    code = "ai_input_too_large"
    title = "AI Input Too Large"
    fixed_detail = "The input is too large to process"


class AiModalityNotSupported(_FixedDetail, ValidationFailed):
    code = "ai_modality_not_supported"
    title = "AI Modality Not Supported"
    fixed_detail = "This type of input is not supported for this AI task"


class AiTaskNotReady(_FixedDetail, DomainError):
    status_code = 503
    code = "ai_task_not_ready"
    title = "AI Task Not Ready"
    fixed_detail = "This AI task is not available yet"


class AiProviderNotConfigured(ConfigurationError):
    """Maps to 503 ``service_unavailable`` through the core ConfigurationError handler.

    Not a ``DomainError``. The message is fixed and never names a provider or a key.
    """

    fixed_detail: ClassVar[str] = "An AI provider is not configured"

    def __init__(self) -> None:
        super().__init__(self.fixed_detail)


class AiErrorCode(StrEnum):
    """Values persisted in ``error_code`` on ai_requests and ai_usage_records (spec 5.4).

    No database constraint enforces this list.
    """

    PROVIDER_TIMEOUT = "provider_timeout"
    PROVIDER_RATE_LIMITED = "provider_rate_limited"
    PROVIDER_UNAVAILABLE = "provider_unavailable"
    PROVIDER_AUTH_FAILED = "provider_auth_failed"
    PROVIDER_NOT_CONFIGURED = "provider_not_configured"
    PROVIDER_BAD_REQUEST = "provider_bad_request"
    CONTENT_REFUSED = "content_refused"
    OUTPUT_TRUNCATED = "output_truncated"
    OUTPUT_INVALID = "output_invalid"
    BUDGET_EXCEEDED = "budget_exceeded"
    NO_ROUTE = "no_route"
    INPUT_TOO_LARGE = "input_too_large"
    LEASE_LOST = "lease_lost"
    EXECUTION_ABANDONED = "execution_abandoned"
