"""T-025 step 2: signature reflection of ``AiOrchestrator.run`` (unit only, no database).

INV-2 and AC-3 (``run`` part): the call has no provider, model, tool or override parameter and no
idempotency parameter (F-1: only ``submit`` has ``idempotency_key``; ``submit`` and
``EmbeddingService.embed_texts`` do not exist yet, so those clauses of AC-3 stay open).
"""

from __future__ import annotations

import inspect
import typing

from app.ai_platform import AiTaskRequest, AiTaskResult
from app.ai_platform.orchestrator import AiOrchestrator

FORBIDDEN_FRAGMENTS = (
    "provider",
    "model",
    "tool",
    "function",
    "override",
    "route",
    "fallback",
    "idempotency",
    "key",
)


def test_run_takes_only_the_context_and_the_request() -> None:
    """INV-2, AC-3: the caller cannot name a provider or a model, or pass an override."""
    parameters = list(inspect.signature(AiOrchestrator.run).parameters)
    assert parameters == ["self", "ctx", "request"]


def test_no_run_parameter_name_mentions_a_provider_model_or_idempotency() -> None:
    """AC-3 (F-1): ``run`` has no idempotency parameter and nothing that selects a route."""
    for name in inspect.signature(AiOrchestrator.run).parameters:
        assert not any(fragment in name.lower() for fragment in FORBIDDEN_FRAGMENTS), name


def test_run_accepts_the_request_type_and_returns_the_result_type() -> None:
    """The request type is the strict ``AiTaskRequest`` (it forbids unknown fields) and the result
    type is ``AiTaskResult``; no free-form dict or kwargs path exists."""
    hints = typing.get_type_hints(AiOrchestrator.run)
    assert hints["request"] is AiTaskRequest
    assert hints["return"] is AiTaskResult
