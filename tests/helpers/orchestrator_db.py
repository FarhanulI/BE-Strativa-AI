"""Builds an ``AiOrchestrator`` over the test database for the T-011 DB tests.

Synthetic catalog, fake provider, a placeholder key. The chat provider id is ``gemini`` because the
configuration can give a credential and a billing mode only for its two known provider ids; the
model name stays synthetic.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable
from typing import Any

from pydantic import BaseModel, ConfigDict

from app.ai_platform import (
    AiPlatformConfig,
    AiTaskRegistry,
    FakeAiProvider,
    OutputSchemaRegistry,
    ScriptedResponse,
)
from app.ai_platform.budget_coordinator import BudgetCoordinator
from app.ai_platform.catalog import ModelCatalog
from app.ai_platform.circuit_breaker import CircuitBreakerRegistry
from app.ai_platform.orchestrator import AiOrchestrator
from app.core import FakeClock
from tests.helpers.ai_request_db_env import AiDbEnv
from tests.helpers.char_estimator import CharCountEstimator
from tests.helpers.synthetic_catalog import catalog_dict, chat_entry

SYNTHETIC_KEY = "synthetic-test-key-not-real"  # a placeholder, never a real credential
CHAT_PROVIDER = "gemini"
VALID_OUTPUT_JSON = '{"value": "ok"}'


class OutputForTests(BaseModel):
    model_config = ConfigDict(extra="forbid")

    value: str = ""


def build_orchestrator(
    env: AiDbEnv,
    clock: FakeClock,
    *,
    entries: tuple[dict[str, Any], ...] | None = None,
    key: str | None = SYNTHETIC_KEY,
    budget_usd: str = "25",
    schemas_ready: bool = True,
    script: Iterable[ScriptedResponse] = (),
    coordinator_factory: Callable[..., BudgetCoordinator] = BudgetCoordinator,
    provider: FakeAiProvider | None = None,
) -> tuple[AiOrchestrator, FakeAiProvider]:
    values: dict[str, Any] = {"workspace_monthly_budget_usd": budget_usd}
    if key is not None:
        values["gemini_api_key"] = key
    config = AiPlatformConfig(_env_file=None, **values)
    catalog = ModelCatalog.from_dict(
        catalog_dict(*(entries or (chat_entry(provider=CHAT_PROVIDER),)))
    )
    schemas = OutputSchemaRegistry()
    for task in AiTaskRegistry().list() if schemas_ready else ():
        if task.output_schema_name is not None:
            schemas.register(task.output_schema_name, 1, OutputForTests)
    provider = provider if provider is not None else FakeAiProvider(script)
    orchestrator = AiOrchestrator(
        env.sessions,
        config,
        catalog,
        clock,
        CircuitBreakerRegistry(clock, config),
        coordinator_factory(env.sessions, clock, config),
        provider,
        CharCountEstimator(),
        schemas=schemas,
    )
    return orchestrator, provider
