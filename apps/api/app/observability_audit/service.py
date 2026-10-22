from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from app.observability_audit.models import AuditLog, AuditRecord


async def append_audit(session: AsyncSession, record: AuditRecord) -> AuditLog:
    row = AuditLog(**record.model_dump())
    session.add(row)
    return row