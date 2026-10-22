from __future__ import annotations

import json
from pathlib import Path

import httpx
import pytest
import structlog

from app.api_contract.app import create_app
from app.core import CursorPage, CursorParams, ProblemDetails
from app.core.config import Settings
from app.core.context import get_request_context
from app.core.errors import NotFound
from app.db_migrations import database_session


def test_openapi_generation_does_not_probe_infrastructure() -> None:
    def fail_if_called(_: Settings) -> None:
        raise AssertionError("OpenAPI generation must not probe dependencies")

    app = create_app(
        Settings(_env_file=None),
        database_check=fail_if_called,
        redis_check=fail_if_called,
    )

    schema = app.openapi()
    assert set(schema["paths"]) == {
        "/readyz",
        "/api/v1/auth/register",
        "/api/v1/auth/login",
        "/api/v1/auth/refresh",
        "/api/v1/auth/logout",
        "/api/v1/auth/logout-all",
        "/api/v1/auth/me",
        "/api/v1/workspaces",
        "/api/v1/workspaces/{workspace_id}",
        "/api/v1/workspaces/{workspace_id}/members",
        "/api/v1/workspaces/{workspace_id}/members/{user_id}",
        "/api/v1/workspaces/{workspace_id}/ownership-transfer",
        "/api/v1/workspaces/{workspace_id}/invitations",
        "/api/v1/workspaces/{workspace_id}/invitations/{invitation_id}",
        "/api/v1/invitations/{token}",
        "/api/v1/invitations/{token}/accept",
        "/api/v1/workspaces/{workspace_id}/profiles",
        "/api/v1/workspaces/{workspace_id}/profiles/{profile_id}",
        "/api/v1/workspaces/{workspace_id}/profiles/{profile_id}/archive",
        "/api/v1/workspaces/{workspace_id}/profiles/{profile_id}/restore",
        "/api/v1/workspaces/{workspace_id}/profiles/{profile_id}/business-context",
        "/api/v1/workspaces/{workspace_id}/profiles/{profile_id}/products",
        "/api/v1/workspaces/{workspace_id}/profiles/{profile_id}/products/{item_id}",
        "/api/v1/workspaces/{workspace_id}/profiles/{profile_id}/services",
        "/api/v1/workspaces/{workspace_id}/profiles/{profile_id}/services/{item_id}",
        "/api/v1/workspaces/{workspace_id}/profiles/{profile_id}/offers",
        "/api/v1/workspaces/{workspace_id}/profiles/{profile_id}/offers/{item_id}",
    }
    assert "503" in schema["paths"]["/readyz"]["get"]["responses"]
    assert "404" in schema["paths"]["/readyz"]["get"]["responses"]
    problem_content = schema["paths"]["/readyz"]["get"]["responses"]["404"]["content"]
    assert set(problem_content) == {"application/problem+json"}
    assert problem_content["application/problem+json"]["schema"]["$ref"] == (
        "#/components/schemas/ProblemDetails"
    )
    assert "ProblemDetails" in schema["components"]["schemas"]
    assert "CursorParams" in schema["components"]["schemas"]
    assert "CursorPage" in schema["components"]["schemas"]
    assert "request_id" in schema["components"]["schemas"]["ProblemDetails"]["properties"]
    assert "trace_id" in schema["components"]["schemas"]["ProblemDetails"]["properties"]
    assert "field_errors" in schema["components"]["schemas"]["ProblemDetails"]["properties"]
    assert "ProblemFieldError" in schema["components"]["schemas"]
    assert CursorParams(limit=10).limit == 10
    assert CursorPage[str](items=["item"]).next_cursor is None
    assert ProblemDetails.model_json_schema()["properties"]["code"]["type"] == "string"
    assert app.openapi() is schema
    profile_patch_responses = schema["paths"][
        "/api/v1/workspaces/{workspace_id}/profiles/{profile_id}"
    ]["patch"]["responses"]
    assert "409" in profile_patch_responses
    conflict_content = profile_patch_responses["409"]["content"]
    assert set(conflict_content) == {"application/problem+json"}
    conflict_schema = conflict_content["application/problem+json"]["schema"]
    assert conflict_schema["$ref"] == (
        "#/components/schemas/ProfileVersionConflictProblemDetails"
    )
    assert "current" in schema["components"]["schemas"][
        "ProfileVersionConflictProblemDetails"
    ]["properties"]
    assert "428" in profile_patch_responses
    assert profile_patch_responses["428"]["content"].keys() == {
        "application/problem+json"
    }
    assert "patch" in schema["paths"]["/api/v1/auth/me"]
    auth_properties = schema["components"]["schemas"]["AuthResponse"]["properties"]
    refresh_properties = schema["components"]["schemas"]["RefreshResponse"]["properties"]
    assert {"access_token", "expires_in"} <= auth_properties.keys()
    assert {"access_token", "expires_in"} <= refresh_properties.keys()
    assert auth_properties["expires_in"]["default"] == 900
    assert refresh_properties["expires_in"]["default"] == 900
    profile_list = schema["paths"]["/api/v1/workspaces/{workspace_id}/profiles"]["get"]
    profile_parameters = {parameter["name"]: parameter for parameter in profile_list["parameters"]}
    assert {"cursor", "limit", "archived", "profile_type"} <= profile_parameters.keys()
    assert profile_parameters["limit"]["schema"]["default"] == 20
    assert profile_parameters["archived"]["schema"]["default"] is False
    profile_patch = schema["paths"][
        "/api/v1/workspaces/{workspace_id}/profiles/{profile_id}"
    ]["patch"]
    profile_if_match = [
        parameter for parameter in profile_patch["parameters"] if parameter["name"] == "If-Match"
    ]
    assert len(profile_if_match) == 1 and profile_if_match[0]["required"]
    child_patch = schema["paths"][
        "/api/v1/workspaces/{workspace_id}/profiles/{profile_id}/products/{item_id}"
    ]["patch"]
    child_if_match = [
        parameter for parameter in child_patch["parameters"] if parameter["name"] == "If-Match"
    ]
    assert len(child_if_match) == 1 and child_if_match[0]["required"]
    profile_schema = schema["components"]["schemas"]["ProfileResponse"]
    assert "version" in profile_schema["properties"]
    for path_item in schema["paths"].values():
        for operation in path_item.values():
            if isinstance(operation, dict) and "responses" in operation:
                assert operation["responses"]["422"]["content"].keys() == {
                    "application/problem+json"
                }


def test_checked_in_openapi_matches_registered_routes() -> None:
    artifact = Path(__file__).parents[3] / "openapi.json"
    generated = create_app(Settings(_env_file=None)).openapi()

    assert json.loads(artifact.read_text(encoding="utf-8")) == generated


@pytest.mark.asyncio
async def test_readyz_reports_dependencies_independently_and_propagates_request_id() -> None:
    observed: dict[str, str | None] = {}

    async def database_ok(_: Settings) -> str:
        request_context = get_request_context(required=True)
        observed["request_id"] = request_context.request_id
        observed["traceparent"] = structlog.contextvars.get_contextvars().get("traceparent")
        return "ok"

    async def redis_missing(_: Settings) -> str:
        return "not_configured"

    app = create_app(
        Settings(_env_file=None),
        database_check=database_ok,
        redis_check=redis_missing,
    )
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://test",
    ) as client:
        response = await client.get(
            "/readyz",
            headers={"X-Request-ID": "request-42", "traceparent": "trace-42"},
        )

    assert response.status_code == 200
    assert response.headers["X-Request-ID"] == "request-42"
    assert observed == {"request_id": "request-42", "traceparent": "trace-42"}
    assert response.json() == {
        "status": "ready",
        "database": "ok",
        "redis": "not_configured",
    }


@pytest.mark.asyncio
async def test_domain_errors_use_problem_details() -> None:
    async def database_missing(_: Settings) -> str:
        raise NotFound("not found")

    async def redis_missing(_: Settings) -> str:
        return "not_configured"

    app = create_app(
        Settings(_env_file=None),
        database_check=database_missing,
        redis_check=redis_missing,
    )
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://test",
    ) as client:
        response = await client.get("/readyz")

    assert response.status_code == 404
    assert response.headers["content-type"].startswith("application/problem+json")


@pytest.mark.asyncio
async def test_request_validation_errors_use_problem_details() -> None:
    async def fake_session():
        yield object()

    app = create_app(Settings(_env_file=None))
    app.dependency_overrides[database_session] = fake_session
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.post(
            "/api/v1/auth/register",
            json={"email": "bad", "password": "short"},
            headers={
                "X-Request-ID": "request-validation-1",
                "traceparent": "00-0123456789abcdef0123456789abcdef-0123456789abcdef-01",
            },
        )

    assert response.status_code == 422
    assert response.headers["content-type"].startswith("application/problem+json")
    assert response.json()["code"] == "validation_failed"
    assert response.json()["instance"] == "/api/v1/auth/register"
    assert response.json()["request_id"] == "request-validation-1"
    assert response.json()["trace_id"] == "0123456789abcdef0123456789abcdef"
    field_errors = response.json()["field_errors"]
    assert {error["field"] for error in field_errors} >= {
        "email",
        "password",
        "display_name",
        "workspace_name",
    }
    assert all(set(error) == {"field", "code", "message"} for error in field_errors)
    assert '"input"' not in response.text
    assert '"bad"' not in response.text and '"short"' not in response.text


@pytest.mark.asyncio
async def test_unexpected_errors_are_redacted_problem_details() -> None:
    async def database_failure(_: Settings) -> str:
        raise RuntimeError("sensitive backend diagnostic")

    async def redis_missing(_: Settings) -> str:
        return "not_configured"

    app = create_app(
        Settings(_env_file=None),
        database_check=database_failure,
        redis_check=redis_missing,
    )
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app, raise_app_exceptions=False),
        base_url="http://test",
    ) as client:
        response = await client.get("/readyz")

    assert response.status_code == 500
    assert response.headers["content-type"].startswith("application/problem+json")
    assert response.json()["code"] == "internal_error"
    assert "sensitive backend diagnostic" not in response.text


@pytest.mark.asyncio
async def test_readiness_returns_503_when_database_is_unavailable() -> None:
    async def database_unavailable(_: Settings) -> str:
        return "unavailable"

    async def redis_unavailable(_: Settings) -> str:
        return "unavailable"

    app = create_app(
        Settings(_env_file=None),
        database_check=database_unavailable,
        redis_check=redis_unavailable,
    )
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://test",
    ) as client:
        response = await client.get("/readyz")

    assert response.status_code == 503
    assert response.json() == {
        "status": "not_ready",
        "database": "unavailable",
        "redis": "unavailable",
    }