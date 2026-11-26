"""Router tests (spec 10.2, AC-13, AC-14, AC-17 router part, AC-8 router part, AC-21, INV-5).

Unit only: synthetic catalogs, fake provider ids, no I/O.
"""

from __future__ import annotations

import ast
import inspect
import json
import random
from dataclasses import FrozenInstanceError
from decimal import ROUND_CEILING, Decimal
from pathlib import Path
from typing import Any

import pytest

from app.ai_platform import router as router_module
from app.ai_platform.catalog import ModelCatalog
from app.ai_platform.enums import (
    AiCapability,
    AiModality,
    AiTaskName,
    LatencyClass,
    QualityClass,
)
from app.ai_platform.errors import (
    AiBudgetExceeded,
    AiInputTooLarge,
    AiModalityNotSupported,
    AiNoRoute,
    AiProviderNotConfigured,
)
from app.ai_platform.router import (
    CandidateDecision,
    ReasonCode,
    RoutedModel,
    RoutingFailure,
    RoutingInput,
    RoutingResult,
    route,
    routing_error_class,
)
from app.ai_platform.tasks import AiTaskDefinition, AiTaskRegistry
from tests.helpers.synthetic_catalog import (
    FAKE_PROVIDER_P1,
    FAKE_PROVIDER_P2,
    catalog_dict,
    chat_entry,
    embed_entry,
)

P1, P2 = FAKE_PROVIDER_P1, FAKE_PROVIDER_P2
ROUTER_SOURCE = Path(inspect.getfile(router_module))

# --- builders ---


def entry(model: str, provider: str = P1, **overrides: Any) -> dict[str, Any]:
    return chat_entry(provider=provider, model=model, **overrides)


def embed(model: str, provider: str = P1, **overrides: Any) -> dict[str, Any]:
    overrides.setdefault("quality_tier", "standard")
    return embed_entry(provider=provider, model=model, **overrides)


def catalog_of(*entries: dict[str, Any]) -> ModelCatalog:
    return ModelCatalog.from_dict(catalog_dict(*entries))


def task_of(
    latency: LatencyClass = LatencyClass.STANDARD,
    quality: QualityClass = QualityClass.STANDARD,
    capabilities: frozenset[AiCapability] | None = None,
) -> AiTaskDefinition:
    base = AiTaskRegistry().get(AiTaskName.GENERATE_HOOK_VARIATIONS)
    return base.model_copy(
        update={
            "latency": latency,
            "quality": quality,
            "capabilities": capabilities
            or frozenset({AiCapability.TEXT_GENERATION, AiCapability.STRUCTURED_OUTPUT}),
        }
    )


def build_input(base_catalog: ModelCatalog, /, **overrides: Any) -> RoutingInput:
    providers = {m.provider for m in base_catalog.models()}
    values: dict[str, Any] = {
        "task": task_of(),
        "input_modalities_present": frozenset({AiModality.TEXT}),
        "estimated_input_units": 1_000,
        "context_safety_margin_percent": 10,
        "max_output_units": 500,
        "quality_floor": None,
        "cost_ceiling_micro_usd": 1_000_000,
        "remaining_budget_micro_usd": 10_000_000,
        "provider_configured": dict.fromkeys(providers, True),
        "provider_billing_mode": dict.fromkeys(providers, "free_tier"),
        "unavailable_models": frozenset(),
        "pinned": None,
        "routing_version": "rv-test-1",
        "catalog": base_catalog,
    }
    values.update(overrides)
    return RoutingInput(**values)


def run(*entries: dict[str, Any], **overrides: Any) -> RoutingResult:
    return route(build_input(catalog_of(*entries), **overrides))


def reasons(result: RoutingResult) -> dict[str, str | None]:
    return {str(item["model"]): item["reason_code"] for item in result.snapshot}  # type: ignore[misc]


def order(result: RoutingResult) -> list[str]:
    return [candidate.model for candidate in result.candidates]


GOOD = "good-model"

# --- AC-13: each filter step alone, with its reason code ---

# (step name, entry overrides for the failing model, input overrides, expected reason)
_STEP_CASES: list[tuple[str, dict[str, Any], dict[str, Any], str]] = [
    ("disabled", {"enabled": False}, {}, "disabled"),
    ("capability", {"capabilities": ["text_generation"]}, {}, "capability"),
    (
        "modality-input",
        {},
        {"input_modalities_present": frozenset({AiModality.TEXT, AiModality.IMAGE})},
        "modality",
    ),
    ("modality-output", {"output_modalities": ["audio"]}, {}, "modality"),
    ("context", {"context_window_units": 1_000}, {}, "context"),
    ("quality", {"quality_tier": "basic"}, {}, "quality"),
    (
        "cost_class",
        {"input_micro_usd_per_million_units": 5_000_000_000},
        {"cost_ceiling_micro_usd": 10_000},
        "cost_class",
    ),
    ("unavailable", {}, {"unavailable_models": frozenset({(P1, "bad-model")})}, "unavailable"),
    (
        "budget",
        {"output_micro_usd_per_million_units": 6_000_000},
        {"remaining_budget_micro_usd": 1_000},
        "budget",
    ),
]


def _good_for(case_input: dict[str, Any]) -> dict[str, Any]:
    """A model that passes every step for the given input overrides."""
    caps = ["text_generation", "structured_output"]
    if AiModality.IMAGE in case_input.get("input_modalities_present", frozenset()):
        # The "good" model must also accept the image so only the bad one fails modality.
        return entry(GOOD, input_modalities=["text", "image"], capabilities=caps)
    return entry(GOOD, capabilities=caps)


@pytest.mark.parametrize(
    ("name", "bad", "inputs", "reason"), _STEP_CASES, ids=lambda v: str(v)[:20]
)
def test_each_step_alone_removes_the_right_model(
    name: str, bad: dict[str, Any], inputs: dict[str, Any], reason: str
) -> None:
    result = run(_good_for(inputs), entry("bad-model", **bad), **inputs)
    assert order(result) == [GOOD]
    assert reasons(result) == {GOOD: None, "bad-model": reason}
    assert result.failure is None


def test_step_not_configured_alone() -> None:
    result = run(
        entry(GOOD, provider=P1),
        entry("other-model", provider=P2),
        provider_configured={P1: True, P2: False},
        provider_billing_mode={P1: "free_tier", P2: "free_tier"},
    )
    assert order(result) == [GOOD]
    assert reasons(result) == {GOOD: None, "other-model": "not_configured"}


_STEP_ORDER = [
    "disabled",
    "capability",
    "modality",
    "not_configured",
    "context",
    "quality",
    "cost_class",
    "unavailable",
    "budget",
]


def test_every_reason_code_is_covered_in_step_order() -> None:
    assert [code.value for code in ReasonCode][:-1] == _STEP_ORDER
    assert ReasonCode.BILLING_MODE.value == "billing_mode"


def test_a_model_failing_several_steps_gets_the_first_reason() -> None:
    # Fails capability (1), context (3), quality (4) and is unconfigured (2): capability wins.
    result = run(
        entry(GOOD),
        entry(
            "multi",
            provider=P2,
            capabilities=["text_generation"],
            context_window_units=10,
            quality_tier="basic",
        ),
        provider_configured={P1: True, P2: False},
        provider_billing_mode={P1: "free_tier", P2: "free_tier"},
    )
    assert reasons(result)["multi"] == "capability"
    # Without the capability gap the next step, not_configured, wins over context and quality.
    result = run(
        entry(GOOD),
        entry("multi", provider=P2, context_window_units=10, quality_tier="basic"),
        provider_configured={P1: True, P2: False},
        provider_billing_mode={P1: "free_tier", P2: "free_tier"},
    )
    assert reasons(result)["multi"] == "not_configured"
    # Context wins over quality, quality over unavailable.
    result = run(entry(GOOD), entry("multi", context_window_units=10, quality_tier="basic"))
    assert reasons(result)["multi"] == "context"
    result = run(
        entry(GOOD),
        entry("multi", quality_tier="basic"),
        unavailable_models=frozenset({(P1, "multi")}),
    )
    assert reasons(result)["multi"] == "quality"


def test_quality_floor_below_the_task_class_has_no_effect() -> None:
    models = (entry("std", quality_tier="standard"), entry("low", quality_tier="basic"))
    without = run(*models)
    below = run(*models, quality_floor=QualityClass.BASIC)
    assert order(without) == order(below) == ["std"]
    assert without.snapshot_json() == below.snapshot_json()


def test_quality_floor_above_the_task_class_raises_the_bar() -> None:
    models = (entry("std", quality_tier="standard"), entry("top", quality_tier="high"))
    assert order(run(*models)) == ["std", "top"] or order(run(*models)) == ["top", "std"]
    raised = run(*models, quality_floor=QualityClass.HIGH)
    assert order(raised) == ["top"]
    assert reasons(raised)["std"] == "quality"


def test_a_higher_task_class_is_not_lowered_by_a_floor() -> None:
    models = (entry("std", quality_tier="standard"), entry("top", quality_tier="high"))
    result = run(*models, task=task_of(quality=QualityClass.HIGH), quality_floor=QualityClass.BASIC)
    assert order(result) == ["top"]


# --- failure decided by the step at which the list became empty ---

_ALONE_FAILURE: list[tuple[str, dict[str, Any], dict[str, Any], RoutingFailure]] = [
    ("disabled", {"enabled": False}, {}, RoutingFailure.NO_ROUTE),
    ("capability", {"capabilities": ["text_generation"]}, {}, RoutingFailure.NO_ROUTE),
    (
        "modality",
        {},
        {"input_modalities_present": frozenset({AiModality.TEXT, AiModality.IMAGE})},
        RoutingFailure.MODALITY_NOT_SUPPORTED,
    ),
    (
        "not_configured",
        {},
        {"provider_configured": {P1: False}},
        RoutingFailure.PROVIDER_NOT_CONFIGURED,
    ),
    ("context", {"context_window_units": 1_000}, {}, RoutingFailure.INPUT_TOO_LARGE),
    ("quality", {"quality_tier": "basic"}, {}, RoutingFailure.NO_ROUTE),
    (
        "cost_class",
        {"input_micro_usd_per_million_units": 5_000_000_000},
        {"cost_ceiling_micro_usd": 10_000},
        RoutingFailure.NO_ROUTE,
    ),
    ("unavailable", {}, {"unavailable_models": frozenset({(P1, "only")})}, RoutingFailure.NO_ROUTE),
    ("budget", {}, {"remaining_budget_micro_usd": 0}, RoutingFailure.BUDGET_EXCEEDED),
]


@pytest.mark.parametrize(
    ("name", "bad", "inputs", "failure"), _ALONE_FAILURE, ids=lambda v: str(v)[:24]
)
def test_failure_when_a_single_step_empties_the_list(
    name: str, bad: dict[str, Any], inputs: dict[str, Any], failure: RoutingFailure
) -> None:
    result = run(entry("only", **bad), **inputs)
    assert result.candidates == ()
    assert result.failure is failure
    assert reasons(result)["only"] == name


def test_input_too_large_only_when_every_model_fails_at_context() -> None:
    all_context = run(
        entry("a", context_window_units=1_000), entry("b", context_window_units=1_200)
    )
    assert all_context.failure is RoutingFailure.INPUT_TOO_LARGE
    # One model fails context, the other fails quality: the list empties at step 4.
    mixed = run(entry("a", context_window_units=1_000), entry("b", quality_tier="basic"))
    assert mixed.failure is RoutingFailure.NO_ROUTE


def test_budget_exceeded_when_the_budget_step_empties_the_list() -> None:
    result = run(entry("a"), entry("b"), remaining_budget_micro_usd=1)
    assert result.failure is RoutingFailure.BUDGET_EXCEEDED
    assert set(reasons(result).values()) == {"budget"}


def test_budget_exceeded_not_reported_when_an_earlier_step_emptied_the_list() -> None:
    result = run(entry("a", quality_tier="basic"), remaining_budget_micro_usd=0)
    assert result.failure is RoutingFailure.NO_ROUTE


def test_modality_failure_wins_only_at_step_one() -> None:
    image_only = {"input_modalities_present": frozenset({AiModality.TEXT, AiModality.IMAGE})}
    # One model fails capability, one fails modality: still modality_not_supported.
    mixed = run(entry("a", capabilities=["text_generation"]), entry("b"), **image_only)
    assert mixed.failure is RoutingFailure.MODALITY_NOT_SUPPORTED
    # A modality-rejected model plus an unconfigured one: the list empties at step 2.
    later = run(
        entry("a"),
        entry("b", provider=P2, input_modalities=["text", "image"]),
        provider_configured={P1: True, P2: False},
        provider_billing_mode={P1: "free_tier", P2: "free_tier"},
        **image_only,
    )
    assert later.failure is RoutingFailure.PROVIDER_NOT_CONFIGURED


def test_empty_catalog_is_no_route() -> None:
    # catalog_dict falls back to defaults for no entries, so build an empty one explicitly.
    empty = ModelCatalog.from_dict({"catalog_version": "v", "price_version": "p", "models": []})
    result = route(build_input(empty))
    assert result.failure is RoutingFailure.NO_ROUTE
    assert result.snapshot == ()


@pytest.mark.parametrize(
    ("failure", "error"),
    [
        (RoutingFailure.PROVIDER_NOT_CONFIGURED, AiProviderNotConfigured),
        (RoutingFailure.INPUT_TOO_LARGE, AiInputTooLarge),
        (RoutingFailure.BUDGET_EXCEEDED, AiBudgetExceeded),
        (RoutingFailure.MODALITY_NOT_SUPPORTED, AiModalityNotSupported),
        (RoutingFailure.NO_ROUTE, AiNoRoute),
    ],
)
def test_failure_maps_to_the_error_class(failure: RoutingFailure, error: type[Exception]) -> None:
    assert routing_error_class(failure) is error


def test_every_failure_value_is_mapped() -> None:
    for failure in RoutingFailure:
        assert issubclass(routing_error_class(failure), Exception)
    assert {f.value for f in RoutingFailure} == {
        "provider_not_configured",
        "input_too_large",
        "budget_exceeded",
        "modality_not_supported",
        "no_route",
    }


# --- AC-14 / INV-5: ranking ---


def _priced(model: str, latency: int, in_price: int, **extra: Any) -> dict[str, Any]:
    return entry(
        model,
        latency_p50_ms=latency,
        input_micro_usd_per_million_units=in_price,
        output_micro_usd_per_million_units=0,
        **extra,
    )


def test_interactive_ranks_by_latency_then_cost_then_model() -> None:
    models = (
        _priced("slow-cheap", 900, 10_000),
        _priced("fast-dear", 100, 900_000),
        _priced("fast-cheap-b", 100, 10_000),
        _priced("fast-cheap-a", 100, 10_000),
    )
    result = run(*models, task=task_of(latency=LatencyClass.INTERACTIVE))
    assert order(result) == ["fast-cheap-a", "fast-cheap-b", "fast-dear", "slow-cheap"]


def test_standard_ranks_by_cost_then_latency_then_model() -> None:
    models = (
        _priced("slow-cheap", 900, 10_000),
        _priced("fast-dear", 100, 900_000),
        _priced("fast-cheap-b", 100, 10_000),
        _priced("fast-cheap-a", 100, 10_000),
        _priced("mid-cheap", 500, 10_000),
    )
    result = run(*models, task=task_of(latency=LatencyClass.STANDARD))
    assert order(result) == [
        "fast-cheap-a",
        "fast-cheap-b",
        "mid-cheap",
        "slow-cheap",
        "fast-dear",
    ]


def test_batch_ranks_by_cost_then_model_ignoring_latency() -> None:
    models = (
        _priced("b-fast", 100, 10_000),
        _priced("a-slow", 900, 10_000),
        _priced("c-dear", 50, 900_000),
    )
    result = run(*models, task=task_of(latency=LatencyClass.BATCH))
    assert order(result) == ["a-slow", "b-fast", "c-dear"]


@pytest.mark.parametrize("latency", list(LatencyClass))
def test_provider_is_the_last_tie_break(latency: LatencyClass) -> None:
    models = (_priced("same", 100, 10_000, provider=P2), _priced("same", 100, 10_000, provider=P1))
    result = run(*models, task=task_of(latency=latency))
    assert [(c.provider, c.model) for c in result.candidates] == [(P1, "same"), (P2, "same")]
    assert [c.route_rank for c in result.candidates] == [1, 2]


def _mixed_catalog_entries() -> list[dict[str, Any]]:
    return [
        _priced("m-a", 300, 20_000),
        _priced("m-b", 300, 20_000),
        _priced("m-c", 100, 20_000),
        _priced("m-d", 100, 10_000, provider=P2),
        _priced("m-e", 700, 10_000),
        entry("m-off", enabled=False),
        entry("m-low", quality_tier="basic"),
        _priced("m-same", 300, 20_000, provider=P2),
        _priced("m-same", 300, 20_000, provider=P1),
        entry("m-big", input_micro_usd_per_million_units=5_000_000_000),
    ]


@pytest.mark.parametrize("latency", list(LatencyClass))
def test_repeated_calls_and_shuffled_catalogs_are_byte_identical(latency: LatencyClass) -> None:
    entries = _mixed_catalog_entries()
    base_input = build_input(
        catalog_of(*entries),
        task=task_of(latency=latency),
        cost_ceiling_micro_usd=10_000,
        provider_billing_mode={P1: "free_tier", P2: "free_tier"},
    )
    expected = route(base_input)
    assert expected.candidates
    assert route(base_input).snapshot_json() == expected.snapshot_json()
    rng = random.Random(20260101)
    for _ in range(60):
        shuffled = entries[:]
        rng.shuffle(shuffled)
        result = route(
            build_input(
                catalog_of(*shuffled),
                task=task_of(latency=latency),
                cost_ceiling_micro_usd=10_000,
                provider_billing_mode={P1: "free_tier", P2: "free_tier"},
            )
        )
        assert result.snapshot_json() == expected.snapshot_json()
        assert result.candidates == expected.candidates
        assert result.snapshot == expected.snapshot


def test_snapshot_shape_and_order() -> None:
    result = run(
        _priced("z-ok", 100, 10_000),
        _priced("a-ok", 100, 20_000),
        entry("y-bad", quality_tier="basic"),
        entry("b-off", enabled=False),
    )
    assert [dict(item) for item in result.snapshot] == [
        {"provider": P1, "model": "z-ok", "eligible": True, "reason_code": None},
        {"provider": P1, "model": "a-ok", "eligible": True, "reason_code": None},
        {"provider": P1, "model": "b-off", "eligible": False, "reason_code": "disabled"},
        {"provider": P1, "model": "y-bad", "eligible": False, "reason_code": "quality"},
    ]
    for item in result.snapshot:
        assert set(item) == {"provider", "model", "eligible", "reason_code"}


def test_snapshot_json_is_canonical() -> None:
    result = run(_priced("a", 100, 10_000), entry("b", enabled=False))
    text = result.snapshot_json()
    assert text == json.dumps(json.loads(text), sort_keys=True, separators=(",", ":"))
    assert text.startswith('[{"eligible":true,')
    assert " " not in text and "\n" not in text
    assert text.isascii()


def test_candidates_carry_rank_cost_and_billing_mode() -> None:
    result = run(_priced("a", 100, 10_000), _priced("b", 100, 20_000))
    assert result.candidates == (
        RoutedModel(P1, "a", "free_tier", 11, 1, 500),
        RoutedModel(P1, "b", "free_tier", 22, 2, 500),
    )
    assert result.routing_version == "rv-test-1"


# --- AC-17 router part / INV-29: billing-mode lock ---


def _p1p2(p1_latency: int, p2_latency: int) -> tuple[dict[str, Any], ...]:
    return (
        _priced("model-a", p1_latency, 10_000, provider=P1),
        _priced("model-b", p1_latency + 1, 10_000, provider=P1),
        _priced("model-c", p2_latency, 10_000, provider=P2),
    )


_INTERACTIVE = {"task": task_of(latency=LatencyClass.INTERACTIVE)}
_MODES = {"provider_billing_mode": {P1: "free_tier", P2: "paid"}}


def test_billing_lock_keeps_the_free_tier_mode_when_it_ranks_first() -> None:
    result = run(*_p1p2(100, 500), **_INTERACTIVE, **_MODES)
    assert order(result) == ["model-a", "model-b"]
    assert {c.billing_mode for c in result.candidates} == {"free_tier"}
    assert reasons(result)["model-c"] == "billing_mode"


def test_billing_lock_reverses_when_the_paid_mode_ranks_first() -> None:
    result = run(*_p1p2(500, 100), **_INTERACTIVE, **_MODES)
    assert order(result) == ["model-c"]
    assert {c.billing_mode for c in result.candidates} == {"paid"}
    assert reasons(result)["model-a"] == "billing_mode"
    assert reasons(result)["model-b"] == "billing_mode"
    assert result.failure is None


def test_a_request_never_mixes_billing_modes() -> None:
    for p1_latency, p2_latency in [(100, 500), (500, 100), (300, 300)]:
        result = run(*_p1p2(p1_latency, p2_latency), **_INTERACTIVE, **_MODES)
        assert len({c.billing_mode for c in result.candidates}) == 1


def test_the_same_model_flips_mode_purely_by_the_mapping() -> None:
    models = (_priced("model-a", 100, 10_000, provider=P1),)
    free = run(*models, provider_billing_mode={P1: "free_tier"})
    paid = run(*models, provider_billing_mode={P1: "paid"})
    assert [c.billing_mode for c in free.candidates] == ["free_tier"]
    assert [c.billing_mode for c in paid.candidates] == ["paid"]
    assert order(free) == order(paid) == ["model-a"]


def test_billing_mode_lock_does_not_change_cost_estimates() -> None:
    free = run(_priced("m", 100, 10_000), provider_billing_mode={P1: "free_tier"})
    paid = run(_priced("m", 100, 10_000), provider_billing_mode={P1: "paid"})
    assert (
        free.candidates[0].estimated_cost_micro_usd == paid.candidates[0].estimated_cost_micro_usd
    )


def test_missing_billing_mode_for_a_candidate_provider_is_an_error() -> None:
    with pytest.raises(ValueError):
        run(entry("a"), provider_billing_mode={})


def test_missing_billing_mode_is_not_needed_for_eliminated_providers() -> None:
    result = run(
        entry("a", provider=P1),
        entry("b", provider=P2),
        provider_configured={P1: True, P2: False},
        provider_billing_mode={P1: "free_tier"},
    )
    assert order(result) == ["a"]


# --- AC-8 router part: provider configuration ---


def test_provider_missing_from_the_configured_mapping_is_not_configured() -> None:
    result = run(
        entry("a", provider=P1),
        entry("b", provider=P2),
        provider_configured={P1: True},
        provider_billing_mode={P1: "free_tier", P2: "free_tier"},
    )
    assert order(result) == ["a"]
    assert reasons(result)["b"] == "not_configured"


def test_provider_configured_false_is_not_configured() -> None:
    result = run(
        entry("a", provider=P1),
        entry("b", provider=P2),
        provider_configured={P1: False, P2: True},
        provider_billing_mode={P1: "free_tier", P2: "free_tier"},
    )
    assert order(result) == ["b"]
    assert reasons(result)["a"] == "not_configured"


def test_only_this_step_emptying_the_list_gives_provider_not_configured() -> None:
    result = run(entry("a"), entry("b", provider=P2), provider_configured={})
    assert result.failure is RoutingFailure.PROVIDER_NOT_CONFIGURED
    assert set(reasons(result).values()) == {"not_configured"}


def test_with_only_one_provider_configured_the_router_routes_to_it() -> None:
    result = run(
        _priced("cheap", 100, 1_000, provider=P1),
        _priced("dear", 100, 900_000, provider=P2),
        provider_configured={P1: False, P2: True},
        provider_billing_mode={P2: "paid"},
    )
    assert [(c.provider, c.model) for c in result.candidates] == [(P2, "dear")]


# --- AC-21: modality ---


def test_an_image_part_for_a_text_only_task_is_modality_not_supported() -> None:
    task = AiTaskRegistry().get(AiTaskName.GENERATE_HOOK_VARIATIONS)
    result = run(
        entry("a"),
        entry("b"),
        task=task,
        input_modalities_present=frozenset({AiModality.TEXT, AiModality.IMAGE}),
    )
    assert result.failure is RoutingFailure.MODALITY_NOT_SUPPORTED
    assert routing_error_class(result.failure) is AiModalityNotSupported
    assert set(reasons(result).values()) == {"modality"}


def test_an_image_capable_model_is_selected_for_a_task_declaring_image_input() -> None:
    image_task = task_of(
        capabilities=frozenset(
            {
                AiCapability.TEXT_GENERATION,
                AiCapability.STRUCTURED_OUTPUT,
                AiCapability.IMAGE_UNDERSTANDING,
            }
        )
    ).model_copy(update={"input_modalities": frozenset({AiModality.TEXT, AiModality.IMAGE})})
    result = run(
        entry("text-only"),
        entry(
            "image-capable",
            capabilities=["text_generation", "structured_output", "image_understanding"],
            input_modalities=["text", "image"],
        ),
        task=image_task,
        input_modalities_present=frozenset({AiModality.TEXT, AiModality.IMAGE}),
    )
    assert order(result) == ["image-capable"]
    assert reasons(result)["text-only"] == "capability"


# --- embedding: pinned model, no fallback ---


def _embed_input(*entries: dict[str, Any], **overrides: Any) -> RoutingResult:
    return run(
        *entries,
        **{
            "task": AiTaskRegistry().get(AiTaskName.EMBED_TEXT),
            "max_output_units": None,
            **overrides,
        },
    )


def test_pinned_considers_only_the_pinned_model() -> None:
    result = _embed_input(
        embed("embed-a"), embed("embed-b"), embed("embed-c", provider=P2), pinned=(P1, "embed-b")
    )
    assert order(result) == ["embed-b"]
    assert [item["model"] for item in result.snapshot] == ["embed-b"]


def test_without_pinned_embedding_models_are_ranked_normally() -> None:
    result = _embed_input(embed("embed-a"), embed("embed-b"))
    assert order(result) == ["embed-a", "embed-b"]


def test_unavailable_pinned_model_gives_no_route_and_no_fallback() -> None:
    result = _embed_input(
        embed("embed-a"),
        embed("embed-b"),
        pinned=(P1, "embed-a"),
        unavailable_models=frozenset({(P1, "embed-a")}),
    )
    assert result.candidates == ()
    assert result.failure is RoutingFailure.NO_ROUTE
    assert [dict(item) for item in result.snapshot] == [
        {"provider": P1, "model": "embed-a", "eligible": False, "reason_code": "unavailable"}
    ]


def test_missing_pinned_model_gives_no_route_with_an_empty_snapshot() -> None:
    result = _embed_input(embed("embed-a"), pinned=(P1, "not-in-catalog"))
    assert result.failure is RoutingFailure.NO_ROUTE
    assert result.snapshot == ()


def test_pinned_model_with_an_unconfigured_provider_follows_the_mapping() -> None:
    result = _embed_input(embed("embed-a"), pinned=(P1, "embed-a"), provider_configured={})
    assert result.failure is RoutingFailure.PROVIDER_NOT_CONFIGURED


def test_disabled_pinned_model_gives_no_route() -> None:
    result = _embed_input(embed("embed-a", enabled=False), pinned=(P1, "embed-a"))
    assert result.failure is RoutingFailure.NO_ROUTE
    assert reasons(result) == {"embed-a": "disabled"}


def test_chat_models_never_serve_an_embedding_task() -> None:
    result = _embed_input(entry("chat-a"), embed("embed-a"))
    assert order(result) == ["embed-a"]
    assert reasons(result)["chat-a"] == "capability"


def test_embedding_context_has_no_output_part_and_cost_uses_the_embedding_estimate() -> None:
    # padded input = 1100; window 1100 fits exactly because the output part is 0.
    result = _embed_input(
        embed("embed-a", context_window_units=1_100, input_micro_usd_per_million_units=1_000_000)
    )
    assert order(result) == ["embed-a"]
    assert result.candidates[0].estimated_cost_micro_usd == 1_100
    tight = _embed_input(embed("embed-a", context_window_units=1_099))
    assert tight.failure is RoutingFailure.INPUT_TOO_LARGE


# --- integer arithmetic against an independent Decimal reference ---


def _ceil(value: Decimal) -> int:
    return int(value.to_integral_value(rounding=ROUND_CEILING))


@pytest.mark.parametrize("units", [0, 1, 7, 99, 100, 101, 12_345])
@pytest.mark.parametrize("margin", [0, 1, 10, 33, 99])
@pytest.mark.parametrize("prices", [(0, 0), (1, 1), (150_000, 600_000), (999_999, 7_777_777)])
def test_margin_and_cost_match_a_decimal_reference(
    units: int, margin: int, prices: tuple[int, int]
) -> None:
    in_price, out_price = prices
    out = 500
    padded = _ceil(Decimal(units) * (100 + margin) / 100)
    expected = _ceil(Decimal(padded) * in_price / 1_000_000) + _ceil(
        Decimal(out) * out_price / 1_000_000
    )
    kwargs = {
        "estimated_input_units": units,
        "context_safety_margin_percent": margin,
        "max_output_units": out,
    }
    model = entry(
        "m",
        input_micro_usd_per_million_units=in_price,
        output_micro_usd_per_million_units=out_price,
        context_window_units=padded + out,
    )
    result = run(model, **kwargs)
    assert result.candidates[0].estimated_cost_micro_usd == expected
    too_small = entry(
        "m",
        input_micro_usd_per_million_units=in_price,
        output_micro_usd_per_million_units=out_price,
        context_window_units=padded + out - 1,
    )
    assert run(too_small, **kwargs).failure is RoutingFailure.INPUT_TOO_LARGE


def test_output_units_are_clamped_to_each_models_own_maximum() -> None:
    result = run(
        entry("small-cap", max_output_units=100, output_micro_usd_per_million_units=1_000_000),
        entry("big-cap", max_output_units=8_000, output_micro_usd_per_million_units=1_000_000),
        max_output_units=500,
        task=task_of(latency=LatencyClass.BATCH),
    )
    by_model = {c.model: c.estimated_cost_micro_usd for c in result.candidates}
    # input part: ceil(1100 * 150000 / 1e6) = 165
    assert by_model == {"small-cap": 165 + 100, "big-cap": 165 + 500}


def test_clamped_output_is_used_for_the_context_check() -> None:
    # 1100 padded input + 100 clamped output = 1200 fits; the unclamped 500 would not.
    result = run(entry("m", max_output_units=100, context_window_units=1_200))
    assert order(result) == ["m"]
    assert run(entry("m", max_output_units=100, context_window_units=1_199)).failure is (
        RoutingFailure.INPUT_TOO_LARGE
    )


def test_cost_ceiling_and_budget_boundaries_are_inclusive() -> None:
    cost = 165 + 300  # 1100 padded input, 500 output at the default prices
    assert order(run(entry("m"), cost_ceiling_micro_usd=cost)) == ["m"]
    assert run(entry("m"), cost_ceiling_micro_usd=cost - 1).failure is RoutingFailure.NO_ROUTE
    assert order(run(entry("m"), remaining_budget_micro_usd=cost)) == ["m"]
    assert run(entry("m"), remaining_budget_micro_usd=cost - 1).failure is (
        RoutingFailure.BUDGET_EXCEEDED
    )


# --- router clarifications (rev 5 and rev 6: D-24, D-25, D-30, D-31) ---


@pytest.mark.parametrize("latency", list(LatencyClass))
def test_model_name_sorts_before_provider_and_provider_decides_equal_names(
    latency: LatencyClass,
) -> None:
    task = task_of(latency=latency)
    # Equal in every earlier key: the smaller model name wins even on the larger provider id.
    cross = run(
        _priced("b", 100, 10_000, provider=P1), _priced("a", 100, 10_000, provider=P2), task=task
    )
    assert [(c.provider, c.model) for c in cross.candidates] == [(P2, "a"), (P1, "b")]
    cross_reversed = run(
        _priced("b", 100, 10_000, provider=P2), _priced("a", 100, 10_000, provider=P1), task=task
    )
    assert [(c.provider, c.model) for c in cross_reversed.candidates] == [(P1, "a"), (P2, "b")]
    # Equal model names: the provider decides.
    same = run(
        _priced("m", 100, 10_000, provider=P2), _priced("m", 100, 10_000, provider=P1), task=task
    )
    assert [c.provider for c in same.candidates] == sorted([P1, P2])


def test_supports_json_schema_changes_neither_ranking_nor_snapshot() -> None:
    def build(flag_x: bool, flag_y: bool) -> RoutingResult:
        return run(
            _priced("x", 100, 10_000, supports_json_schema=flag_x),
            _priced("y", 100, 20_000, supports_json_schema=flag_y),
        )

    results = [build(True, False), build(False, True), build(True, True), build(False, False)]
    for result in results[1:]:
        assert result.candidates == results[0].candidates
        assert result.snapshot_json() == results[0].snapshot_json()
        assert order(result) == ["x", "y"]


def test_one_estimate_serves_the_ceiling_the_budget_and_the_candidate() -> None:
    estimate = run(entry("m")).candidates[0].estimated_cost_micro_usd
    assert estimate > 1
    exact = run(entry("m"), cost_ceiling_micro_usd=estimate, remaining_budget_micro_usd=estimate)
    assert order(exact) == ["m"]
    assert exact.candidates[0].estimated_cost_micro_usd == estimate
    lower_ceiling = run(
        entry("m"), cost_ceiling_micro_usd=estimate - 1, remaining_budget_micro_usd=estimate
    )
    assert lower_ceiling.failure is RoutingFailure.NO_ROUTE
    assert reasons(lower_ceiling) == {"m": "cost_class"}
    lower_budget = run(
        entry("m"), cost_ceiling_micro_usd=estimate, remaining_budget_micro_usd=estimate - 1
    )
    assert lower_budget.failure is RoutingFailure.BUDGET_EXCEEDED
    assert reasons(lower_budget) == {"m": "budget"}


def test_effective_max_output_units_is_the_clamped_value() -> None:
    result = run(
        entry("low-cap", max_output_units=100),
        entry("high-cap", max_output_units=8_000),
        max_output_units=500,
        task=task_of(latency=LatencyClass.BATCH),
    )
    by_model = {c.model: c.effective_max_output_units for c in result.candidates}
    assert by_model == {"low-cap": 100, "high-cap": 500}


def test_effective_max_output_units_is_none_for_embedding() -> None:
    result = _embed_input(embed("embed-a"))
    assert [c.effective_max_output_units for c in result.candidates] == [None]


@pytest.mark.parametrize("model_max", [100, 500, 8_000])
def test_effective_max_output_units_is_the_context_fit_boundary(model_max: int) -> None:
    padded = 1_100  # 1000 input units with the 10 percent margin
    effective = run(entry("m", max_output_units=model_max)).candidates[0]
    assert effective.effective_max_output_units == min(500, model_max)
    window = padded + (effective.effective_max_output_units or 0)
    assert order(run(entry("m", max_output_units=model_max, context_window_units=window))) == ["m"]
    beyond = run(entry("m", max_output_units=model_max, context_window_units=window - 1))
    assert beyond.failure is RoutingFailure.INPUT_TOO_LARGE


def test_a_pinned_model_is_refused_for_a_non_embedding_task() -> None:
    with pytest.raises(ValueError, match="pinned"):
        build_input(catalog_of(entry("a")), pinned=(P1, "a"))


def test_a_pinned_embedding_model_still_has_no_fallback() -> None:
    result = _embed_input(embed("embed-a"), embed("embed-b"), pinned=(P1, "embed-b"))
    assert order(result) == ["embed-b"]
    unavailable = _embed_input(
        embed("embed-a"),
        embed("embed-b"),
        pinned=(P1, "embed-b"),
        unavailable_models=frozenset({(P1, "embed-b")}),
    )
    assert unavailable.failure is RoutingFailure.NO_ROUTE


def test_interactive_ranks_the_fastest_first_and_other_classes_the_cheapest_first() -> None:
    models = (_priced("slow-cheap", 900, 10_000), _priced("fast-dear", 100, 900_000))
    interactive = run(*models, task=task_of(latency=LatencyClass.INTERACTIVE))
    assert order(interactive) == ["fast-dear", "slow-cheap"]
    for latency in (LatencyClass.STANDARD, LatencyClass.BATCH):
        assert order(run(*models, task=task_of(latency=latency))) == ["slow-cheap", "fast-dear"]


# --- purity ---

_FORBIDDEN_MODULES = {"litellm", "datetime", "time", "random", "os", "sys"}


def _router_tree() -> ast.Module:
    return ast.parse(ROUTER_SOURCE.read_text(encoding="utf-8"))


def _imported_roots(tree: ast.AST) -> set[str]:
    roots: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            roots |= {alias.name.split(".")[0] for alias in node.names}
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            roots.add(node.module.split(".")[0])
    return roots


def test_router_imports_nothing_impure() -> None:
    assert _imported_roots(_router_tree()) & _FORBIDDEN_MODULES == set()


def test_router_has_no_io_calls() -> None:
    called = {
        node.func.id
        for node in ast.walk(_router_tree())
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
    }
    assert called & {"open", "print", "input", "eval", "exec", "__import__"} == set()


def test_router_has_no_global_statements_or_module_level_mutable_state() -> None:
    tree = _router_tree()
    assert not [node for node in ast.walk(tree) if isinstance(node, ast.Global)]
    mutable = (ast.List, ast.Dict, ast.Set, ast.ListComp, ast.DictComp, ast.SetComp)
    for node in tree.body:
        if isinstance(node, ast.Assign | ast.AnnAssign) and node.value is not None:
            assert not isinstance(node.value, mutable), ast.dump(node)
            if isinstance(node.value, ast.Call) and isinstance(node.value.func, ast.Name):
                assert node.value.func.id not in {"list", "dict", "set", "defaultdict"}


def test_router_has_no_floats_and_no_true_division() -> None:
    tree = _router_tree()
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant):
            assert not isinstance(node.value, float)
        if isinstance(node, ast.BinOp | ast.AugAssign):
            assert not isinstance(node.op, ast.Div)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
            assert node.func.id != "float"
    assert "float(" not in ROUTER_SOURCE.read_text(encoding="utf-8")


def test_router_names_no_token_and_no_provider_identifier() -> None:
    source = ROUTER_SOURCE.read_text(encoding="utf-8").lower()
    assert "token" not in source
    for fragment in ("gemini", "openai", "perplexity", "pplx", "claude", "anthropic", "litellm"):
        assert fragment not in source
    names = {name for name in vars(router_module) if not name.startswith("__")}
    for _, cls in inspect.getmembers(router_module, inspect.isclass):
        if cls.__module__ == router_module.__name__:
            names |= {n for n in vars(cls) if not n.startswith("__")}
            names |= set(getattr(cls, "model_fields", {}))
    assert [name for name in names if "token" in name.lower()] == []


def test_router_is_not_exported_from_the_package_root() -> None:
    import app.ai_platform as package

    assert "route" not in vars(package)
    assert "RoutingInput" not in vars(package)


def test_route_does_not_mutate_its_input_or_keep_state() -> None:
    routing_input = build_input(catalog_of(*_mixed_catalog_entries()))
    first = route(routing_input)
    second = route(routing_input)
    assert first == second
    assert first is not second


# --- immutability and validation ---


def test_results_and_input_are_frozen() -> None:
    result = run(entry("a"))
    with pytest.raises(FrozenInstanceError):
        result.failure = RoutingFailure.NO_ROUTE  # type: ignore[misc]
    with pytest.raises(FrozenInstanceError):
        result.candidates[0].model = "x"  # type: ignore[misc]
    with pytest.raises(TypeError):
        result.snapshot[0]["model"] = "x"  # type: ignore[index]
    routing_input = build_input(catalog_of(entry("a")))
    with pytest.raises(ValueError):
        routing_input.estimated_input_units = 5  # type: ignore[misc]
    with pytest.raises(TypeError):
        routing_input.provider_configured[P1] = False  # type: ignore[index]
    decision = CandidateDecision(P1, "a", False, "quality", None, None, None)
    with pytest.raises(FrozenInstanceError):
        decision.eligible = True  # type: ignore[misc]


def test_a_result_needs_a_failure_exactly_when_it_has_no_candidates() -> None:
    with pytest.raises(ValueError):
        RoutingResult(candidates=(), snapshot=(), failure=None, routing_version="v")
    candidate = RoutedModel(P1, "a", "free_tier", 1, 1, 500)
    with pytest.raises(ValueError):
        RoutingResult(
            candidates=(candidate,),
            snapshot=(),
            failure=RoutingFailure.NO_ROUTE,
            routing_version="v",
        )


_INVALID: list[tuple[str, Any]] = [
    ("estimated_input_units", -1),
    ("estimated_input_units", 1.5),
    ("estimated_input_units", True),
    ("estimated_input_units", "10"),
    ("context_safety_margin_percent", -1),
    ("context_safety_margin_percent", 100),
    ("context_safety_margin_percent", 10.0),
    ("max_output_units", 0),
    ("max_output_units", None),  # a generation task needs a value
    ("max_output_units", -5),
    ("quality_floor", "excellent"),
    ("cost_ceiling_micro_usd", -1),
    ("cost_ceiling_micro_usd", 1.0),
    ("remaining_budget_micro_usd", -1),
    ("remaining_budget_micro_usd", None),
    ("provider_configured", {P1: "yes"}),
    ("provider_configured", None),
    ("provider_billing_mode", {P1: "trial"}),
    ("provider_billing_mode", {P1: None}),
    ("unavailable_models", frozenset({"not-a-pair"})),
    ("unavailable_models", [(P1, "a")]),
    ("pinned", ("", "a")),
    ("pinned", (P1, "  ")),
    ("pinned", "a"),
    ("routing_version", ""),
    ("routing_version", "   "),
    ("routing_version", None),
    ("input_modalities_present", frozenset()),
    ("input_modalities_present", frozenset({"text"})),
    ("catalog", {"models": []}),
    ("task", "GENERATE_CONTENT_DRAFT"),
]


@pytest.mark.parametrize(("field", "value"), _INVALID, ids=lambda v: str(v)[:24])
def test_invalid_routing_input_raises_value_error(field: str, value: Any) -> None:
    with pytest.raises(ValueError):
        build_input(catalog_of(entry("a")), **{field: value})


def test_embedding_task_rejects_an_output_unit_value() -> None:
    with pytest.raises(ValueError):
        build_input(
            catalog_of(embed("e")),
            task=AiTaskRegistry().get(AiTaskName.EMBED_TEXT),
            max_output_units=100,
        )


def test_unknown_fields_are_rejected() -> None:
    with pytest.raises(ValueError):
        build_input(catalog_of(entry("a")), surprise=1)


def test_missing_fields_are_rejected() -> None:
    with pytest.raises(ValueError):
        RoutingInput()  # type: ignore[call-arg]


def test_a_valid_input_with_all_optional_values_is_accepted() -> None:
    routing_input = build_input(
        catalog_of(embed("a")),
        task=AiTaskRegistry().get(AiTaskName.EMBED_TEXT),
        max_output_units=None,
        quality_floor=QualityClass.HIGH,
        pinned=(P1, "a"),
    )
    assert routing_input.pinned == (P1, "a")
    assert routing_input.quality_floor is QualityClass.HIGH
