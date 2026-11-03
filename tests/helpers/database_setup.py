from __future__ import annotations

from alembic import command
from alembic.config import Config

from app.core.config import Settings
from app.db_migrations import validate_test_database_target, verify_local_test_database


def prepare_test_schema(settings: Settings) -> None:
    """Guard first, then (in local mode) the live check, then migrate. Nothing runs earlier."""
    validate_test_database_target(settings)
    verify_local_test_database(settings)
    config = Config("alembic.ini")
    command.upgrade(config, "head")
    command.check(config)
