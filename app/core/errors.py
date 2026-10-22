from __future__ import annotations

from typing import Any

from fastapi import Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict


class ProblemFieldError(BaseModel):
    field: str
    code: str
    message: str


class ProblemDetails(BaseModel):
    model_config = ConfigDict(extra="allow")

    type: str = "about:blank"
    title: str
    status: int
    detail: str
    instance: str | None = None
    code: str
    request_id: str | None = None
    trace_id: str | None = None
    field_errors: list[ProblemFieldError] | None = None


class DomainError(Exception):
    status_code = 500
    code = "internal_error"
    title = "Internal Server Error"

    def __init__(self, detail: str) -> None:
        super().__init__(detail)
        self.detail = detail


class NotFound(DomainError):
    status_code = 404
    code = "not_found"
    title = "Not Found"


class Conflict(DomainError):
    status_code = 409
    code = "conflict"
    title = "Conflict"


class ValidationFailed(DomainError):
    status_code = 422
    code = "validation_failed"
    title = "Validation Failed"


class Forbidden(DomainError):
    status_code = 403
    code = "forbidden"
    title = "Forbidden"


class Unauthenticated(DomainError):
    status_code = 401
    code = "unauthenticated"
    title = "Unauthenticated"


class RateLimited(DomainError):
    status_code = 429
    code = "rate_limited"
    title = "Too Many Requests"


class ExternalServiceError(DomainError):
    status_code = 502
    code = "external_service_error"
    title = "External Service Error"


async def domain_error_handler(request: Request, exc: DomainError) -> JSONResponse:
    from app.core.context import get_request_context

    context = get_request_context()
    problem = ProblemDetails(
        title=exc.title,
        status=exc.status_code,
        detail=exc.detail,
        instance=request.url.path,
        code=exc.code,
        request_id=context.request_id if context else request.headers.get("x-request-id"),
    )
    return JSONResponse(
        status_code=exc.status_code,
        content=problem.model_dump(exclude_none=True),
        media_type="application/problem+json",
    )


def problem_details_for(
    *, title: str, status: int, detail: str, code: str, instance: str | None = None,
    extensions: dict[str, Any] | None = None,
) -> ProblemDetails:
    return ProblemDetails(
        title=title,
        status=status,
        detail=detail,
        code=code,
        instance=instance,
        **(extensions or {}),
    )