from __future__ import annotations

from dataclasses import dataclass

from app.core import (
    DEFAULT_MATURITY_COLD_START_THRESHOLD,
    DEFAULT_MATURITY_MATURE_THRESHOLD,
    Settings,
)
from app.profile.schemas import MaturityStage


@dataclass(frozen=True)
class MaturityThresholds:
    cold_start_threshold: int = DEFAULT_MATURITY_COLD_START_THRESHOLD
    mature_threshold: int = DEFAULT_MATURITY_MATURE_THRESHOLD

    def __post_init__(self) -> None:
        if self.cold_start_threshold < 0:
            raise ValueError("cold_start_threshold must not be negative")
        if self.mature_threshold <= self.cold_start_threshold:
            raise ValueError("mature_threshold must be greater than cold_start_threshold")


    @classmethod
    def from_settings(cls, settings: Settings) -> MaturityThresholds:
        return cls(
            cold_start_threshold=settings.maturity_cold_start_threshold,
            mature_threshold=settings.maturity_mature_threshold,
        )


DEFAULT_THRESHOLDS = MaturityThresholds()


def compute_stage(
    verified_performance_count: int,
    thresholds: MaturityThresholds = DEFAULT_THRESHOLDS,
) -> MaturityStage:
    if verified_performance_count < 0:
        raise ValueError("verified_performance_count must not be negative")
    if verified_performance_count < thresholds.cold_start_threshold:
        return MaturityStage.COLD_START
    if verified_performance_count < thresholds.mature_threshold:
        return MaturityStage.EARLY_GROWTH
    return MaturityStage.MATURE