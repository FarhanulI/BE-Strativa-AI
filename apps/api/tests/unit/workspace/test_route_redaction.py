from __future__ import annotations

import httpx
import pytest

from app.api_contract import create_app
from app.core import NotFound, Settings
from app.db_migrations import database_session
from app.workspace import WorkspaceService


@pytest.mark.asyncio
async def test_invitation_token_is_not_echoed_in_problem_response(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level("INFO")
    token = "opaque-invitation-secret"

    async def missing_invitation(session, presented_token: str):
        assert presented_token == token
        raise NotFound("Invitation is unavailable")

    async def fake_session():
        yield object()

    monkeypatch.setattr(WorkspaceService, "preview_invitation", missing_invitation)
    app = create_app(Settings(_env_file=None))
    app.dependency_overrides[database_session] = fake_session
    observed_scope: dict[str, str | bytes] = {}

    async def capture_scope(scope, receive, send):
        await app(scope, receive, send)
        observed_scope["path"] = scope["path"]
        observed_scope["raw_path"] = scope["raw_path"]

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=capture_scope), base_url="http://test"
    ) as client:
        response = await client.get(f"/api/v1/invitations/{token}")

    assert response.status_code == 404
    assert response.json()["instance"] == "/api/v1/invitations/{token}"
    assert token not in response.text
    app_logs = [
        record.getMessage()
        for record in caplog.records
        if record.name == "app.api_contract.app"
    ]
    assert app_logs and all(token not in message for message in app_logs)
    assert observed_scope["path"] == "/api/v1/invitations/{token}"
    assert observed_scope["raw_path"] == b"/api/v1/invitations/{token}"