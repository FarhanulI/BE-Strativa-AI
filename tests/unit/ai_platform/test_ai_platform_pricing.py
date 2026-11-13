from __future__ import annotations

from decimal import ROUND_CEILING, Decimal

import pytest

from app.ai_platform.catalog import CatalogModel, ModelCatalog
from app.ai_platform.pricing import (
    cost_micro_usd,
    estimate_embedding_micro_usd,
    estimate_generation_micro_usd,
)
from tests.helpers.synthetic_catalog import catalog_dict, chat_entry, embed_entry


def _reference(units: int, price: int) -> int:
    value = Decimal(units) * Decimal(price) / Decimal(1_000_000)
    return int(value.to_integral_value(rounding=ROUND_CEILING))


UNITS = [0, 1, 2, 999, 1_000, 999_999, 1_000_000, 1_000_001, 2_000_000, 123_456_789, 10**15]
PRICES = [0, 1, 2, 999_999, 1_000_000, 1_000_001, 150_000, 600_000, 10**12, 10**18]


@pytest.mark.parametrize("units", UNITS)
@pytest.mark.parametrize("price", PRICES)
def test_cost_matches_decimal_reference(units: int, price: int) -> None:
    result = cost_micro_usd(units, price)
    assert isinstance(result, int)
    assert result == _reference(units, price)


@pytest.mark.parametrize(
    ("units", "price", "expected"),
    [
        (0, 5, 0),
        (1, 1, 1),
        (1_000_000, 7, 7),
        (1_000_000, 0, 0),
        (999_999, 1, 1),
        (1_000_001, 1, 2),
    ],
)
def test_cost_known_values(units: int, price: int, expected: int) -> None:
    assert cost_micro_usd(units, price) == expected


@pytest.mark.parametrize(
    ("units", "price"),
    [(-1, 1), (1, -1), (1.0, 1), (1, 1.0), ("1", 1), (1, "1"), (True, 1), (1, True), (None, 1)],
)
def test_cost_rejects_negative_and_non_int(units: object, price: object) -> None:
    with pytest.raises(ValueError):
        cost_micro_usd(units, price)  # type: ignore[arg-type]


def _models(in_price: int, out_price: int, embed_price: int) -> tuple[CatalogModel, CatalogModel]:
    catalog = ModelCatalog.from_dict(
        catalog_dict(
            chat_entry(
                input_micro_usd_per_million_units=in_price,
                output_micro_usd_per_million_units=out_price,
            ),
            embed_entry(input_micro_usd_per_million_units=embed_price),
        )
    )
    chat, embed = catalog.models()
    return chat, embed


def test_generation_estimate_rounds_each_part_up_separately() -> None:
    chat, _ = _models(1, 1, 1)
    # Each part is 0.5 micro-USD, rounded up to 1 each. Rounding the sum (1.0) would give 1.
    assert estimate_generation_micro_usd(500_000, 500_000, chat) == 2
    assert estimate_generation_micro_usd(0, 0, chat) == 0
    assert estimate_generation_micro_usd(1_000_000, 1, chat) == 2


@pytest.mark.parametrize("input_units", [0, 1, 333_333, 1_000_000, 7_654_321])
@pytest.mark.parametrize("output_units", [0, 1, 500_000, 1_000_000, 2_000_001])
def test_generation_estimate_matches_reference(input_units: int, output_units: int) -> None:
    chat, _ = _models(150_000, 600_000, 1)
    expected = _reference(input_units, 150_000) + _reference(output_units, 600_000)
    assert estimate_generation_micro_usd(input_units, output_units, chat) == expected


def test_embedding_estimate() -> None:
    _, embed = _models(1, 1, 3)
    assert estimate_embedding_micro_usd(1, embed) == 1
    assert estimate_embedding_micro_usd(333_334, embed) == 2
    assert estimate_embedding_micro_usd(0, embed) == 0


def test_estimates_reject_bad_input() -> None:
    chat, embed = _models(1, 1, 1)
    with pytest.raises(ValueError):
        estimate_generation_micro_usd(-1, 1, chat)
    with pytest.raises(ValueError):
        estimate_generation_micro_usd(1, 1.5, chat)  # type: ignore[arg-type]
    with pytest.raises(ValueError):
        estimate_embedding_micro_usd(-1, embed)
