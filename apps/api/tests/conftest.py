from __future__ import annotations

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import AppEnvironment, Settings
from app.db_migrations.engine import build_async_engine


@pytest.fixture(scope="session")
def migrated_test_schema() -> Settings:
    settings = Settings()
    if settings.app_env != AppEnvironment.TEST or settings.neon_branch_name != "test":
        pytest.fail("DB tests require APP_ENV=test and NEON_BRANCH_NAME=test")
    settings.require_database_url(direct=True)
    config = Config("alembic.ini")
    command.upgrade(config, "head")
    command.check(config)
    return settings


@pytest.fixture
async def db_session(migrated_test_schema: Settings):
    engine = build_async_engine(
        migrated_test_schema.require_database_url(direct=True),
        pooled=False,
    )
    try:
        async with engine.connect() as connection:
            transaction = await connection.begin()
            session = AsyncSession(bind=connection, expire_on_commit=False)
            await session.begin_nested()
            try:
                yield session
            finally:
                await session.close()
                await transaction.rollback()
    finally:
        await engine.dispose()