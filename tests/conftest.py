from __future__ import annotations

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import ConfigurationError, Settings
from app.db_migrations.engine import build_async_engine
from tests.helpers.database_setup import prepare_test_schema


@pytest.fixture(scope="session")
def migrated_test_schema() -> Settings:
    try:
        settings = Settings()
        prepare_test_schema(settings)
    except ConfigurationError as error:
        pytest.fail(str(error))
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