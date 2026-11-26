"""FakeAiProvider (spec 5.5; AC-8 api_key part). In-memory, no network."""

from __future__ import annotations

import asyncio

import pytest
from pydantic import SecretStr

from app.ai_platform import FakeAiProvider, ScriptedResponse
from app.ai_platform.failure_policy import ProviderFailureKind
from app.ai_platform.provider import (
    ChatMessage,
    ProviderCallError,
    ProviderGenerationRequest,
)


def _request(
    provider: str = "p", model: str = "m", text: str = "hello"
) -> ProviderGenerationRequest:
    return ProviderGenerationRequest(
        provider=provider,
        model=model,
        messages=(ChatMessage(role="system", content=text),),
        response_mode="json_mode",
        response_schema={"type": "object"},
        max_output_units=5,
        timeout_seconds=1.0,
    )


async def test_returns_scripted_responses_in_fifo_order() -> None:
    fake = FakeAiProvider(
        [
            ScriptedResponse.ok("a", input_units=1, output_units=2),
            ScriptedResponse.ok("b", finish_reason="length"),
        ]
    )
    first = await fake.generate(_request(), api_key=None)
    second = await fake.generate(_request(), api_key=None)
    assert (first.raw_text, first.input_units, first.output_units, first.finish_reason) == (
        "a",
        1,
        2,
        "stop",
    )
    assert (second.raw_text, second.finish_reason) == ("b", "length")


async def test_records_exact_requests_and_exact_api_key_objects_in_order() -> None:
    key = SecretStr("synthetic-key-value")
    fake = FakeAiProvider([ScriptedResponse.ok("x"), ScriptedResponse.ok("y")])
    first, second = _request(text="one"), _request(text="two")
    await fake.generate(first, api_key=key)
    await fake.generate(second, api_key=None)
    calls = fake.calls
    assert [c.request for c in calls] == [first, second]
    assert calls[0].request is first and calls[1].request is second
    assert calls[0].api_key is key
    assert calls[1].api_key is None


async def test_calls_property_is_a_read_only_snapshot() -> None:
    fake = FakeAiProvider([ScriptedResponse.ok("x")])
    await fake.generate(_request(), api_key=None)
    snapshot = fake.calls
    assert isinstance(snapshot, tuple)
    with pytest.raises(AttributeError):
        fake.calls = ()  # type: ignore[misc]  # read-only property: assignment must fail
    assert len(fake.calls) == len(snapshot) == 1


async def test_failures_raise_provider_call_error_with_reported_units() -> None:
    fake = FakeAiProvider(
        [
            ScriptedResponse.fail(ProviderFailureKind.RATE_LIMITED, input_units=4, output_units=0),
            ScriptedResponse.fail(ProviderFailureKind.TIMEOUT),
        ]
    )
    with pytest.raises(ProviderCallError) as first:
        await fake.generate(_request(), api_key=None)
    assert first.value.kind is ProviderFailureKind.RATE_LIMITED
    assert (first.value.input_units, first.value.output_units) == (4, 0)
    with pytest.raises(ProviderCallError) as second:
        await fake.generate(_request(), api_key=None)
    assert (second.value.input_units, second.value.output_units) == (None, None)
    assert len(fake.calls) == 2  # failed calls are recorded too


async def test_per_model_fifo_takes_precedence_over_the_global_script() -> None:
    fake = FakeAiProvider(
        [ScriptedResponse.ok("global")],
        per_model={("p", "special"): [ScriptedResponse.ok("s1"), ScriptedResponse.ok("s2")]},
    )
    assert (await fake.generate(_request(model="special"), api_key=None)).raw_text == "s1"
    assert (await fake.generate(_request(model="other"), api_key=None)).raw_text == "global"
    assert (await fake.generate(_request(model="special"), api_key=None)).raw_text == "s2"
    with pytest.raises(AssertionError):  # a per-model queue does not fall through to the global
        await fake.generate(_request(model="special"), api_key=None)


async def test_exhausted_script_raises_assertion_error_with_a_fixed_message() -> None:
    fake = FakeAiProvider([ScriptedResponse.ok("x")])
    await fake.generate(_request(), api_key=None)
    with pytest.raises(AssertionError) as error:
        await fake.generate(_request(text="DISTINCTIVE-CONTENT"), api_key=None)
    assert str(error.value) == "FakeAiProvider script is exhausted"
    with pytest.raises(AssertionError):
        await FakeAiProvider().generate(_request(), api_key=None)


async def test_responder_computes_a_response_from_the_request() -> None:
    fake = FakeAiProvider(
        responder=lambda request: ScriptedResponse.ok(
            f"echo:{request.model}", input_units=len(request.messages)
        )
    )
    response = await fake.generate(_request(model="zz"), api_key=None)
    assert (response.raw_text, response.input_units) == ("echo:zz", 1)
    assert len(fake.calls) == 1


async def test_per_model_queue_wins_over_the_responder() -> None:
    fake = FakeAiProvider(
        per_model={("p", "m"): [ScriptedResponse.ok("queued")]},
        responder=lambda request: ScriptedResponse.ok("dynamic"),
    )
    assert (await fake.generate(_request(), api_key=None)).raw_text == "queued"
    assert (await fake.generate(_request(model="n"), api_key=None)).raw_text == "dynamic"


def test_script_and_responder_together_are_rejected() -> None:
    with pytest.raises(ValueError):
        FakeAiProvider([ScriptedResponse.ok("x")], responder=lambda r: ScriptedResponse.ok("y"))


def test_negative_delay_is_rejected() -> None:
    with pytest.raises(ValueError):
        ScriptedResponse.ok("x", delay_seconds=-1)


async def test_delay_uses_asyncio_only() -> None:
    fake = FakeAiProvider([ScriptedResponse.ok("slow", delay_seconds=0.01)])
    with pytest.raises(TimeoutError):
        async with asyncio.timeout(0.001):
            await fake.generate(_request(), api_key=None)
    assert len(fake.calls) == 1  # recorded before the wait

    fake = FakeAiProvider([ScriptedResponse.ok("slow", delay_seconds=0.01)])
    assert (await asyncio.wait_for(fake.generate(_request(), api_key=None), 5)).raw_text == "slow"


async def test_concurrent_calls_each_consume_one_response() -> None:
    fake = FakeAiProvider([ScriptedResponse.ok(str(n), delay_seconds=0.001) for n in range(3)])
    results = await asyncio.gather(*(fake.generate(_request(), api_key=None) for _ in range(3)))
    assert sorted(r.raw_text for r in results) == ["0", "1", "2"]
    assert len(fake.calls) == 3


def test_scripted_response_helpers() -> None:
    ok = ScriptedResponse.ok("t", input_units=1, output_units=2)
    assert ok.failure_kind is None and ok.finish_reason == "stop"
    failed = ScriptedResponse.fail(ProviderFailureKind.AUTH_FAILED, input_units=9)
    assert failed.failure_kind is ProviderFailureKind.AUTH_FAILED and failed.input_units == 9
