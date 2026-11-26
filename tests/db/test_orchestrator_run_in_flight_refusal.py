"""T-025 step 2: AC-35, the in-flight clause (local Postgres).

"The in-flight call at the moment of refusal still settles." While one ``run`` waits in its provider
call (its reservation is held), a second ``run`` against the same budget is refused. The first call
then settles normally. The HTTP 429 and ``GET /budget`` clauses of AC-35 need an endpoint that does
not exist and are not covered here. Synthetic text only.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from decimal import Decimal

import pytest
from pydantic import SecretStr
from sqlalchemy import text

from app.ai_platform import (
    AiBudgetExceeded,
    AiCallContext,
    AiTaskName,
    AiTaskRequest,
    FakeAiProvider,
    ScriptedResponse,
)
from app.ai_platform.messages import build_generation_messages
from app.ai_platform.provider import ProviderGenerationRequest, ProviderGenerationResponse
from app.core import Settings
from tests.helpers.ai_request_db_env import AiDbEnv, build_env
from tests.helpers.char_estimator import CharCountEstimator
from tests.helpers.orchestrator_db import CHAT_PROVIDER, VALID_OUTPUT_JSON, build_orchestrator
from tests.helpers.synthetic_catalog import chat_entry

pytestmark = pytest.mark.db

TASK = AiTaskName.GENERATE_HOOK_VARIATIONS
INSTRUCTIONS = "synthetic instructions"
IN_PRICE, OUT_PRICE = 150_000, 600_000  # micro-USD per million units, the synthetic chat entry
ENTRY = chat_entry(provider=CHAT_PROVIDER, model="synthetic-a")


@pytest.fixture
async def env(migrated_test_schema: Settings) -> AsyncIterator[AiDbEnv]:
    environment = build_env(migrated_test_schema)
    try:
        yield environment
    finally:
        try:
            async with environment.sessions() as session, session.begin():
                found = await session.execute(
                    text("SELECT id FROM ai_requests WHERE workspace_id = ANY(CAST(:w AS uuid[]))"),
                    {"w": environment.workspaces},
                )
                for (request_id,) in found.all():
                    if request_id not in environment.requests:
                        environment.requests.append(request_id)
            await environment.cleanup()
        finally:
            await environment.engine.dispose()


def _ceil_cost(units: int, price_per_million: int) -> int:
    return -(-(units * price_per_million) // 1_000_000)


def _estimate() -> int:
    """The Router estimate of the request below, computed here (as in the AC-59 tests)."""
    messages, _ = build_generation_messages(INSTRUCTIONS, [])
    units = CharCountEstimator().estimate_messages(messages)
    padded = -(-(units * 110) // 100)  # default context_safety_margin_percent is 10
    return _ceil_cost(padded, IN_PRICE) + _ceil_cost(1500, OUT_PRICE)


def _usd(micro: int) -> str:
    return f"{Decimal(micro) / Decimal(1_000_000):.6f}"


class _InFlightProbe(FakeAiProvider):
    """Runs one action while the first provider call is in flight, then answers normally."""

    def __init__(self, script: list[ScriptedResponse]) -> None:
        super().__init__(script)
        self.during: object = None
        self.captured: list[object] = []

    async def generate(
        self, request: ProviderGenerationRequest, *, api_key: SecretStr | None
    ) -> ProviderGenerationResponse:
        if not self.captured:
            self.captured.append(await self.during())  # type: ignore[operator]
        return await super().generate(request, api_key=api_key)


async def test_a_refusal_while_a_call_is_in_flight_leaves_that_call_to_settle(
    env: AiDbEnv,
) -> None:
    """AC-35, INV-15, D-8: the budget admits one call but not two. The second call is refused while
    the first is in flight; no provider call and no usage row for the second, one
    ``ai.budget_exhausted`` event with ``spent`` below the limit, and the first call still settles
    ``succeeded`` with its reservation released."""
    estimate = _estimate()
    limit = estimate + estimate // 2  # room for one reservation, not for two
    assert estimate <= limit < 2 * estimate
    clock = env.clock()
    workspace_id = await env.new_workspace()
    ctx = AiCallContext.for_worker(workspace_id=workspace_id, request_id="r")
    request = AiTaskRequest(task=TASK, instructions=INSTRUCTIONS)
    provider = _InFlightProbe(
        [ScriptedResponse.ok(VALID_OUTPUT_JSON, input_units=10, output_units=5)]
    )
    orchestrator, _ = build_orchestrator(
        env, clock, entries=(ENTRY,), budget_usd=_usd(limit), provider=provider
    )

    async def second_call_while_first_is_in_flight() -> tuple[str, int, int]:
        with pytest.raises(AiBudgetExceeded):
            await orchestrator.run(
                AiCallContext.for_worker(workspace_id=workspace_id, request_id="r2"), request
            )
        row_id = await env.find_budget_row(workspace_id, clock)
        assert row_id is not None
        held = await env.budget_row(row_id)
        return ("refused", held.reserved_micro_usd, held.spent_micro_usd)

    provider.during = second_call_while_first_is_in_flight
    await orchestrator.run(ctx, request)

    assert provider.captured == [("refused", estimate, 0)]  # first reservation held, nothing spent
    assert len(provider.calls) == 1  # no provider call for the refused request
    row_id = await env.find_budget_row(workspace_id, clock)
    assert row_id is not None
    budget = await env.budget_row(row_id)
    assert budget.reserved_micro_usd == 0 and 0 < budget.spent_micro_usd < limit
    async with env.sessions() as session, session.begin():
        rows = (
            await session.execute(
                text("SELECT status, error_code FROM ai_requests WHERE workspace_id = :w"),
                {"w": workspace_id},
            )
        ).all()
        usage = (
            await session.execute(
                text("SELECT status FROM ai_usage_records WHERE workspace_id = :w"),
                {"w": workspace_id},
            )
        ).all()
    assert sorted((r.status, r.error_code) for r in rows) == [
        ("failed", "budget_exceeded"),
        ("succeeded", None),
    ]
    assert [u.status for u in usage] == ["succeeded"]  # the refused call has no usage row
    (event,) = await env.events(row_id)
    assert event.event_type == "ai.budget_exhausted"
    assert event.payload["spent_micro_usd"] < event.payload["limit_micro_usd"]
    assert len(await env.audits(row_id)) == 1
