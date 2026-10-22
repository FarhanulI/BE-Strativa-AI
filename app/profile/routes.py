from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import Depends, FastAPI, Header, Request, Response
from fastapi.responses import JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import (
    Conflict,
    CursorParams,
    ProblemDetails,
    ValidationFailed,
    problem_correlation_fields,
)
from app.db_migrations import database_session
from app.profile.schemas import (
    BusinessContextRequest,
    BusinessContextResponse,
    MaturityStage,
    ProfileCreateRequest,
    ProfileGoal,
    ProfileItemCreateRequest,
    ProfileItemPage,
    ProfileItemPatchRequest,
    ProfileItemResponse,
    ProfileItemType,
    ProfilePage,
    ProfilePatchRequest,
    ProfileResponse,
    ProfileSummary,
    ProfileType,
    ProfileVersionConflictProblemDetails,
)
from app.profile.service import (
    ProfileService,
    ProfileVersionConflict,
)
from app.workspace import (
    WorkspaceContext,
    WorkspacePermission,
    require_workspace_permission,
)

ReadProfile = Annotated[
    WorkspaceContext,
    Depends(require_workspace_permission(WorkspacePermission.PROFILE_READ)),
]
CreateProfile = Annotated[
    WorkspaceContext,
    Depends(require_workspace_permission(WorkspacePermission.PROFILE_CREATE)),
]
UpdateProfile = Annotated[
    WorkspaceContext,
    Depends(require_workspace_permission(WorkspacePermission.PROFILE_UPDATE)),
]
ArchiveProfile = Annotated[
    WorkspaceContext,
    Depends(require_workspace_permission(WorkspacePermission.PROFILE_ARCHIVE)),
]
IF_MATCH_REQUIRED_RESPONSE = {
    "description": "If-Match is required",
    "content": {
        "application/problem+json": {"schema": {"$ref": "#/components/schemas/ProblemDetails"}}
    },
}
IF_MATCH_OPENAPI_PARAMETER = {
    "parameters": [
        {
            "name": "If-Match",
            "in": "header",
            "required": True,
            "description": "Current profile version or ETag value",
            "schema": {"type": "string"},
        }
    ]
}
PROFILE_ETAG_RESPONSE = {
    "description": "Profile response with the current version ETag",
    "headers": {
        "ETag": {
            "description": "Quoted current profile version; send as If-Match on update",
            "schema": {"type": "string"},
        }
    },
}

VERSIONED_WRITE_RESPONSES = {
    409: {
        "model": ProfileVersionConflictProblemDetails,
        "description": "Parent profile version conflict; current state included",
    },
    428: IF_MATCH_REQUIRED_RESPONSE,
}


def register_routes(app: FastAPI) -> None:
    @app.get(
        "/api/v1/workspaces/{workspace_id}/profiles",
        response_model=ProfilePage,
        tags=["profile"],
    )
    async def list_profiles(
        context: ReadProfile,
        session: Annotated[AsyncSession, Depends(database_session)],
        page: Annotated[CursorParams, Depends()],
        profile_type: ProfileType | None = None,
        archived: bool = False,
    ) -> ProfilePage:
        profiles, next_cursor = await ProfileService.list(
            context,
            session,
            page,
            profile_type=profile_type.value if profile_type else None,
            archived=archived,
        )
        return ProfilePage(
            items=[_profile_summary(profile) for profile in profiles],
            next_cursor=next_cursor,
        )

    @app.post(
        "/api/v1/workspaces/{workspace_id}/profiles",
        response_model=ProfileResponse,
        status_code=201,
        responses={201: PROFILE_ETAG_RESPONSE},
        tags=["profile"],
    )
    async def create_profile(
        body: ProfileCreateRequest,
        context: CreateProfile,
        session: Annotated[AsyncSession, Depends(database_session)],
        response: Response,
    ) -> ProfileResponse:
        profile = await ProfileService.create(context, session, body)
        response.headers["ETag"] = _etag(profile.version)
        return _profile_response(profile)

    @app.get(
        "/api/v1/workspaces/{workspace_id}/profiles/{profile_id}",
        response_model=ProfileResponse,
        responses={200: PROFILE_ETAG_RESPONSE},
        tags=["profile"],
    )
    async def get_profile(
        profile_id: UUID,
        context: ReadProfile,
        session: Annotated[AsyncSession, Depends(database_session)],
        response: Response,
    ) -> ProfileResponse:
        profile = await ProfileService.get(context, session, profile_id)
        response.headers["ETag"] = _etag(profile.version)
        return _profile_response(profile)

    @app.patch(
        "/api/v1/workspaces/{workspace_id}/profiles/{profile_id}",
        response_model=ProfileResponse,
        responses={
            200: PROFILE_ETAG_RESPONSE,
            409: {
                "model": ProfileVersionConflictProblemDetails,
                "description": "Profile version conflict; current state included",
            },
            428: IF_MATCH_REQUIRED_RESPONSE,
        },
        openapi_extra=IF_MATCH_OPENAPI_PARAMETER,
        tags=["profile"],
    )
    async def update_profile(
        profile_id: UUID,
        body: ProfilePatchRequest,
        request: Request,
        context: UpdateProfile,
        session: Annotated[AsyncSession, Depends(database_session)],
        response: Response,
        if_match: Annotated[str | None, Header(alias="If-Match", include_in_schema=False)] = None,
    ) -> ProfileResponse | JSONResponse:
        if if_match is None:
            return _precondition_required_response(request)
        expected_version = _parse_if_match(if_match)
        try:
            profile = await ProfileService.update(
                context,
                session,
                profile_id,
                expected_version=expected_version,
                body=body,
            )
        except ProfileVersionConflict as error:
            return _profile_version_conflict_response(request, error)
        response.headers["ETag"] = _etag(profile.version)
        return _profile_response(profile)

    @app.post(
        "/api/v1/workspaces/{workspace_id}/profiles/{profile_id}/archive",
        response_model=ProfileResponse,
        responses={200: PROFILE_ETAG_RESPONSE, **VERSIONED_WRITE_RESPONSES},
        openapi_extra=IF_MATCH_OPENAPI_PARAMETER,
        tags=["profile"],
    )
    async def archive_profile(
        profile_id: UUID,
        request: Request,
        context: ArchiveProfile,
        session: Annotated[AsyncSession, Depends(database_session)],
        response: Response,
        if_match: Annotated[str | None, Header(alias="If-Match", include_in_schema=False)] = None,
    ) -> ProfileResponse | JSONResponse:
        if if_match is None:
            return _precondition_required_response(request)
        try:
            profile = await ProfileService.archive(
                context, session, profile_id, expected_version=_parse_if_match(if_match)
            )
        except ProfileVersionConflict as error:
            return _profile_version_conflict_response(request, error)
        response.headers["ETag"] = _etag(profile.version)
        return _profile_response(profile)

    @app.post(
        "/api/v1/workspaces/{workspace_id}/profiles/{profile_id}/restore",
        response_model=ProfileResponse,
        responses={200: PROFILE_ETAG_RESPONSE, **VERSIONED_WRITE_RESPONSES},
        openapi_extra=IF_MATCH_OPENAPI_PARAMETER,
        tags=["profile"],
    )
    async def restore_profile(
        profile_id: UUID,
        request: Request,
        context: ArchiveProfile,
        session: Annotated[AsyncSession, Depends(database_session)],
        response: Response,
        if_match: Annotated[str | None, Header(alias="If-Match", include_in_schema=False)] = None,
    ) -> ProfileResponse | JSONResponse:
        if if_match is None:
            return _precondition_required_response(request)
        try:
            profile = await ProfileService.restore(
                context, session, profile_id, expected_version=_parse_if_match(if_match)
            )
        except ProfileVersionConflict as error:
            return _profile_version_conflict_response(request, error)
        response.headers["ETag"] = _etag(profile.version)
        return _profile_response(profile)

    @app.get(
        "/api/v1/workspaces/{workspace_id}/profiles/{profile_id}/business-context",
        response_model=BusinessContextResponse | None,
        tags=["profile"],
    )
    async def get_business_context(
        profile_id: UUID,
        context: ReadProfile,
        session: Annotated[AsyncSession, Depends(database_session)],
    ) -> BusinessContextResponse | None:
        business_context = await ProfileService.get_business_context(context, session, profile_id)
        if business_context is None:
            return None
        return BusinessContextResponse(
            profile_id=business_context.profile_id,
            workspace_id=business_context.workspace_id,
            commercial_objectives=business_context.commercial_objectives,
            created_at=business_context.created_at,
            updated_at=business_context.updated_at,
        )

    @app.put(
        "/api/v1/workspaces/{workspace_id}/profiles/{profile_id}/business-context",
        response_model=BusinessContextResponse,
        responses={200: PROFILE_ETAG_RESPONSE, **VERSIONED_WRITE_RESPONSES},
        openapi_extra=IF_MATCH_OPENAPI_PARAMETER,
        tags=["profile"],
    )
    async def put_business_context(
        profile_id: UUID,
        body: BusinessContextRequest,
        request: Request,
        context: UpdateProfile,
        session: Annotated[AsyncSession, Depends(database_session)],
        response: Response,
        if_match: Annotated[str | None, Header(alias="If-Match", include_in_schema=False)] = None,
    ) -> BusinessContextResponse | JSONResponse:
        if if_match is None:
            return _precondition_required_response(request)
        expected_version = _parse_if_match(if_match)
        try:
            business_context = await ProfileService.put_business_context(
                context, session, profile_id, body, expected_version=expected_version
            )
        except ProfileVersionConflict as error:
            return _profile_version_conflict_response(request, error)
        response.headers["ETag"] = _etag(expected_version + 1)
        return BusinessContextResponse(
            profile_id=business_context.profile_id,
            workspace_id=business_context.workspace_id,
            commercial_objectives=business_context.commercial_objectives,
            created_at=business_context.created_at,
            updated_at=business_context.updated_at,
        )

    def register_item_routes(item_type: ProfileItemType) -> None:
        segment = item_type.value

        async def list_items(
            workspace_id: UUID,
            profile_id: UUID,
            context: ReadProfile,
            session: Annotated[AsyncSession, Depends(database_session)],
            page: Annotated[CursorParams, Depends()],
        ) -> ProfileItemPage:
            del workspace_id
            items, next_cursor = await ProfileService.list_items(
                context, session, profile_id, item_type, page
            )
            return ProfileItemPage(
                items=[_item_response(item) for item in items], next_cursor=next_cursor
            )

        async def create_item(
            workspace_id: UUID,
            profile_id: UUID,
            body: ProfileItemCreateRequest,
            request: Request,
            context: CreateProfile,
            session: Annotated[AsyncSession, Depends(database_session)],
            response: Response,
            if_match: Annotated[
                str | None, Header(alias="If-Match", include_in_schema=False)
            ] = None,
        ) -> ProfileItemResponse | JSONResponse:
            del workspace_id
            if if_match is None:
                return _precondition_required_response(request)
            expected_version = _parse_if_match(if_match)
            try:
                item = await ProfileService.create_item(
                    context,
                    session,
                    profile_id,
                    item_type,
                    body,
                    expected_version=expected_version,
                )
            except ProfileVersionConflict as error:
                return _profile_version_conflict_response(request, error)
            response.headers["ETag"] = _etag(expected_version + 1)
            return _item_response(item)

        async def update_item(
            workspace_id: UUID,
            profile_id: UUID,
            item_id: UUID,
            body: ProfileItemPatchRequest,
            request: Request,
            context: UpdateProfile,
            session: Annotated[AsyncSession, Depends(database_session)],
            response: Response,
            if_match: Annotated[
                str | None, Header(alias="If-Match", include_in_schema=False)
            ] = None,
        ) -> ProfileItemResponse | JSONResponse:
            del workspace_id
            if if_match is None:
                return _precondition_required_response(request)
            expected_version = _parse_if_match(if_match)
            try:
                item = await ProfileService.update_item(
                    context,
                    session,
                    profile_id,
                    item_id,
                    item_type,
                    expected_version=expected_version,
                    body=body,
                )
            except ProfileVersionConflict as error:
                return _profile_version_conflict_response(request, error)
            response.headers["ETag"] = _etag(expected_version + 1)
            return _item_response(item)

        async def archive_item(
            workspace_id: UUID,
            profile_id: UUID,
            item_id: UUID,
            request: Request,
            context: ArchiveProfile,
            session: Annotated[AsyncSession, Depends(database_session)],
            if_match: Annotated[
                str | None, Header(alias="If-Match", include_in_schema=False)
            ] = None,
        ) -> Response:
            del workspace_id
            if if_match is None:
                return _precondition_required_response(request)
            expected_version = _parse_if_match(if_match)
            try:
                await ProfileService.archive_item(
                    context,
                    session,
                    profile_id,
                    item_id,
                    item_type,
                    expected_version=expected_version,
                )
            except ProfileVersionConflict as error:
                return _profile_version_conflict_response(request, error)
            return Response(status_code=204, headers={"ETag": _etag(expected_version + 1)})

        root = f"/api/v1/workspaces/{{workspace_id}}/profiles/{{profile_id}}/{segment}"
        app.add_api_route(
            root,
            list_items,
            methods=["GET"],
            response_model=ProfileItemPage,
            name=f"list_profile_{segment}",
            tags=["profile"],
        )
        app.add_api_route(
            root,
            create_item,
            methods=["POST"],
            response_model=ProfileItemResponse,
            status_code=201,
            name=f"create_profile_{segment}",
            tags=["profile"],
            responses={201: PROFILE_ETAG_RESPONSE, **VERSIONED_WRITE_RESPONSES},
            openapi_extra=IF_MATCH_OPENAPI_PARAMETER,
        )
        app.add_api_route(
            f"{root}/{{item_id}}",
            update_item,
            methods=["PATCH"],
            response_model=ProfileItemResponse,
            name=f"update_profile_{segment}",
            responses={
                409: {
                    "model": ProfileVersionConflictProblemDetails,
                    "description": "Parent profile version conflict; current state included",
                },
                200: PROFILE_ETAG_RESPONSE,
                428: IF_MATCH_REQUIRED_RESPONSE,
            },
            openapi_extra=IF_MATCH_OPENAPI_PARAMETER,
            tags=["profile"],
        )
        app.add_api_route(
            f"{root}/{{item_id}}",
            archive_item,
            methods=["DELETE"],
            status_code=204,
            name=f"archive_profile_{segment}",
            tags=["profile"],
            responses=VERSIONED_WRITE_RESPONSES,
            openapi_extra=IF_MATCH_OPENAPI_PARAMETER,
        )

    for profile_item_type in ProfileItemType:
        register_item_routes(profile_item_type)


def _profile_summary(profile) -> ProfileSummary:
    return ProfileSummary(
        id=profile.id,
        workspace_id=profile.workspace_id,
        type=ProfileType(profile.type),
        name=profile.name,
        positioning=profile.positioning,
        topics=profile.topics,
        expertise=profile.expertise,
        goals=[ProfileGoal.model_validate(goal) for goal in profile.goals],
        maturity_stage=MaturityStage(profile.maturity_stage),
        verified_performance_count=profile.verified_performance_count,
        version=profile.version,
        created_at=profile.created_at,
        updated_at=profile.updated_at,
    )


def _profile_response(profile) -> ProfileResponse:
    return ProfileResponse(
        id=profile.id,
        workspace_id=profile.workspace_id,
        type=ProfileType(profile.type),
        name=profile.name,
        positioning=profile.positioning,
        topics=profile.topics,
        expertise=profile.expertise,
        goals=[ProfileGoal.model_validate(goal) for goal in profile.goals],
        maturity_stage=MaturityStage(profile.maturity_stage),
        verified_performance_count=profile.verified_performance_count,
        version=profile.version,
        archived_at=profile.archived_at,
        created_at=profile.created_at,
        updated_at=profile.updated_at,
    )


def _item_response(item) -> ProfileItemResponse:
    return ProfileItemResponse(
        id=item.id,
        workspace_id=item.workspace_id,
        profile_id=item.profile_id,
        name=item.name,
        description=item.description,
        metadata=item.item_metadata,
        archived_at=item.archived_at,
        created_at=item.created_at,
        updated_at=item.updated_at,
    )


def _parse_if_match(value: str) -> int:
    text_value = value.strip().strip('"')
    if not text_value.isdecimal() or int(text_value) < 1:
        raise ValidationFailed("If-Match must contain a positive profile version")
    return int(text_value)


def _etag(version: int) -> str:
    return f'"{version}"'


def _precondition_required_response(request: Request) -> JSONResponse:
    problem = ProblemDetails(
        title="Precondition Required",
        status=428,
        detail="If-Match is required",
        code="precondition_required",
        instance=request.scope.get("route").path,
        **problem_correlation_fields(
            request_id_header=request.headers.get("x-request-id"),
            traceparent=request.headers.get("traceparent"),
        ),
    )
    return JSONResponse(
        status_code=428,
        content=problem.model_dump(exclude_none=True),
        media_type="application/problem+json",
    )


def _profile_version_conflict_response(
    request: Request, error: ProfileVersionConflict
) -> JSONResponse:
    current = _profile_response(error.current_profile)
    problem = ProblemDetails(
        title=Conflict.title,
        status=409,
        detail=error.detail,
        code=Conflict.code,
        instance=request.scope.get("route").path,
        current=current.model_dump(mode="json"),
        **problem_correlation_fields(
            request_id_header=request.headers.get("x-request-id"),
            traceparent=request.headers.get("traceparent"),
        ),
    )
    return JSONResponse(
        status_code=409,
        content=problem.model_dump(exclude_none=True),
        media_type="application/problem+json",
    )
