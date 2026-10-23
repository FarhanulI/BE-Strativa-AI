from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from contextlib import asynccontextmanager
from typing import Any
from uuid import uuid4

import structlog
from fastapi import FastAPI, Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.openapi.utils import get_openapi
from fastapi.responses import JSONResponse
from pydantic.json_schema import models_json_schema

from app.api_contract.readiness import (
    DependencyStatus,
    ReadinessResponse,
)
from app.auth import register_routes as register_auth_routes
from app.core import (
    ConfigurationError,
    Conflict,
    CursorPage,
    CursorParams,
    DomainError,
    ExternalServiceError,
    Forbidden,
    NotFound,
    ProblemDetails,
    RateLimited,
    RequestContext,
    Settings,
    Unauthenticated,
    ValidationFailed,
    problem_correlation_fields,
    reset_request_context,
    set_request_context,
)
from app.db_migrations import dispose_database
from app.observability_audit import check_database, check_redis, configure_logging
from app.profile import register_routes as register_profile_routes
from app.workspace import register_routes as register_workspace_routes

DependencyCheck = Callable[[Settings], Awaitable[DependencyStatus]]
DOMAIN_ERROR_RESPONSES = {
    error.status_code: {
        "description": error.title,
        "content": {
            "application/problem+json": {
                "schema": {"$ref": "#/components/schemas/ProblemDetails"}
            }
        },
    }
    for error in (
        Unauthenticated,
        Forbidden,
        NotFound,
        Conflict,
        ValidationFailed,
        RateLimited,
        ExternalServiceError,
        DomainError,
    )
}


CONFIGURATION_ERROR_STATUS = 503
CONFIGURATION_ERROR_CODE = "service_unavailable"
CONFIGURATION_ERROR_TITLE = "Service Unavailable"
CONFIGURATION_ERROR_DETAIL = "A required service is temporarily unavailable"
CONFIGURATION_ERROR_RESPONSE = {
    "description": CONFIGURATION_ERROR_TITLE,
    "content": {
        "application/problem+json": {"schema": {"$ref": "#/components/schemas/ProblemDetails"}}
    },
}


def create_app(
    settings: Settings | None = None,
    *,
    database_check: DependencyCheck = check_database,
    redis_check: DependencyCheck = check_redis,
) -> FastAPI:
    app_settings = settings or Settings()
    configure_logging(level=app_settings.log_level)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        try:
            yield
        finally:
            await dispose_database(app.state)

    app = FastAPI(
        title="AI Content Studio API",
        version="0.1.0",
        docs_url=None,
        redoc_url=None,
        lifespan=lifespan,
    )
    app.state.settings = app_settings
    app.add_exception_handler(ConfigurationError, _configuration_error_handler)
    app.add_exception_handler(DomainError, _api_domain_error_handler)
    app.add_exception_handler(RequestValidationError, _request_validation_error_handler)
    app.add_exception_handler(Exception, _unhandled_error_handler)
    register_auth_routes(app)
    register_workspace_routes(app)
    register_profile_routes(app)

    @app.middleware("http")
    async def request_context_middleware(request: Request, call_next: Any) -> Response:
        request_id = request.headers.get("x-request-id") or str(uuid4())
        token = set_request_context(RequestContext(request_id=request_id, actor_type="user"))
        log_tokens = structlog.contextvars.bind_contextvars(
            request_id=request_id,
            traceparent=request.headers.get("traceparent"),
        )
        logger = structlog.get_logger().bind(request_id=request_id)
        try:
            response = await call_next(request)
        except Exception as error:
            _sanitize_access_log_path(request)
            logger.error(
                "request_failed",
                method=request.method,
                path=_route_template(request),
                error_type=type(error).__name__,
            )
            raise
        finally:
            reset_request_context(token)
            structlog.contextvars.reset_contextvars(**log_tokens)
        _sanitize_access_log_path(request)
        response.headers["X-Request-ID"] = request_id
        logger.info(
            "request_completed",
            method=request.method,
            path=_route_template(request),
            status_code=response.status_code,
        )
        return response

    @app.get(
        "/readyz",
        response_model=ReadinessResponse,
        responses={
            **DOMAIN_ERROR_RESPONSES,
            503: {
                "model": ReadinessResponse,
                "description": "Required database unavailable",
            },
        },
        tags=["system"],
    )
    async def readiness() -> JSONResponse:
        database_status, redis_status = await _check_dependencies(
            app_settings,
            database_check,
            redis_check,
        )
        ready = database_status == "ok"
        body = ReadinessResponse(
            status="ready" if ready else "not_ready",
            database=database_status,
            redis=redis_status,
        )
        return JSONResponse(
            status_code=200 if ready else 503,
            content=body.model_dump(mode="json"),
        )

    def openapi_with_shared_schemas() -> dict[str, Any]:
        if app.openapi_schema is None:
            schema = get_openapi(title=app.title, version=app.version, routes=app.routes)
            _, shared = models_json_schema(
                [
                    (ProblemDetails, "validation"),
                    (CursorParams, "validation"),
                    (CursorPage, "serialization"),
                ],
                ref_template="#/components/schemas/{model}",
            )
            schema.setdefault("components", {}).setdefault("schemas", {}).update(shared["$defs"])
            for path_item in schema.get("paths", {}).values():
                for operation in path_item.values():
                    if isinstance(operation, dict) and "responses" in operation:
                        for status_code, response in DOMAIN_ERROR_RESPONSES.items():
                            status_key = str(status_code)
                            existing = operation["responses"].get(status_key)
                            existing_content = (
                                existing.get("content", {}) if isinstance(existing, dict) else {}
                            )
                            json_content = existing_content.get("application/json", {})
                            response_schema = json_content.get("schema", {})
                            if (
                                status_code != 422
                                and response_schema.get("$ref")
                                and response_schema["$ref"]
                                != "#/components/schemas/ProblemDetails"
                            ):
                                existing_content["application/problem+json"] = (
                                    existing_content.pop("application/json")
                                )
                                continue
                            operation["responses"][status_key] = response
                        # Routes that declare their own 503 (e.g. /readyz) keep it.
                        operation["responses"].setdefault(
                            str(CONFIGURATION_ERROR_STATUS), CONFIGURATION_ERROR_RESPONSE
                        )
            app.openapi_schema = schema
        return app.openapi_schema

    app.openapi = openapi_with_shared_schemas
    return app


def _route_template(request: Request) -> str:
    route = request.scope.get("route")
    return getattr(route, "path", "unmatched")


def _sanitize_access_log_path(request: Request) -> None:
    route_path = _route_template(request)
    if "{token}" in route_path:
        request.scope["path"] = route_path
        request.scope["raw_path"] = route_path.encode("ascii")


async def _api_domain_error_handler(request: Request, error: DomainError) -> JSONResponse:
    problem = ProblemDetails(
        title=error.title,
        status=error.status_code,
        detail=error.detail,
        instance=_route_template(request),
        code=error.code,
        **problem_correlation_fields(
            request_id_header=request.headers.get("x-request-id"),
            traceparent=request.headers.get("traceparent"),
        ),
    )
    return JSONResponse(
        status_code=error.status_code,
        content=problem.model_dump(exclude_none=True),
        media_type="application/problem+json",
    )


async def _configuration_error_handler(
    request: Request, error: ConfigurationError
) -> JSONResponse:
    correlation_fields = problem_correlation_fields(
        request_id_header=request.headers.get("x-request-id"),
        traceparent=request.headers.get("traceparent"),
    )
    # ConfigurationError messages name settings, never their values.
    structlog.get_logger().error(
        "configuration_error",
        method=request.method,
        path=_route_template(request),
        reason=str(error),
        **correlation_fields,
    )
    problem = ProblemDetails(
        title=CONFIGURATION_ERROR_TITLE,
        status=CONFIGURATION_ERROR_STATUS,
        detail=CONFIGURATION_ERROR_DETAIL,
        instance=_route_template(request),
        code=CONFIGURATION_ERROR_CODE,
        **correlation_fields,
    )
    return JSONResponse(
        status_code=CONFIGURATION_ERROR_STATUS,
        content=problem.model_dump(exclude_none=True),
        media_type="application/problem+json",
    )


async def _request_validation_error_handler(
    request: Request, error: RequestValidationError
) -> JSONResponse:
    correlation_fields = problem_correlation_fields(
        request_id_header=request.headers.get("x-request-id"),
        traceparent=request.headers.get("traceparent"),
    )
    field_errors = []
    for error_item in error.errors():
        location = [
            part
            for part in error_item["loc"]
            if part not in {"body", "query", "path", "header"}
        ]
        field_errors.append(
            {
                "field": ".".join(str(part) for part in location) or "body",
                "code": str(error_item.get("type", "invalid")),
                "message": "Invalid value",
            }
        )
    problem = ProblemDetails(
        title=ValidationFailed.title,
        status=ValidationFailed.status_code,
        detail="Request validation failed",
        instance=_route_template(request),
        code=ValidationFailed.code,
        field_errors=field_errors,
        **correlation_fields,
    )
    return JSONResponse(
        status_code=ValidationFailed.status_code,
        content=problem.model_dump(exclude_none=True),
        media_type="application/problem+json",
    )


async def _unhandled_error_handler(request: Request, error: Exception) -> JSONResponse:
    del error
    problem = ProblemDetails(
        title=DomainError.title,
        status=DomainError.status_code,
        detail="An unexpected error occurred",
        instance=_route_template(request),
        code=DomainError.code,
        **problem_correlation_fields(
            request_id_header=request.headers.get("x-request-id"),
            traceparent=request.headers.get("traceparent"),
        ),
    )
    return JSONResponse(
        status_code=DomainError.status_code,
        content=problem.model_dump(exclude_none=True),
        media_type="application/problem+json",
    )


async def _check_dependencies(
    settings: Settings,
    database_check: DependencyCheck,
    redis_check: DependencyCheck,
) -> tuple[DependencyStatus, DependencyStatus]:
    database_status, redis_status = await asyncio.gather(
        database_check(settings),
        redis_check(settings),
    )
    return database_status, redis_status