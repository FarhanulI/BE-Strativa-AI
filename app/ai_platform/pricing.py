"""Integer cost helpers (spec 12.2). Pure functions, no floats, no I/O.

``cost = ceil(units * price_per_million / 1_000_000)``, rounded up so the ledger never
undercounts.
"""

from __future__ import annotations

from app.ai_platform.catalog import CatalogModel

_MILLION = 1_000_000


def _require_non_negative_int(value: object) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError("expected a non-negative integer")
    return value


def cost_micro_usd(units: int, price_per_million: int) -> int:
    units = _require_non_negative_int(units)
    price = _require_non_negative_int(price_per_million)
    return -(-(units * price) // _MILLION)


def estimate_generation_micro_usd(
    estimated_input_units: int, max_output_units: int, model: CatalogModel
) -> int:
    """Reservation estimate: input and output parts are each rounded up separately."""
    return cost_micro_usd(
        estimated_input_units, model.input_micro_usd_per_million_units
    ) + cost_micro_usd(max_output_units, model.output_micro_usd_per_million_units)


def estimate_embedding_micro_usd(estimated_input_units: int, model: CatalogModel) -> int:
    return cost_micro_usd(estimated_input_units, model.input_micro_usd_per_million_units)
