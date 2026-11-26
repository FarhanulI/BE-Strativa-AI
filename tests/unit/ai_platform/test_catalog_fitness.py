"""T-018 / AC-60 (D-26, D-28): catalog fitness over every (task, model) pair, DB-free.

Reads the committed catalog through the production loader (``allow_unverified`` left at its
default, so an unverified entry fails here) and the built-in task registry with the default cost
ceilings. For every pair eligible by capability, modality and quality it checks:
(a) the worst-case output cost at the task's default ``max_output_units``, clamped to the model
maximum, does not exceed the cost-class ceiling; (b) the largest input the ceiling allows,
``floor((ceiling - output cost) / input price)``, is at least ``task_min_input_units``.
The full table is printed (run with ``-s`` to see it).
"""

from __future__ import annotations

from pathlib import Path

import pytest

import app.ai_platform as ai_platform_package
from app.ai_platform.catalog import CatalogModel, ModelCatalog, load_catalog
from app.ai_platform.config import AiPlatformConfig
from app.ai_platform.enums import AiTaskName, CostClass
from app.ai_platform.pricing import cost_micro_usd
from app.ai_platform.tasks import AiTaskDefinition, AiTaskRegistry
from tests.helpers.synthetic_catalog import chat_entry

CATALOG_PATH = Path(ai_platform_package.__file__).parent / "catalog_data" / "models.json"
_MILLION = 1_000_000


@pytest.fixture(scope="module")
def catalog() -> ModelCatalog:
    return load_catalog(CATALOG_PATH)


@pytest.fixture(scope="module")
def ceilings() -> AiPlatformConfig:
    return AiPlatformConfig(_env_file=None)  # type: ignore[call-arg]


def _eligible(task: AiTaskDefinition, catalog: ModelCatalog) -> list[CatalogModel]:
    return [
        entry
        for entry in catalog.enabled_models()
        if task.capabilities <= entry.capabilities
        and task.input_modalities <= entry.input_modalities
        and task.output_modalities <= entry.output_modalities
        and entry.quality_tier >= task.quality
    ]


def _row(
    task: AiTaskDefinition, entry: CatalogModel, ceiling: int, minimum: int
) -> dict[str, object]:
    output_units = (
        0
        if task.default_max_output_units is None
        else min(task.default_max_output_units, entry.max_output_units or 0)
    )
    output_cost = cost_micro_usd(output_units, entry.output_micro_usd_per_million_units)
    price = entry.input_micro_usd_per_million_units
    remaining = ceiling - output_cost
    max_input = (remaining * _MILLION) // price if remaining >= 0 else 0
    return {
        "task": task.name.value,
        "model": f"{entry.provider}/{entry.model}",
        "ceiling": ceiling,
        "output_cost": output_cost,
        "max_input_units": max_input,
        "required_min": minimum,
        "ok": output_cost <= ceiling and max_input >= minimum,
    }


def test_catalog_file_is_fully_verified_and_has_a_minimum_for_every_task(
    catalog: ModelCatalog,
) -> None:
    assert catalog.entries and all(entry.verified for entry in catalog.entries)
    assert set(catalog.task_min_input_units) == set(AiTaskName)


def test_every_task_has_an_eligible_enabled_model(catalog: ModelCatalog) -> None:
    for task in AiTaskRegistry().list():
        assert _eligible(task, catalog), f"no eligible model for {task.name.value}"


def test_ac60_every_task_and_eligible_model_fits_its_cost_ceiling(
    catalog: ModelCatalog, ceilings: AiPlatformConfig
) -> None:
    rows = [
        _row(
            task,
            entry,
            ceilings.cost_ceiling_micro_usd(task.cost),
            catalog.task_min_input_units[task.name],
        )
        for task in AiTaskRegistry().list()
        for entry in _eligible(task, catalog)
    ]
    print("\nAC-60 fitness table (micro-USD, units)")
    print(
        f"{'task':28} {'model':32} {'ceiling':>8} {'out cost':>9} {'max input':>10} {'min':>8} ok"
    )
    for row in rows:
        print(
            f"{row['task']:28} {row['model']:32} {row['ceiling']:>8} {row['output_cost']:>9} "
            f"{row['max_input_units']:>10} {row['required_min']:>8} {row['ok']}"
        )
    failures = [row for row in rows if not row["ok"]]
    assert rows and not failures, f"AC-60 violations: {failures}"


def test_the_check_detects_a_violation() -> None:
    """A model priced far too high fails; proves the assertion can fail."""
    task = AiTaskRegistry().get(AiTaskName.GENERATE_HOOK_VARIATIONS)
    assert task.cost is CostClass.LOW
    pricey = ModelCatalog.from_dict(
        {
            "catalog_version": "t",
            "price_version": "t",
            "models": [chat_entry(output_micro_usd_per_million_units=50_000_000)],
        }
    ).entries[0]
    assert _row(task, pricey, 20_000, 8_000)["ok"] is False
    cheap = ModelCatalog.from_dict(
        {"catalog_version": "t", "price_version": "t", "models": [chat_entry()]}
    ).entries[0]
    assert _row(task, cheap, 20_000, 8_000)["ok"] is True
