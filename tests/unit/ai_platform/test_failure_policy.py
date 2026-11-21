"""Failure policy tests (spec 10.3, 11, 5.4; AC-16 table part, INV-9, D-32). Pure, no I/O."""

from __future__ import annotations

import ast
import inspect
from dataclasses import FrozenInstanceError
from itertools import product
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

from app.ai_platform import circuit_breaker as breaker_module
from app.ai_platform import failure_policy as policy_module
from app.ai_platform.config import AiPlatformConfig
from app.ai_platform.errors import (
    AiContentRefused,
    AiErrorCode,
    AiOutputInvalid,
    AiProviderNotConfigured,
    AiProviderUnavailable,
)
from app.ai_platform.failure_policy import (
    NEVER_FALL_BACK_CODES,
    ProviderFailureKind,
    classify,
    deadline_stop_error_code,
    final_error,
    max_total_calls,
    next_attempt_allowed,
    terminal_error_class,
)

K = ProviderFailureKind
C = AiErrorCode

# kind -> (error_code, falls_back, counts_toward_breaker, marks_unavailable, repairable,
#          terminal_on_first_failure, makes_provider_call_counted): the table in spec 10.3,
# written out independently of the implementation.
TABLE: dict[ProviderFailureKind, tuple[Any, ...]] = {
    K.TIMEOUT: (C.PROVIDER_TIMEOUT, True, True, False, False, False, True),
    K.CONNECTION_ERROR: (C.PROVIDER_UNAVAILABLE, True, True, False, False, False, True),
    K.HTTP_5XX: (C.PROVIDER_UNAVAILABLE, True, True, False, False, False, True),
    K.RATE_LIMITED: (C.PROVIDER_RATE_LIMITED, True, True, False, False, False, True),
    K.AUTH_FAILED: (C.PROVIDER_AUTH_FAILED, True, False, True, False, False, True),
    K.BAD_REQUEST: (C.PROVIDER_BAD_REQUEST, False, False, False, False, True, True),
    K.CONTENT_REFUSED: (C.CONTENT_REFUSED, False, False, False, False, True, True),
    K.TRUNCATED: (C.OUTPUT_TRUNCATED, True, False, False, False, False, True),
    K.INVALID_OUTPUT: (C.OUTPUT_INVALID, True, False, False, True, False, True),
    K.MISSING_CREDENTIALS: (C.PROVIDER_NOT_CONFIGURED, False, False, False, False, True, False),
}
TERMINAL: dict[ProviderFailureKind, type[Exception]] = {
    K.BAD_REQUEST: AiProviderUnavailable,
    K.CONTENT_REFUSED: AiContentRefused,
    K.MISSING_CREDENTIALS: AiProviderNotConfigured,
}


def test_table_has_a_row_for_every_kind() -> None:
    assert set(TABLE) == set(ProviderFailureKind)


@pytest.mark.parametrize("kind", list(ProviderFailureKind))
def test_classify_matches_the_spec_table(kind: ProviderFailureKind) -> None:
    result = classify(kind)
    assert (
        result.error_code,
        result.falls_back,
        result.counts_toward_breaker,
        result.marks_unavailable_for_process,
        result.repairable,
        result.terminal_on_first_failure,
        result.makes_provider_call_counted,
    ) == TABLE[kind]
    assert result.max_attempts_note is None or isinstance(result.max_attempts_note, str)


def test_failure_class_is_frozen() -> None:
    result = classify(K.TIMEOUT)
    with pytest.raises(FrozenInstanceError):
        result.falls_back = False  # type: ignore[misc]  # asserting the dataclass is frozen


def test_every_error_code_is_a_failure_code_or_never_falls_back() -> None:
    failure_codes = {classify(kind).error_code for kind in ProviderFailureKind}
    assert failure_codes | NEVER_FALL_BACK_CODES == set(AiErrorCode)
    assert failure_codes.isdisjoint(NEVER_FALL_BACK_CODES)
    assert {
        C.BUDGET_EXCEEDED,
        C.NO_ROUTE,
        C.INPUT_TOO_LARGE,
        C.LEASE_LOST,
        C.EXECUTION_ABANDONED,
    } == NEVER_FALL_BACK_CODES


def test_only_missing_credentials_makes_no_counted_call() -> None:
    uncounted = [k for k in ProviderFailureKind if not classify(k).makes_provider_call_counted]
    assert uncounted == [K.MISSING_CREDENTIALS]


def test_terminal_kinds_never_fall_back() -> None:
    for kind in ProviderFailureKind:
        result = classify(kind)
        assert result.terminal_on_first_failure != result.falls_back


@pytest.mark.parametrize("kind", list(TERMINAL))
def test_terminal_error_class(kind: ProviderFailureKind) -> None:
    assert terminal_error_class(kind) is TERMINAL[kind]


@pytest.mark.parametrize("kind", [k for k in ProviderFailureKind if k not in TERMINAL])
def test_terminal_error_class_rejects_non_terminal_kinds(kind: ProviderFailureKind) -> None:
    with pytest.raises(ValueError):
        terminal_error_class(kind)


def test_terminal_set_matches_the_table() -> None:
    terminal = {k for k in ProviderFailureKind if classify(k).terminal_on_first_failure}
    assert terminal == set(TERMINAL)


# --- final_error (D-32) ---


def test_all_invalid_gives_output_invalid() -> None:
    result = final_error([K.INVALID_OUTPUT, K.INVALID_OUTPUT, K.INVALID_OUTPUT])
    assert result.error_class is AiOutputInvalid
    assert result.error_code is C.OUTPUT_INVALID


def test_single_invalid_gives_output_invalid() -> None:
    assert final_error([K.INVALID_OUTPUT]).error_class is AiOutputInvalid


@pytest.mark.parametrize("order", [[K.INVALID_OUTPUT, K.TIMEOUT], [K.TIMEOUT, K.INVALID_OUTPUT]])
def test_mixed_failures_give_provider_unavailable_with_the_last_code(
    order: list[ProviderFailureKind],
) -> None:
    result = final_error(order)
    assert result.error_class is AiProviderUnavailable
    assert result.error_code is classify(order[-1]).error_code


def test_mixed_expected_codes_are_explicit() -> None:
    assert final_error([K.INVALID_OUTPUT, K.TIMEOUT]).error_code is C.PROVIDER_TIMEOUT
    assert final_error([K.TIMEOUT, K.INVALID_OUTPUT]).error_code is C.OUTPUT_INVALID


def test_all_timeouts() -> None:
    result = final_error([K.TIMEOUT, K.TIMEOUT])
    assert result.error_class is AiProviderUnavailable
    assert result.error_code is C.PROVIDER_TIMEOUT


def test_truncated_only() -> None:
    result = final_error([K.TRUNCATED])
    assert result.error_class is AiProviderUnavailable
    assert result.error_code is C.OUTPUT_TRUNCATED


def test_empty_failures_raise() -> None:
    with pytest.raises(ValueError):
        final_error([])


@pytest.mark.parametrize("pair", list(product(ProviderFailureKind, repeat=2)))
def test_final_error_pairs(pair: tuple[ProviderFailureKind, ProviderFailureKind]) -> None:
    result = final_error(pair)
    assert result.error_code is classify(pair[-1]).error_code
    both_invalid = pair == (K.INVALID_OUTPUT, K.INVALID_OUTPUT)
    assert result.error_class is (AiOutputInvalid if both_invalid else AiProviderUnavailable)


# --- attempts and deadline ---


def test_attempt_cap_boundaries() -> None:
    assert next_attempt_allowed(2, 3, 1_000, 100) is True
    assert next_attempt_allowed(3, 3, 1_000, 100) is False
    assert next_attempt_allowed(4, 3, 1_000, 100) is False
    assert next_attempt_allowed(0, 0, 1_000, 100) is False


def test_deadline_boundaries() -> None:
    assert next_attempt_allowed(0, 3, 99, 100) is False
    assert next_attempt_allowed(0, 3, 100, 100) is True
    assert next_attempt_allowed(0, 3, 101, 100) is True
    assert next_attempt_allowed(0, 3, 0, 0) is True


@pytest.mark.parametrize(
    "arguments",
    [(-1, 3, 10, 10), (0, -3, 10, 10), (0, 3, -10, 10), (0, 3, 10, -10), (0, 3, 10.5, 10)],
)
def test_next_attempt_allowed_rejects_invalid_inputs(arguments: tuple[Any, ...]) -> None:
    with pytest.raises(ValueError):
        next_attempt_allowed(*arguments)


def test_deadline_stop_code_is_provider_timeout() -> None:
    assert deadline_stop_error_code() is C.PROVIDER_TIMEOUT


def test_max_total_calls_default_config_is_six() -> None:
    config = AiPlatformConfig(_env_file=None)
    assert max_total_calls(config.max_provider_attempts, config.max_repair_attempts) == 6


@pytest.mark.parametrize(
    ("attempts", "repairs", "expected"), [(3, 1, 6), (2, 2, 6), (5, 3, 20), (1, 1, 2)]
)
def test_max_total_calls_follows_custom_values(attempts: int, repairs: int, expected: int) -> None:
    config = AiPlatformConfig(
        _env_file=None, max_provider_attempts=attempts, max_repair_attempts=repairs
    )
    assert max_total_calls(config.max_provider_attempts, config.max_repair_attempts) == expected


def test_max_total_calls_rejects_negative_values() -> None:
    with pytest.raises(ValueError):
        max_total_calls(-1, 1)
    with pytest.raises(ValueError):
        max_total_calls(3, -1)


# --- hygiene ---

POLICY_TREE = ast.parse(Path(inspect.getfile(policy_module)).read_text(encoding="utf-8"))
BREAKER_TREE = ast.parse(Path(inspect.getfile(breaker_module)).read_text(encoding="utf-8"))
FORBIDDEN_POLICY_ROOTS = {"time", "datetime", "random", "os", "sys"}


def _imported_modules(tree: ast.Module) -> set[str]:
    modules: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            modules.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            modules.add(node.module)
    return modules


def test_failure_policy_imports_no_clock_time_random_or_system_modules() -> None:
    imported = _imported_modules(POLICY_TREE)
    assert not {m for m in imported if m.split(".")[0] in FORBIDDEN_POLICY_ROOTS}
    assert "app.core.clock" not in imported


def test_circuit_breaker_imports_neither_time_nor_the_datetime_module() -> None:
    for node in ast.walk(BREAKER_TREE):
        if isinstance(node, ast.Import):
            assert all(alias.name.split(".")[0] not in {"time", "datetime"} for alias in node.names)
        if isinstance(node, ast.ImportFrom):
            assert node.module != "time"
            if node.module == "datetime":
                # Only the value types read from the injected Clock; no now() or today().
                assert {alias.name for alias in node.names} <= {"datetime", "timedelta"}


def test_failure_policy_has_no_module_level_mutable_state() -> None:
    mutable_nodes = (ast.List, ast.Dict, ast.Set, ast.ListComp, ast.DictComp, ast.SetComp)
    for node in POLICY_TREE.body:
        assert not isinstance(node, ast.Global)
        if isinstance(node, ast.Assign | ast.AnnAssign) and node.value is not None:
            assert not isinstance(node.value, mutable_nodes)
            if isinstance(node.value, ast.Call) and isinstance(node.value.func, ast.Name):
                assert node.value.func.id not in {"list", "dict", "set", "defaultdict", "deque"}


@pytest.mark.parametrize("module", [policy_module, breaker_module])
def test_no_public_name_contains_the_forbidden_word(module: ModuleType) -> None:
    forbidden = "tok" + "en"
    for name in dir(module):
        if name.startswith("_"):
            continue
        assert forbidden not in name.lower()
        member = getattr(module, name)
        if inspect.isclass(member) and member.__module__ == module.__name__:
            assert all(forbidden not in n.lower() for n in dir(member) if not n.startswith("_"))
