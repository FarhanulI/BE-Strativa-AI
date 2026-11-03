from __future__ import annotations

import pytest

from app.profile.maturity import MaturityThresholds, compute_stage
from app.profile.schemas import MaturityStage


@pytest.mark.parametrize(
    ("count", "expected"),
    [
        (0, MaturityStage.COLD_START),
        (4, MaturityStage.COLD_START),
        (5, MaturityStage.EARLY_GROWTH),
        (29, MaturityStage.EARLY_GROWTH),
        (30, MaturityStage.MATURE),
        (300, MaturityStage.MATURE),
    ],
)
def test_default_maturity_threshold_boundaries(
    count: int, expected: MaturityStage
) -> None:
    assert compute_stage(count) == expected


def test_maturity_thresholds_are_configurable() -> None:
    thresholds = MaturityThresholds(cold_start_threshold=2, mature_threshold=10)

    assert compute_stage(1, thresholds) == MaturityStage.COLD_START
    assert compute_stage(2, thresholds) == MaturityStage.EARLY_GROWTH
    assert compute_stage(9, thresholds) == MaturityStage.EARLY_GROWTH
    assert compute_stage(10, thresholds) == MaturityStage.MATURE


def test_invalid_thresholds_and_negative_counts_are_rejected() -> None:
    with pytest.raises(ValueError):
        MaturityThresholds(cold_start_threshold=-1)
    with pytest.raises(ValueError):
        MaturityThresholds(cold_start_threshold=5, mature_threshold=5)
    with pytest.raises(ValueError):
        compute_stage(-1)

def test_thresholds_come_from_typed_settings() -> None:
    from app.core import Settings

    settings = Settings(
        _env_file=None, maturity_cold_start_threshold=2, maturity_mature_threshold=10
    )
    thresholds = MaturityThresholds.from_settings(settings)
    assert (thresholds.cold_start_threshold, thresholds.mature_threshold) == (2, 10)


def test_settings_reject_inverted_maturity_thresholds() -> None:
    from app.core import ConfigurationError, Settings

    with pytest.raises(ConfigurationError):
        Settings(_env_file=None, maturity_cold_start_threshold=10, maturity_mature_threshold=10)
