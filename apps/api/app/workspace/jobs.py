from __future__ import annotations

from datetime import datetime

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.jobs_workers import JobEnvelope, JobRegistry
from app.workspace.service import WorkspaceService


def register_jobs(
    registry: JobRegistry, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    async def expire_invitations(job: JobEnvelope) -> None:
        raw_now = job.payload.get("now")
        current = datetime.fromisoformat(raw_now) if isinstance(raw_now, str) else None
        async with session_factory() as session:
            async with session.begin():
                await WorkspaceService.expire_invitations(session, now=current)

    registry.register("workspace.expire_invitations", 1, expire_invitations)