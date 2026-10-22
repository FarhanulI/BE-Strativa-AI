from __future__ import annotations

from collections.abc import AsyncIterator
from contextvars import ContextVar, Token
from typing import Literal
from uuid import uuid4

from fastapi import Request
from pydantic import BaseModel, ConfigDict


class RequestContext(BaseModel):
    model_config = ConfigDict(frozen=True)

    request_id: str
    user_id: str | None = None
    workspace_id: str | None = None
    actor_type: Literal["user", "system", "worker"]


_request_context: ContextVar[RequestContext | None] = ContextVar("request_context", default=None)


def set_request_context(context: RequestContext) -> Token[RequestContext | None]:
    return _request_context.set(context)


def reset_request_context(token: Token[RequestContext | None]) -> None:
    _request_context.reset(token)


def get_request_context(*, required: bool = False) -> RequestContext | None:
    context = _request_context.get()
    if context is None and required:
        raise RuntimeError("Request context has not been established")
    return context


def problem_correlation_fields(
    *, request_id_header: str | None, traceparent: str | None
) -> dict[str, str]:
    context = get_request_context()
    request_id = context.request_id if context else request_id_header
    fields: dict[str, str] = {}
    if request_id:
        fields["request_id"] = request_id
    parts = (traceparent or "").split("-")
    if len(parts) == 4 and len(parts[1]) == 32:
        fields["trace_id"] = parts[1]
    return fields


async def request_context_dependency(request: Request) -> AsyncIterator[RequestContext]:
    existing = get_request_context()
    if existing is not None:
        yield existing
        return

    request_id = request.headers.get("x-request-id") or str(uuid4())
    context = RequestContext(request_id=request_id, actor_type="user")
    token = set_request_context(context)
    try:
        yield context
    finally:
        reset_request_context(token)