from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any

from fastapi import Request
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from app.core import Settings
from app.db_migrations.engine import async_session_factory, runtime_engine


async def database_session(request: Request) -> AsyncIterator[AsyncSession]:
    state: Any = request.app.state
    factory: async_sessionmaker | None = getattr(state, "session_factory", None)
    if factory is None:
        settings: Settings = state.settings
        engine = runtime_engine(settings)
        factory = async_session_factory(engine)
        state.database_engine = engine
        state.session_factory = factory

    async with factory() as session:
        try:
            yield session
        except BaseException:
            await session.rollback()
            raise
        else:
            if session.in_transaction():
                await session.commit()


async def dispose_database(state: Any) -> None:
    engine: AsyncEngine | None = getattr(state, "database_engine", None)
    if engine is not None:
        await engine.dispose()