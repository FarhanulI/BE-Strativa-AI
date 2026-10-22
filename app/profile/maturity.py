from __future__ import annotations

from dataclasses import dataclass

from app.profile.schemas import MaturityStage


@dataclass(frozen=True)
class MaturityThresholds:
    cold_start_threshold: int = 5
    mature_threshold: int = 30

    def __post_init__(self) -> None:
        if self.cold_start_threshold < 0:
            raise ValueError("cold_start_threshold must not be negative")
        if self.mature_threshold <= self.cold_start_threshold:
            raise ValueError("mature_threshold must be greater than cold_start_threshold")


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