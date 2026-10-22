from __future__ import annotations

from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import (
    Conflict,
    CursorParams,
    NotFound,
    SystemClock,
    UUID7Factory,
    ValidationFailed,
    get_request_context,
)
from app.events_outbox import EventEnvelope, handle_once, publish
from app.observability_audit import AuditRecord, append_audit
from app.profile.events import (
    BusinessContextUpdated,
    ProfileArchived,
    ProfileCreated,
    ProfileMaturityChanged,
    ProfileRestored,
    ProfileUpdated,
)
from app.profile.maturity import DEFAULT_THRESHOLDS, MaturityThresholds, compute_stage
from app.profile.models import (
    ContentProfile,
    ProfileBusinessContext,
    ProfileOffer,
    ProfileProduct,
    ProfileServiceItem,
)
from app.profile.schemas import (
    BusinessContextRequest,
    MaturityStage,
    ProfileCreateRequest,
    ProfileItemCreateRequest,
    ProfileItemPatchRequest,
    ProfileItemType,
    ProfileMaturityResponse,
    ProfilePatchRequest,
)
from app.workspace import WorkspaceContext

ProfileItemModel = type[ProfileProduct] | type[ProfileServiceItem] | type[ProfileOffer]
PROFILE_ITEM_MODELS: dict[ProfileItemType, ProfileItemModel] = {
    ProfileItemType.PRODUCT: ProfileProduct,
    ProfileItemType.SERVICE: ProfileServiceItem,
    ProfileItemType.OFFER: ProfileOffer,
}
_MATURITY_CONSUMER = "profile.verified_performance"


class ProfileVersionConflict(Conflict):
    def __init__(self, current_profile: ContentProfile) -> None:
        super().__init__("Profile version is stale")
        self.current_profile = current_profile


class ProfileService:
    @staticmethod
    async def create(
        ctx: WorkspaceContext,
        session: AsyncSession,
        body: ProfileCreateRequest,
    ) -> ContentProfile:
        profile = ContentProfile(
            id=UUID7Factory(SystemClock()).new(),
            workspace_id=ctx.workspace_id,
            type=body.type.value,
            name=body.name.strip(),
            positioning=body.positioning,
            topics=body.topics,
            expertise=body.expertise,
            goals=[goal.model_dump(mode="json") for goal in body.goals],
        )
        session.add(profile)
        await session.flush()
        await publish(
            session,
            ProfileCreated(
                aggregate_type="content_profile",
                aggregate_id=profile.id,
                workspace_id=ctx.workspace_id,
                profile_id=profile.id,
            ),
        )
        await _audit(
            session,
            ctx,
            action="profile.created",
            resource_id=profile.id,
            details={"type": profile.type},
        )
        return profile

    @staticmethod
    async def get(
        ctx: WorkspaceContext,
        session: AsyncSession,
        profile_id: UUID,
        *,
        include_archived: bool = False,
    ) -> ContentProfile:
        return await _get_profile(ctx, session, profile_id, include_archived=include_archived)

    @staticmethod
    async def list(
        ctx: WorkspaceContext,
        session: AsyncSession,
        params: CursorParams,
        *,
        profile_type: str | None = None,
        archived: bool = False,
    ) -> tuple[list[ContentProfile], str | None]:
        statement = select(ContentProfile).where(ContentProfile.workspace_id == ctx.workspace_id)
        if archived:
            statement = statement.where(ContentProfile.archived_at.is_not(None))
        else:
            statement = statement.where(ContentProfile.archived_at.is_(None))
        if profile_type is not None:
            statement = statement.where(ContentProfile.type == profile_type)
        if params.cursor:
            cursor_id = _parse_cursor(params.cursor)
            statement = statement.where(ContentProfile.id > cursor_id)
        statement = statement.order_by(ContentProfile.id).limit(params.limit + 1)
        profiles = list(await session.scalars(statement))
        has_more = len(profiles) > params.limit
        page = profiles[: params.limit]
        next_cursor = str(page[-1].id) if has_more and page else None
        return page, next_cursor

    @staticmethod
    async def update(
        ctx: WorkspaceContext,
        session: AsyncSession,
        profile_id: UUID,
        *,
        expected_version: int,
        body: ProfilePatchRequest,
    ) -> ContentProfile:
        profile = await _get_profile(ctx, session, profile_id, lock=True)
        if profile.version != expected_version:
            raise ProfileVersionConflict(profile)
        changes = body.model_dump(exclude_unset=True)
        if not changes:
            raise ValidationFailed("At least one profile field must be updated")
        for field, value in changes.items():
            if value is None:
                raise ValidationFailed(f"{field} cannot be null")
            if field == "goals":
                value = [goal.model_dump(mode="json") for goal in body.goals or []]
            if field == "name":
                value = value.strip()
            setattr(profile, field, value)
        profile.version += 1
        await session.flush()
        await publish(
            session,
            ProfileUpdated(
                aggregate_type="content_profile",
                aggregate_id=profile.id,
                workspace_id=ctx.workspace_id,
                profile_id=profile.id,
            ),
        )
        await _audit(
            session,
            ctx,
            action="profile.updated",
            resource_id=profile.id,
            details={"changed_fields": sorted(changes)},
        )
        return profile

    @staticmethod
    async def archive(
        ctx: WorkspaceContext,
        session: AsyncSession,
        profile_id: UUID,
        *,
        expected_version: int,
    ) -> ContentProfile:
        profile = await _get_profile(ctx, session, profile_id, lock=True)
        if profile.version != expected_version:
            raise ProfileVersionConflict(profile)
        profile.archived_at = SystemClock().now()
        profile.version += 1
        await session.flush()
        await publish(
            session,
            ProfileArchived(
                aggregate_type="content_profile",
                aggregate_id=profile.id,
                workspace_id=ctx.workspace_id,
                profile_id=profile.id,
            ),
        )
        await _audit(session, ctx, action="profile.archived", resource_id=profile.id)
        return profile

    @staticmethod
    async def restore(
        ctx: WorkspaceContext,
        session: AsyncSession,
        profile_id: UUID,
        *,
        expected_version: int,
    ) -> ContentProfile:
        profile = await _get_profile(ctx, session, profile_id, include_archived=True, lock=True)
        if profile.version != expected_version:
            raise ProfileVersionConflict(profile)
        if profile.archived_at is None:
            raise Conflict("Profile is not archived")
        profile.archived_at = None
        profile.version += 1
        await session.flush()
        await publish(
            session,
            ProfileRestored(
                aggregate_type="content_profile",
                aggregate_id=profile.id,
                workspace_id=ctx.workspace_id,
                profile_id=profile.id,
            ),
        )
        await _audit(session, ctx, action="profile.restored", resource_id=profile.id)
        return profile

    @staticmethod
    async def get_business_context(
        ctx: WorkspaceContext, session: AsyncSession, profile_id: UUID
    ) -> ProfileBusinessContext | None:
        await _get_profile(ctx, session, profile_id)
        return await session.scalar(
            select(ProfileBusinessContext).where(
                ProfileBusinessContext.workspace_id == ctx.workspace_id,
                ProfileBusinessContext.profile_id == profile_id,
            )
        )

    @staticmethod
    async def put_business_context(
        ctx: WorkspaceContext,
        session: AsyncSession,
        profile_id: UUID,
        body: BusinessContextRequest,
        *,
        expected_version: int,
    ) -> ProfileBusinessContext:
        profile = await _get_profile(ctx, session, profile_id, lock=True)
        if profile.version != expected_version:
            raise ProfileVersionConflict(profile)
        business_context = await session.scalar(
            select(ProfileBusinessContext)
            .where(
                ProfileBusinessContext.workspace_id == ctx.workspace_id,
                ProfileBusinessContext.profile_id == profile_id,
            )
            .with_for_update()
        )
        now = SystemClock().now()
        if business_context is None:
            business_context = ProfileBusinessContext(
                profile_id=profile.id,
                workspace_id=ctx.workspace_id,
                commercial_objectives=body.commercial_objectives,
            )
            session.add(business_context)
        else:
            business_context.commercial_objectives = body.commercial_objectives
            business_context.updated_at = now
        profile.version += 1
        await session.flush()
        await publish(
            session,
            BusinessContextUpdated(
                aggregate_type="content_profile",
                aggregate_id=profile.id,
                workspace_id=ctx.workspace_id,
                profile_id=profile.id,
            ),
        )
        await _audit(
            session, ctx, action="profile.business_context_updated", resource_id=profile.id
        )
        return business_context

    @staticmethod
    async def get_maturity(
        ctx: WorkspaceContext, session: AsyncSession, profile_id: UUID
    ) -> ProfileMaturityResponse:
        profile = await _get_profile(ctx, session, profile_id)
        return ProfileMaturityResponse(
            profile_id=profile.id,
            workspace_id=ctx.workspace_id,
            stage=MaturityStage(profile.maturity_stage),
            verified_performance_count=profile.verified_performance_count,
            version=profile.version,
        )

    @staticmethod
    async def record_verified_performance(
        ctx: WorkspaceContext,
        session: AsyncSession,
        profile_id: UUID,
        delta: int,
        idempotency_key: UUID,
        *,
        thresholds: MaturityThresholds = DEFAULT_THRESHOLDS,
    ) -> ProfileMaturityResponse:
        if delta <= 0:
            raise ValidationFailed("Verified performance delta must be positive")
        envelope = EventEnvelope(
            event_id=idempotency_key,
            event_type="profile.verified_performance_recorded",
            event_version=1,
            aggregate_type="content_profile",
            aggregate_id=profile_id,
            workspace_id=ctx.workspace_id,
            occurred_at=SystemClock().now(),
            payload={"profile_id": str(profile_id)},
        )

        async def apply_verified_performance(
            transaction: AsyncSession, event: EventEnvelope
        ) -> None:
            del event
            profile = await _get_profile(ctx, transaction, profile_id, lock=True)
            old_stage = MaturityStage(profile.maturity_stage)
            profile.verified_performance_count += delta
            new_stage = compute_stage(profile.verified_performance_count, thresholds)
            profile.version += 1
            profile.maturity_stage = new_stage.value
            await transaction.flush()
            if new_stage != old_stage:
                await publish(
                    transaction,
                    ProfileMaturityChanged(
                        aggregate_type="content_profile",
                        aggregate_id=profile.id,
                        workspace_id=ctx.workspace_id,
                        profile_id=profile.id,
                    ),
                )
            await _audit(
                transaction,
                ctx,
                action="profile.verified_performance_recorded",
                resource_id=profile.id,
                details={"delta": delta, "stage_changed": new_stage != old_stage},
            )

        await handle_once(
            session,
            consumer_name=_MATURITY_CONSUMER,
            event=envelope,
            handler=apply_verified_performance,
        )
        return await ProfileService.get_maturity(ctx, session, profile_id)

    @staticmethod
    async def list_items(
        ctx: WorkspaceContext,
        session: AsyncSession,
        profile_id: UUID,
        item_type: ProfileItemType,
        params: CursorParams,
    ) -> tuple[list[Any], str | None]:
        await _get_profile(ctx, session, profile_id)
        model = PROFILE_ITEM_MODELS[item_type]
        statement = select(model).where(
            model.workspace_id == ctx.workspace_id,
            model.profile_id == profile_id,
            model.archived_at.is_(None),
        )
        if params.cursor:
            statement = statement.where(model.id > _parse_cursor(params.cursor))
        items = list(await session.scalars(statement.order_by(model.id).limit(params.limit + 1)))
        has_more = len(items) > params.limit
        page = items[: params.limit]
        return page, str(page[-1].id) if has_more and page else None

    @staticmethod
    async def create_item(
        ctx: WorkspaceContext,
        session: AsyncSession,
        profile_id: UUID,
        item_type: ProfileItemType,
        body: ProfileItemCreateRequest,
        *,
        expected_version: int,
    ) -> Any:
        profile = await _get_profile(ctx, session, profile_id, lock=True)
        if profile.version != expected_version:
            raise ProfileVersionConflict(profile)
        model = PROFILE_ITEM_MODELS[item_type]
        item = model(
            id=UUID7Factory(SystemClock()).new(),
            workspace_id=ctx.workspace_id,
            profile_id=profile.id,
            name=body.name.strip(),
            description=body.description,
            item_metadata=body.metadata,
        )
        session.add(item)
        profile.version += 1
        await session.flush()
        await publish(
            session,
            ProfileUpdated(
                aggregate_type="content_profile",
                aggregate_id=profile.id,
                workspace_id=ctx.workspace_id,
                profile_id=profile.id,
            ),
        )
        await _audit(
            session,
            ctx,
            action=f"profile.{item_type.value}.created",
            resource_id=profile.id,
            details={"item_id": str(item.id)},
        )
        return item

    @staticmethod
    async def update_item(
        ctx: WorkspaceContext,
        session: AsyncSession,
        profile_id: UUID,
        item_id: UUID,
        item_type: ProfileItemType,
        *,
        expected_version: int,
        body: ProfileItemPatchRequest,
    ) -> Any:
        profile = await _get_profile(ctx, session, profile_id, lock=True)
        if profile.version != expected_version:
            raise ProfileVersionConflict(profile)
        item = await _get_item(ctx, session, profile_id, item_id, item_type)
        changes = body.model_dump(exclude_unset=True)
        if not changes:
            raise ValidationFailed("At least one item field must be updated")
        for field, value in changes.items():
            if value is None:
                raise ValidationFailed(f"{field} cannot be null")
            if field == "metadata":
                field = "item_metadata"
            if field == "name":
                value = value.strip()
            setattr(item, field, value)
        profile.version += 1
        await session.flush()
        await publish(
            session,
            ProfileUpdated(
                aggregate_type="content_profile",
                aggregate_id=profile.id,
                workspace_id=ctx.workspace_id,
                profile_id=profile.id,
            ),
        )
        await _audit(
            session,
            ctx,
            action=f"profile.{item_type.value}.updated",
            resource_id=profile.id,
            details={"item_id": str(item.id), "changed_fields": sorted(changes)},
        )
        return item

    @staticmethod
    async def archive_item(
        ctx: WorkspaceContext,
        session: AsyncSession,
        profile_id: UUID,
        item_id: UUID,
        item_type: ProfileItemType,
        *,
        expected_version: int,
    ) -> None:
        profile = await _get_profile(ctx, session, profile_id, lock=True)
        if profile.version != expected_version:
            raise ProfileVersionConflict(profile)
        item = await _get_item(ctx, session, profile_id, item_id, item_type)
        item.archived_at = SystemClock().now()
        profile.version += 1
        await session.flush()
        await publish(
            session,
            ProfileUpdated(
                aggregate_type="content_profile",
                aggregate_id=profile.id,
                workspace_id=ctx.workspace_id,
                profile_id=profile.id,
            ),
        )
        await _audit(
            session,
            ctx,
            action=f"profile.{item_type.value}.archived",
            resource_id=profile.id,
            details={"item_id": str(item.id)},
        )


async def _get_profile(
    ctx: WorkspaceContext,
    session: AsyncSession,
    profile_id: UUID,
    *,
    include_archived: bool = False,
    lock: bool = False,
) -> ContentProfile:
    statement = select(ContentProfile).where(
        ContentProfile.workspace_id == ctx.workspace_id,
        ContentProfile.id == profile_id,
    )
    if not include_archived:
        statement = statement.where(ContentProfile.archived_at.is_(None))
    if lock:
        statement = statement.with_for_update()
    profile = await session.scalar(statement)
    if profile is None:
        raise NotFound("Profile was not found")
    return profile


async def _get_item(
    ctx: WorkspaceContext,
    session: AsyncSession,
    profile_id: UUID,
    item_id: UUID,
    item_type: ProfileItemType,
) -> Any:
    model = PROFILE_ITEM_MODELS[item_type]
    item = await session.scalar(
        select(model).where(
            model.workspace_id == ctx.workspace_id,
            model.profile_id == profile_id,
            model.id == item_id,
            model.archived_at.is_(None),
        )
    )
    if item is None:
        raise NotFound("Profile item was not found")
    return item


async def _audit(
    session: AsyncSession,
    ctx: WorkspaceContext,
    *,
    action: str,
    resource_id: UUID,
    details: dict[str, object] | None = None,
) -> None:
    request_context = get_request_context()
    await append_audit(
        session,
        AuditRecord(
            actor_id=ctx.user_id,
            actor_type="user",
            action=action,
            resource_type="content_profile",
            resource_id=str(resource_id),
            workspace_id=ctx.workspace_id,
            request_id=request_context.request_id if request_context else "unknown",
            details=details or {},
        ),
    )


def _parse_cursor(cursor: str) -> UUID:
    try:
        return UUID(cursor)
    except ValueError as error:
        raise ValidationFailed("Cursor is invalid") from error
