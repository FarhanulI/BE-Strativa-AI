from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from uuid import UUID

import httpx


@dataclass(frozen=True)
class WorkspaceRouteCase:
    method: str
    path: str
    body: dict[str, Any] | None = None
    headers: dict[str, str] | None = None


WORKSPACE_SCOPED_ROUTES = (
    WorkspaceRouteCase("GET", "/api/v1/workspaces/{workspace_id}"),
    WorkspaceRouteCase("PATCH", "/api/v1/workspaces/{workspace_id}", {"name": "Renamed"}),
    WorkspaceRouteCase("DELETE", "/api/v1/workspaces/{workspace_id}"),
    WorkspaceRouteCase("GET", "/api/v1/workspaces/{workspace_id}/members"),
    WorkspaceRouteCase(
        "PATCH",
        "/api/v1/workspaces/{workspace_id}/members/{user_id}",
        {"role": "MEMBER"},
    ),
    WorkspaceRouteCase("DELETE", "/api/v1/workspaces/{workspace_id}/members/{user_id}"),
    WorkspaceRouteCase(
        "POST",
        "/api/v1/workspaces/{workspace_id}/ownership-transfer",
        {"new_owner_id": "0199f000-0000-7000-8000-000000000099"},
    ),
    WorkspaceRouteCase("GET", "/api/v1/workspaces/{workspace_id}/invitations"),
    WorkspaceRouteCase(
        "POST",
        "/api/v1/workspaces/{workspace_id}/invitations",
        {"email": "invite@example.test", "role": "MEMBER"},
    ),
    WorkspaceRouteCase(
        "DELETE",
        "/api/v1/workspaces/{workspace_id}/invitations/{invitation_id}",
    ),
)

PROFILE_SCOPED_ROUTES = (
    WorkspaceRouteCase("GET", "/api/v1/workspaces/{workspace_id}/profiles"),
    WorkspaceRouteCase(
        "POST",
        "/api/v1/workspaces/{workspace_id}/profiles",
        {"type": "creator", "name": "Nonmember profile"},
    ),
    WorkspaceRouteCase(
        "GET", "/api/v1/workspaces/{workspace_id}/profiles/{profile_id}"
    ),
    WorkspaceRouteCase(
        "PATCH",
        "/api/v1/workspaces/{workspace_id}/profiles/{profile_id}",
        {"name": "Crafted update"},
        {"If-Match": "1"},
    ),
    WorkspaceRouteCase(
        "POST", "/api/v1/workspaces/{workspace_id}/profiles/{profile_id}/archive"
    ),
    WorkspaceRouteCase(
        "POST", "/api/v1/workspaces/{workspace_id}/profiles/{profile_id}/restore"
    ),
    WorkspaceRouteCase(
        "GET",
        "/api/v1/workspaces/{workspace_id}/profiles/{profile_id}/business-context",
    ),
    WorkspaceRouteCase(
        "PUT",
        "/api/v1/workspaces/{workspace_id}/profiles/{profile_id}/business-context",
        {"commercial_objectives": []},
    ),
    WorkspaceRouteCase(
        "GET", "/api/v1/workspaces/{workspace_id}/profiles/{profile_id}/products"
    ),
    WorkspaceRouteCase(
        "POST",
        "/api/v1/workspaces/{workspace_id}/profiles/{profile_id}/products",
        {"name": "Product"},
    ),
    WorkspaceRouteCase(
        "PATCH",
        "/api/v1/workspaces/{workspace_id}/profiles/{profile_id}/products/{item_id}",
        {"name": "Updated product"},
    ),
    WorkspaceRouteCase(
        "DELETE",
        "/api/v1/workspaces/{workspace_id}/profiles/{profile_id}/products/{item_id}",
    ),
    WorkspaceRouteCase(
        "GET", "/api/v1/workspaces/{workspace_id}/profiles/{profile_id}/services"
    ),
    WorkspaceRouteCase(
        "POST",
        "/api/v1/workspaces/{workspace_id}/profiles/{profile_id}/services",
        {"name": "Service"},
    ),
    WorkspaceRouteCase(
        "PATCH",
        "/api/v1/workspaces/{workspace_id}/profiles/{profile_id}/services/{item_id}",
        {"name": "Updated service"},
    ),
    WorkspaceRouteCase(
        "DELETE",
        "/api/v1/workspaces/{workspace_id}/profiles/{profile_id}/services/{item_id}",
    ),
    WorkspaceRouteCase(
        "GET", "/api/v1/workspaces/{workspace_id}/profiles/{profile_id}/offers"
    ),
    WorkspaceRouteCase(
        "POST",
        "/api/v1/workspaces/{workspace_id}/profiles/{profile_id}/offers",
        {"name": "Offer"},
    ),
    WorkspaceRouteCase(
        "PATCH",
        "/api/v1/workspaces/{workspace_id}/profiles/{profile_id}/offers/{item_id}",
        {"name": "Updated offer"},
    ),
    WorkspaceRouteCase(
        "DELETE",
        "/api/v1/workspaces/{workspace_id}/profiles/{profile_id}/offers/{item_id}",
    ),
)


async def assert_nonmember_routes_hidden(
    client: httpx.AsyncClient,
    *,
    workspace_id: UUID,
    routes: tuple[WorkspaceRouteCase, ...] = WORKSPACE_SCOPED_ROUTES,
) -> None:
    for route in routes:
        path = route.path.format(
            workspace_id=workspace_id,
            user_id="0199f000-0000-7000-8000-000000000099",
            invitation_id="0199f000-0000-7000-8000-000000000098",
            profile_id="0199f000-0000-7000-8000-000000000097",
            item_id="0199f000-0000-7000-8000-000000000096",
        )
        response = await client.request(
            route.method, path, json=route.body, headers=route.headers
        )
        assert response.status_code == 404, (
            f"{route.method} {route.path} returned {response.status_code}, expected 404"
        )