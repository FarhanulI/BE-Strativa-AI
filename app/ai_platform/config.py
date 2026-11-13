"""AiPlatformConfig: pydantic-settings, env prefix ``AI_``, owned by ai_platform (spec 5.5).

Not part of core ``Settings``. Environment only (no dotenv files), so a developer's local files
never leak into tests. Invalid values raise ``ConfigurationError`` whose message names the
setting, never its value.
"""

from __future__ import annotations

import os
from decimal import Decimal, InvalidOperation, localcontext
from typing import Any, Literal

from pydantic import (
    AliasChoices,
    BaseModel,
    ConfigDict,
    Field,
    SecretStr,
    ValidationError,
    field_validator,
    model_validator,
)
from pydantic_settings import BaseSettings, SettingsConfigDict

from app.ai_platform.enums import CostClass, LatencyClass
from app.core import ConfigurationError, Settings, select_env_files

MICRO_USD_PER_USD = Decimal(1_000_000)
_MAX_MICRO_USD = 2**63 - 1  # the budget columns are bigint
_BUDGET_DECIMAL_PLACES = Decimal("0.000001")

GeminiBillingMode = Literal["free_tier", "paid"]

EMBEDDING_LIMITS_NOT_CONFIGURED = "AI embedding limits are not configured"


class EmbeddingLimits(BaseModel):
    """The three embedding input limits (spec 5.3, D-23), read by ``rag`` to size batches."""

    model_config = ConfigDict(frozen=True)

    max_text_units: int
    max_batch: int
    max_request_units: int


def _parse_positive_int(value: Any) -> int | None:
    """Parse an optional positive integer. ``None`` means unset. Never echoes the input."""
    if value is None:
        return None
    if isinstance(value, bool):
        raise ValueError("must be a positive integer")
    if isinstance(value, int):
        parsed = value
    elif isinstance(value, str):
        text = value.strip()
        if not (text.isascii() and text.isdigit()):
            raise ValueError("must be a positive integer")
        parsed = int(text)
    else:
        raise ValueError("must be a positive integer")
    if parsed <= 0:
        raise ValueError("must be a positive integer")
    return parsed


def _parse_budget_usd(value: Any) -> Decimal:
    """Parse a budget in USD as Decimal. Never accepts float; never echoes the input."""
    if isinstance(value, bool | float):
        raise ValueError("must be a decimal number given as text")
    try:
        parsed = value if isinstance(value, Decimal) else Decimal(str(value).strip())
    except (InvalidOperation, ValueError):
        raise ValueError("must be a decimal number") from None
    if not parsed.is_finite():
        raise ValueError("must be finite")
    if parsed < 0:
        raise ValueError("must not be negative")
    with localcontext() as context:
        context.prec = 60
        try:
            exact_to_six_places = parsed == parsed.quantize(_BUDGET_DECIMAL_PLACES)
        except InvalidOperation:
            raise ValueError("is out of range") from None
        if not exact_to_six_places:
            raise ValueError("must have at most 6 decimal places")
        if parsed * MICRO_USD_PER_USD > _MAX_MICRO_USD:
            raise ValueError("is out of range")
        return parsed + 0  # also normalizes a negative zero


class AiPlatformConfig(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="AI_",
        case_sensitive=False,
        env_file=None,
        env_ignore_empty=False,
        extra="ignore",
    )

    # Budgets (12.3). Decimal USD in, integer micro-USD out.
    workspace_monthly_budget_usd: Decimal = Decimal(25)
    system_monthly_budget_usd: Decimal = Decimal(100)

    # Content retention (8.3).
    async_content_retention_days: int = Field(default=30, ge=1)

    # Billing mode of the Gemini credential (10.1). The embedding credential is always paid and
    # is not configurable.
    gemini_billing_mode: GeminiBillingMode = "free_tier"

    # Provider credentials: exact names without the AI_ prefix (5.5, D-22). The adapter passes
    # them to LiteLLM explicitly; no other environment name is read.
    perplexity_api_key: SecretStr | None = Field(
        default=None,
        repr=False,
        validation_alias=AliasChoices("PERPLEXITY_API_KEY", "perplexity_api_key"),
    )
    gemini_api_key: SecretStr | None = Field(
        default=None,
        repr=False,
        validation_alias=AliasChoices("GEMINI_API_KEY", "gemini_api_key"),
    )

    # Embedding input limits (5.3, D-23). The spec gives no numbers: they are filled at
    # implementation from the official embeddings API reference (20.4). Unset (None) is valid
    # until an embedding call needs them (``embedding_limits``).
    embed_max_text_units: int | None = None
    embed_max_batch: int | None = None
    embed_max_request_units: int | None = None

    # Router and orchestrator (10.3, 10.4).
    max_provider_attempts: int = Field(default=3, gt=0)
    max_repair_attempts: int = Field(default=1, gt=0)
    context_safety_margin_percent: int = Field(default=10, gt=0, lt=100)
    breaker_failure_threshold: int = Field(default=5, gt=0)
    breaker_window_seconds: int = Field(default=60, gt=0)
    breaker_open_seconds: int = Field(default=30, gt=0)

    # Request deadlines by latency class (9).
    interactive_deadline_seconds: int = Field(default=20, gt=0)
    standard_deadline_seconds: int = Field(default=60, gt=0)
    batch_deadline_seconds: int = Field(default=300, gt=0)

    # Worst-case cost ceiling of one provider call, by cost class, in integer micro-USD (9).
    cost_ceiling_low_micro_usd: int = Field(default=20_000, gt=0)
    cost_ceiling_medium_micro_usd: int = Field(default=100_000, gt=0)
    cost_ceiling_high_micro_usd: int = Field(default=500_000, gt=0)

    # Jobs (8).
    lease_seconds: int = Field(default=180, gt=0)
    heartbeat_seconds: int = Field(default=60, gt=0)
    purge_batch_size: int = Field(default=500, gt=0)
    async_reserved_stale_seconds: int = Field(default=360, gt=0)
    queued_stale_seconds: int = Field(default=300, gt=0)
    sync_stale_after_seconds: int = Field(default=420, gt=0)

    def __init__(self, **values: Any) -> None:
        # Same env files as core Settings (shared selection logic); real process environment
        # variables take precedence over file values. Pass ``_env_file=None`` to read none.
        if "_env_file" not in values:
            values["_env_file"] = select_env_files(
                Settings.repository_root(),
                os.environ.get("APP_ENV"),
                os.environ.get("TEST_DB_MODE") or "neon",
            ).env_files
        try:
            super().__init__(**values)
        except ValidationError as error:
            # Names only: pydantic's own message would echo the offending input.
            names = sorted({".".join(str(part) for part in e["loc"]) for e in error.errors()})
            raise ConfigurationError(
                "Invalid AI platform configuration: " + ", ".join(names)
            ) from None

    @field_validator("workspace_monthly_budget_usd", "system_monthly_budget_usd", mode="before")
    @classmethod
    def _validate_budget(cls, value: Any) -> Decimal:
        return _parse_budget_usd(value)

    @field_validator(
        "embed_max_text_units", "embed_max_batch", "embed_max_request_units", mode="before"
    )
    @classmethod
    def _validate_embed_limit(cls, value: Any) -> int | None:
        return _parse_positive_int(value)

    @field_validator("perplexity_api_key", "gemini_api_key", mode="before")
    @classmethod
    def _blank_key_is_absent(cls, value: Any) -> Any:
        if isinstance(value, str) and not value.strip():
            return None
        return value

    @model_validator(mode="after")
    def _validate_cost_ceilings(self) -> AiPlatformConfig:
        if not (
            self.cost_ceiling_low_micro_usd
            < self.cost_ceiling_medium_micro_usd
            < self.cost_ceiling_high_micro_usd
        ):
            raise ConfigurationError(
                "cost_ceiling_low_micro_usd, cost_ceiling_medium_micro_usd and "
                "cost_ceiling_high_micro_usd must be strictly ascending"
            )
        return self

    @model_validator(mode="after")
    def _validate_timing(self) -> AiPlatformConfig:
        if self.heartbeat_seconds >= self.lease_seconds:
            raise ConfigurationError("heartbeat_seconds must be less than lease_seconds")
        if self.sync_stale_after_seconds <= self.longest_deadline_seconds:
            raise ConfigurationError(
                "sync_stale_after_seconds must be greater than the longest latency deadline"
            )
        return self

    @property
    def longest_deadline_seconds(self) -> int:
        return max(
            self.interactive_deadline_seconds,
            self.standard_deadline_seconds,
            self.batch_deadline_seconds,
        )

    def cost_ceiling_micro_usd(self, cost: CostClass) -> int:
        """The worst-case cost ceiling of a single provider call for a cost class."""
        return {
            CostClass.LOW: self.cost_ceiling_low_micro_usd,
            CostClass.MEDIUM: self.cost_ceiling_medium_micro_usd,
            CostClass.HIGH: self.cost_ceiling_high_micro_usd,
        }[cost]

    def deadline_seconds(self, latency: LatencyClass) -> int:
        """The total request deadline for a latency class."""
        return {
            LatencyClass.INTERACTIVE: self.interactive_deadline_seconds,
            LatencyClass.STANDARD: self.standard_deadline_seconds,
            LatencyClass.BATCH: self.batch_deadline_seconds,
        }[latency]

    @property
    def workspace_limit_micro_usd(self) -> int:
        return int(self.workspace_monthly_budget_usd * MICRO_USD_PER_USD)

    @property
    def system_limit_micro_usd(self) -> int:
        return int(self.system_monthly_budget_usd * MICRO_USD_PER_USD)

    def embedding_limits(self) -> EmbeddingLimits:
        """The embedding limits, or ``ConfigurationError`` if any of the three is unset."""
        if (
            self.embed_max_text_units is None
            or self.embed_max_batch is None
            or self.embed_max_request_units is None
        ):
            raise ConfigurationError(EMBEDDING_LIMITS_NOT_CONFIGURED)
        return EmbeddingLimits(
            max_text_units=self.embed_max_text_units,
            max_batch=self.embed_max_batch,
            max_request_units=self.embed_max_request_units,
        )
