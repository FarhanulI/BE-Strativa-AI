"""BudgetCoordinator logic that needs no database (ai_platform step 3b).

A fake session factory records transaction boundaries, and the repository statements are replaced
by recording stand-ins, so these tests check ordering (commit before raise, rollback on a failed
publish), scope-to-limit selection, argument validation and the use of the injected Clock.
"""

from __future__ import annotations

import inspect
from datetime import UTC, date, datetime
from types import SimpleNamespace
from typing import Any
from uuid import UUID, uuid4

import pytest

from app.ai_platform import budget_coordinator as coordinator_module
from app.ai_platform import budget_repository as repo
from app.ai_platform.budget_coordinator import (
    BudgetCoordinator,
    ReservationParams,
    SettlementOutcome,
)
from app.ai_platform.config import AiPlatformConfig
from app.ai_platform.errors import AiBudgetExceeded
from app.core import FakeClock

NOW = datetime(2031, 3, 9, 10, 0, tzinfo=UTC)
PERIOD = date(2031, 3, 1)
ROW_ID = uuid4()
WORKSPACE_ID = uuid4()


class _Begin:
    def __init__(self, log: list[str]) -> None:
        self._log = log

    async def __aenter__(self) -> None:
        self._log.append("begin")

    async def __aexit__(self, exc_type: object, exc: object, tb: object) -> bool:
        self._log.append("rollback" if exc_type else "commit")
        return False


class _FakeSession:
    def __init__(self, log: list[str]) -> None:
        self._log = log

    async def __aenter__(self) -> _FakeSession:
        return self

    async def __aexit__(self, exc_type: object, exc: object, tb: object) -> bool:
        self._log.append("close")
        return False

    def begin(self) -> _Begin:
        return _Begin(self._log)


class _Factory:
    def __init__(self, log: list[str]) -> None:
        self.log = log
        self.opened = 0

    def __call__(self) -> _FakeSession:
        self.opened += 1
        return _FakeSession(self.log)


def _snapshot(scope: str = "workspace", workspace_id: UUID | None = WORKSPACE_ID) -> Any:
    return repo.BudgetRowSnapshot(
        id=ROW_ID,
        scope=scope,
        workspace_id=workspace_id if scope == "workspace" else None,
        period_start=PERIOD,
        limit_micro_usd=1_000,
        reserved_micro_usd=50,
        spent_micro_usd=900,
        warning_notified_at=None,
        exhausted_notified_at=None,
        created_at=NOW,
        updated_at=NOW,
    )


def _params() -> ReservationParams:
    return ReservationParams(
        request_id=uuid4(),
        attempt_no=1,
        task="GENERATE_HOOK_VARIATIONS",
        call_kind="generation",
        provider="fakeprov",
        model="fake-chat",
        catalog_version="c1",
        price_version="p1",
        billing_mode="paid",
        routing_version="r1",
        route_rank=1,
        candidate_snapshot=[],
    )


def _outcome() -> SettlementOutcome:
    return SettlementOutcome(outcome="succeeded", input_units=1, output_units=2, cost_micro_usd=3)


class _Harness:
    def __init__(
        self, monkeypatch: pytest.MonkeyPatch, *, reserve: bool, refusal_new: bool
    ) -> None:
        self.log: list[str] = []
        self.factory = _Factory(self.log)
        self.times: list[datetime] = []
        self.published: list[Any] = []
        self.audits: list[Any] = []
        self.publish_error: Exception | None = None
        self.settle_result = repo.SettleResult(flipped=True, warning_newly_set=True)
        self.settle_error: Exception | None = None
        self.scope = "workspace"

        async def ensure(session: Any, scope: str, ws: Any, period: date, limit: int, now: Any):
            self.log.append("ensure")
            self.times.append(now)
            self.scope = scope
            return ROW_ID

        async def do_reserve(session: Any, row: Any, est: int, limit: int, now: Any) -> bool:
            self.log.append("reserve")
            self.times.append(now)
            return reserve

        async def insert(session: Any, record: Any) -> UUID:
            self.log.append("insert_usage")
            self.times.append(record.started_at)
            return uuid4()

        async def refusal(session: Any, row: Any, limit: int, now: Any) -> bool:
            self.log.append("record_refusal")
            return refusal_new

        async def get_row(session: Any, row: Any) -> Any:
            self.log.append("get_row")
            return _snapshot(self.scope)

        async def settle(session: Any, *args: Any) -> repo.SettleResult:
            self.log.append("settle")
            self.times.append(args[-1])
            if self.settle_error is not None:
                raise self.settle_error
            return self.settle_result

        async def audit(session: Any, record: Any) -> None:
            self.log.append("audit")
            self.audits.append(record)

        async def publish(session: Any, event: Any) -> Any:
            self.log.append("publish")
            if self.publish_error is not None:
                raise self.publish_error
            self.published.append(event)
            return SimpleNamespace(event_id=uuid4())

        monkeypatch.setattr(repo, "ensure_budget_row", ensure)
        monkeypatch.setattr(repo, "reserve", do_reserve)
        monkeypatch.setattr(repo, "insert_reserved_usage_record", insert)
        monkeypatch.setattr(repo, "record_refusal", refusal)
        monkeypatch.setattr(repo, "get_budget_row", get_row)
        monkeypatch.setattr(repo, "settle", settle)
        monkeypatch.setattr(coordinator_module, "append_audit", audit)
        self.publish = publish
        self.coordinator = BudgetCoordinator(
            self.factory,  # type: ignore[arg-type]
            FakeClock(NOW),
            AiPlatformConfig(
                workspace_monthly_budget_usd="7.5", system_monthly_budget_usd="40"
            ),
            publish,
        )


def test_limit_is_selected_by_scope(monkeypatch: pytest.MonkeyPatch) -> None:
    h = _Harness(monkeypatch, reserve=True, refusal_new=False)
    assert h.coordinator.limit_for_scope("workspace") == 7_500_000
    assert h.coordinator.limit_for_scope("system") == 40_000_000
    with pytest.raises(ValueError):
        h.coordinator.limit_for_scope("global")


@pytest.mark.parametrize(
    ("scope", "workspace_id", "estimate"),
    [
        ("global", None, 1),
        ("workspace", None, 1),
        ("system", WORKSPACE_ID, 1),
        ("workspace", WORKSPACE_ID, -1),
        ("workspace", WORKSPACE_ID, True),
        ("workspace", WORKSPACE_ID, 1.5),
    ],
)
async def test_invalid_arguments_fail_before_any_transaction(
    monkeypatch: pytest.MonkeyPatch, scope: Any, workspace_id: Any, estimate: Any
) -> None:
    h = _Harness(monkeypatch, reserve=True, refusal_new=False)
    with pytest.raises(ValueError):
        await h.coordinator.reserve_for_call(scope, workspace_id, estimate, _params())
    assert h.factory.opened == 0
    assert h.log == []


async def test_successful_reservation_is_one_committed_transaction(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    h = _Harness(monkeypatch, reserve=True, refusal_new=False)
    result = await h.coordinator.reserve_for_call("workspace", WORKSPACE_ID, 10, _params())
    assert h.log == ["begin", "ensure", "reserve", "insert_usage", "commit", "close"]
    assert result.budget_row_id == ROW_ID
    assert result.limit_micro_usd == 7_500_000
    assert h.published == [] and h.audits == []


async def test_first_refusal_commits_event_and_audit_before_raising(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    h = _Harness(monkeypatch, reserve=False, refusal_new=True)
    with pytest.raises(AiBudgetExceeded):
        await h.coordinator.reserve_for_call("workspace", WORKSPACE_ID, 10, _params())
    assert h.log == [
        "begin",
        "ensure",
        "reserve",
        "record_refusal",
        "get_row",
        "publish",
        "audit",
        "commit",
        "close",
    ]
    assert "insert_usage" not in h.log
    assert len(h.published) == 1 and len(h.audits) == 1
    event = h.published[0]
    assert event.event_type == "ai.budget_exhausted"
    assert event.aggregate_type == "ai_budget" and event.aggregate_id == ROW_ID
    assert event.workspace_id == WORKSPACE_ID
    assert event.occurred_at == NOW
    assert h.audits[0].action == "ai.budget.exhausted"
    assert h.audits[0].actor_type == "system"


async def test_later_refusal_publishes_nothing_but_still_commits_then_raises(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    h = _Harness(monkeypatch, reserve=False, refusal_new=False)
    with pytest.raises(AiBudgetExceeded):
        await h.coordinator.reserve_for_call("system", None, 10, _params())
    assert h.log == ["begin", "ensure", "reserve", "record_refusal", "commit", "close"]
    assert h.published == [] and h.audits == []


async def test_failed_publish_during_refusal_rolls_back_and_propagates(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    h = _Harness(monkeypatch, reserve=False, refusal_new=True)
    h.publish_error = RuntimeError("publish down")
    with pytest.raises(RuntimeError):
        await h.coordinator.reserve_for_call("workspace", WORKSPACE_ID, 10, _params())
    assert "rollback" in h.log and "commit" not in h.log


async def test_system_scope_event_has_no_workspace(monkeypatch: pytest.MonkeyPatch) -> None:
    h = _Harness(monkeypatch, reserve=False, refusal_new=True)
    with pytest.raises(AiBudgetExceeded):
        await h.coordinator.reserve_for_call("system", None, 10, _params())
    assert h.published[0].workspace_id is None
    assert h.published[0].scope == "system"
    assert h.audits[0].workspace_id is None


async def test_settlement_with_warning_publishes_in_the_same_transaction(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    h = _Harness(monkeypatch, reserve=True, refusal_new=False)
    result = await h.coordinator.settle_call(uuid4(), ROW_ID, 10, _outcome(), 1_000)
    assert result.warning_newly_set
    assert h.log == ["begin", "settle", "get_row", "publish", "audit", "commit", "close"]
    assert h.published[0].event_type == "ai.budget_threshold_reached"
    assert h.published[0].threshold_percent == 80
    assert h.audits[0].action == "ai.budget.threshold_reached"


async def test_settlement_without_warning_publishes_nothing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    h = _Harness(monkeypatch, reserve=True, refusal_new=False)
    h.settle_result = repo.SettleResult(flipped=True, warning_newly_set=False)
    await h.coordinator.settle_call(uuid4(), ROW_ID, 10, _outcome(), 1_000)
    assert h.log == ["begin", "settle", "commit", "close"]


async def test_failed_publish_rolls_the_settlement_back(monkeypatch: pytest.MonkeyPatch) -> None:
    h = _Harness(monkeypatch, reserve=True, refusal_new=False)
    h.publish_error = RuntimeError("publish down")
    with pytest.raises(RuntimeError):
        await h.coordinator.settle_call(uuid4(), ROW_ID, 10, _outcome(), 1_000)
    assert h.log[-2:] == ["rollback", "close"] and "commit" not in h.log
    assert h.audits == []


async def test_repository_error_rolls_back_and_propagates(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    h = _Harness(monkeypatch, reserve=True, refusal_new=False)
    h.settle_error = repo.BudgetRepositoryError("boom")
    with pytest.raises(repo.BudgetRepositoryError):
        await h.coordinator.settle_call(uuid4(), ROW_ID, 10, _outcome(), 1_000)
    assert "rollback" in h.log and "commit" not in h.log


@pytest.mark.parametrize(("estimate", "limit"), [(-1, 10), (True, 10), (1, -1), (1, 2.5)])
async def test_settle_validates_amounts_before_any_transaction(
    monkeypatch: pytest.MonkeyPatch, estimate: Any, limit: Any
) -> None:
    h = _Harness(monkeypatch, reserve=True, refusal_new=False)
    with pytest.raises(ValueError):
        await h.coordinator.settle_call(uuid4(), ROW_ID, estimate, _outcome(), limit)
    assert h.factory.opened == 0


async def test_time_comes_from_the_injected_clock(monkeypatch: pytest.MonkeyPatch) -> None:
    h = _Harness(monkeypatch, reserve=True, refusal_new=False)
    await h.coordinator.reserve_for_call("workspace", WORKSPACE_ID, 10, _params())
    await h.coordinator.settle_call(uuid4(), ROW_ID, 10, _outcome(), 1_000)
    assert h.times and set(h.times) == {NOW}


def test_module_never_reads_the_wall_clock() -> None:
    source = inspect.getsource(coordinator_module)
    for forbidden in ("datetime.now(", "datetime.utcnow(", "date.today(", "time.time("):
        assert forbidden not in source


def test_public_methods_take_no_free_text_parameters() -> None:
    """AC-52 (privacy, budget path): every parameter is an id, a scope, an int or a typed object."""
    allowed = {
        "scope": "repo.Scope",
        "workspace_id": "UUID | None",
        "estimate_micro_usd": "int",
        "usage_record_params": "ReservationParams",
        "usage_record_id": "UUID",
        "budget_row_id": "UUID",
        "outcome": "SettlementOutcome",
        "limit_micro_usd": "int",
    }
    for method in (BudgetCoordinator.reserve_for_call, BudgetCoordinator.settle_call):
        for name, parameter in inspect.signature(method).parameters.items():
            if name == "self":
                continue
            assert str(parameter.annotation) == allowed[name], name
    # The typed objects hold ids, codes and numbers only: no field is named like content.
    fields = set(ReservationParams.__dataclass_fields__) | set(
        SettlementOutcome.__dataclass_fields__
    )
    for name in fields:
        assert not any(
            word in name for word in ("prompt", "completion", "text", "content", "message", "token")
        ), name
