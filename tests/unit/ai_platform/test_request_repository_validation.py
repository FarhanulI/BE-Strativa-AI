"""Input validation of the request repository: every rejection happens before any statement runs."""

from __future__ import annotations

import inspect
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

import pytest

import app.ai_platform.request_repository as repo
from app.ai_platform import AiErrorCode, AiTaskName

NOW = datetime(2026, 5, 1, 12, 0, tzinfo=UTC)
NAIVE = datetime(2026, 5, 1, 12, 0)


class _NoStatementSession:
    """Fails the test if the repository touches the database."""

    async def execute(self, *args: Any, **kwargs: Any) -> Any:
        raise AssertionError("a statement ran before validation finished")


def _insert_args(**overrides: Any) -> dict[str, Any]:
    args: dict[str, Any] = {
        "scope": "workspace",
        "workspace_id": uuid4(),
        "requested_by_user_id": uuid4(),
        "actor_type": "user",
        "task": AiTaskName.GENERATE_HOOK_VARIATIONS.value,
        "output_schema_name": "HookVariationSet",
        "output_schema_version": 1,
        "correlation_request_id": "req-1",
        "now": NOW,
    }
    args.update(overrides)
    return args


async def _insert(**overrides: Any) -> Any:
    return await repo.insert_sync_request(_NoStatementSession(), **_insert_args(**overrides))  # type: ignore[arg-type]


async def _complete(**overrides: Any) -> Any:
    args: dict[str, Any] = {"status": "succeeded", "error_code": None, "now": NOW}
    args.update(overrides)
    request_id = args.pop("request_id", uuid4())
    return await repo.complete_request(_NoStatementSession(), request_id, **args)  # type: ignore[arg-type]


# --- insert_sync_request ---


@pytest.mark.parametrize(
    "overrides",
    [
        {"scope": "tenant"},
        {"scope": ""},
        {"scope": "workspace", "workspace_id": None},
        {"scope": "workspace", "workspace_id": "not-a-uuid"},
        {"scope": "system", "workspace_id": uuid4()},
    ],
)
async def test_insert_rejects_a_bad_scope_workspace_combination(overrides: dict[str, Any]) -> None:
    with pytest.raises(ValueError):
        await _insert(**overrides)


@pytest.mark.parametrize("actor", ["", "admin", "USER", None])
async def test_insert_rejects_a_bad_actor_type(actor: Any) -> None:
    with pytest.raises(ValueError):
        await _insert(actor_type=actor)


@pytest.mark.parametrize("task", ["", "NOT_A_TASK", "generate_hook_variations", None])
async def test_insert_rejects_an_unknown_task(task: Any) -> None:
    with pytest.raises(ValueError):
        await _insert(task=task)


@pytest.mark.parametrize(
    "overrides",
    [
        {"output_schema_name": None},
        {"output_schema_version": None},
        {"output_schema_name": None, "output_schema_version": None},
        {"output_schema_name": ""},
        {"output_schema_version": 0},
        {"output_schema_version": True},
        {"output_schema_version": 1.0},
        {"output_schema_version": "1"},
    ],
)
async def test_insert_requires_a_schema_for_every_task_but_embed_text(
    overrides: dict[str, Any],
) -> None:
    with pytest.raises(ValueError):
        await _insert(**overrides)


@pytest.mark.parametrize(
    "overrides",
    [
        {"output_schema_name": "X", "output_schema_version": None},
        {"output_schema_name": None, "output_schema_version": 1},
        {"output_schema_name": "X", "output_schema_version": 1},
    ],
)
async def test_insert_embed_text_must_have_no_schema(overrides: dict[str, Any]) -> None:
    with pytest.raises(ValueError):
        await _insert(task="EMBED_TEXT", scope="system", workspace_id=None, **overrides)


@pytest.mark.parametrize("bad", ["", None, 5])
async def test_insert_rejects_a_bad_correlation_id(bad: Any) -> None:
    with pytest.raises(ValueError):
        await _insert(correlation_request_id=bad)


async def test_insert_rejects_a_naive_time_and_a_bad_user_id() -> None:
    with pytest.raises(ValueError):
        await _insert(now=NAIVE)
    with pytest.raises(ValueError):
        await _insert(now="2026-05-01")
    with pytest.raises(ValueError):
        await _insert(requested_by_user_id="user")


# --- complete_request ---


@pytest.mark.parametrize("status", ["running", "queued", "abandoned", "", None, True])
async def test_complete_rejects_any_status_but_succeeded_or_failed(status: Any) -> None:
    with pytest.raises(ValueError):
        await _complete(status=status, error_code="output_invalid")


@pytest.mark.parametrize("error_code", ["output_invalid", "anything", ""])
async def test_succeeded_must_have_no_error_code(error_code: str) -> None:
    with pytest.raises(ValueError):
        await _complete(status="succeeded", error_code=error_code)


@pytest.mark.parametrize("error_code", [None, "", "not_a_code", "BUDGET_EXCEEDED", 7])
async def test_failed_needs_a_valid_error_code(error_code: Any) -> None:
    with pytest.raises(ValueError):
        await _complete(status="failed", error_code=error_code)


async def test_output_payload_only_for_succeeded() -> None:
    with pytest.raises(ValueError):
        await _complete(status="failed", error_code="output_invalid", output_payload={"a": 1})


@pytest.mark.parametrize("payload", [[1], "text", 5, {"a": object()}, {"a": float("nan")}])
async def test_output_payload_must_be_a_json_serialisable_dict(payload: Any) -> None:
    with pytest.raises(ValueError):
        await _complete(output_payload=payload)


async def test_complete_rejects_a_bad_id_time_and_routing_version() -> None:
    with pytest.raises(ValueError):
        await _complete(request_id="not-a-uuid")
    with pytest.raises(ValueError):
        await _complete(now=NAIVE)
    with pytest.raises(ValueError):
        await _complete(routing_version="")
    with pytest.raises(ValueError):
        await _complete(routing_version=5)


async def test_get_request_snapshot_rejects_a_bad_id() -> None:
    with pytest.raises(ValueError):
        await repo.get_request_snapshot(_NoStatementSession(), "x")  # type: ignore[arg-type]


def test_every_error_code_is_accepted_for_a_failed_request() -> None:
    assert {code.value for code in AiErrorCode} == set(repo._ERROR_CODES)


# --- shape ---


def test_module_never_commits_or_reads_a_clock() -> None:
    source = inspect.getsource(repo)
    for forbidden in (".commit(", ".rollback(", ".begin(", "datetime.now", "utcnow", "time.time"):
        assert forbidden not in source


def test_statements_use_bound_parameters_only() -> None:
    for statement in (repo._INSERT_SYNC, repo._COMPLETE, repo._SELECT_SNAPSHOT):
        assert "%s" not in statement and "{" not in statement
