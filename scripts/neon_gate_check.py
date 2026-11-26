"""Read-only gate check for the Neon test branch.

Runs only with APP_ENV=test in Neon mode, goes through the shared guard (static rules, then the
live marker check) and prints one JSON object with the documented keys only. It never prints a URL,
host, user, password or key. Exit code 0 only when ``label_ok`` and ``marker_ok`` are both true.

Statements issued after the guard: ``SHOW server_version_num``, one query on ``pg_extension``,
one on ``pg_trigger`` and, with ``--counts``, ``SELECT count(*)`` on a fixed list of tables.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from collections.abc import Sequence
from typing import Any

from sqlalchemy import text
from sqlalchemy.pool import NullPool

from app.core import AppEnvironment, ConfigurationError, Settings, parse_database_target
from app.db_migrations.engine import build_async_engine
from app.db_migrations.guard import confirm_neon_test_database, validate_test_database_target

TRIGGER_NAME = "audit_log_immutable"
COUNT_TABLES = (
    "ai_requests",
    "ai_usage_records",
    "ai_budget_periods",
    "workspaces",
    "users",
    "outbox_events",
    "audit_log",
)
NOT_NEON_MESSAGE = "neon_gate_check runs only with APP_ENV=test in Neon mode"
ERROR_MESSAGE = "neon_gate_check failed"


# The test suite connects through ``settings.require_database_url(direct=True)`` (tests/conftest.py,
# tests/helpers/database_setup.py and the guard), i.e. the field behind DATABASE_URL_DIRECT. When
# only DATABASE_URL_UNPOOLED is set, Settings copies it into that field.
TEST_CONNECTION_VARIABLE = "DATABASE_URL_DIRECT"


def pooled_flags(settings: Settings) -> dict[str, bool]:
    """One boolean per configured URL variable, keyed ``pooled_<NAME>``. Names only, no hosts."""
    candidates = (
        ("DATABASE_URL", settings.database_url),
        ("DATABASE_URL_DIRECT", settings.database_url_direct),
        ("DATABASE_URL_UNPOOLED", settings.database_url_unpooled),
    )
    return {
        f"pooled_{name}": is_pooled_endpoint(value.get_secret_value())
        for name, value in candidates
        if value is not None
    }


def is_pooled_endpoint(url: str) -> bool:
    host = parse_database_target(url).host
    return host is not None and "-pooler" in host


async def collect(settings: Settings, connection: Any, *, counts: bool) -> dict[str, Any]:
    """Run the live check and the read-only queries on an open connection."""
    report: dict[str, Any] = {"mode": settings.test_db_mode, "label_ok": True}
    try:
        await confirm_neon_test_database(settings, connection)
    except ConfigurationError:
        report["marker_ok"] = False
        return report
    report["marker_ok"] = True
    report.update(pooled_flags(settings))
    report["test_connection_variable"] = TEST_CONNECTION_VARIABLE
    version = (await connection.execute(text("SHOW server_version_num"))).scalar()
    report["server_major_version"] = int(version) // 10000
    extensions = await connection.execute(text("SELECT extname FROM pg_extension ORDER BY extname"))
    report["extensions"] = [str(name) for name in extensions.scalars().all()]
    state = (
        await connection.execute(
            text(
                "SELECT tgenabled FROM pg_trigger "
                f"WHERE tgname = '{TRIGGER_NAME}' AND tgrelid = 'audit_log'::regclass"
            )
        )
    ).scalar()
    report["audit_trigger_enabled"] = state is not None and str(state) != "D"
    if counts:
        report["counts"] = {
            table: int((await connection.execute(text(f"SELECT count(*) FROM {table}"))).scalar())
            for table in COUNT_TABLES
        }
    return report


async def run(settings: Settings, *, counts: bool) -> dict[str, Any]:
    try:
        validate_test_database_target(settings)
    except ConfigurationError:
        return {"mode": settings.test_db_mode, "label_ok": False, "marker_ok": False}
    engine = build_async_engine(
        settings.require_database_url(direct=True),
        pooled=False,
        engine_options={"poolclass": NullPool},
    )
    try:
        async with engine.connect() as connection:
            return await collect(settings, connection, counts=counts)
    finally:
        await engine.dispose()


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--counts", action="store_true")
    args = parser.parse_args(argv)
    try:
        settings = Settings()
        if settings.test_db_mode != "neon" or settings.app_env != AppEnvironment.TEST:
            print(NOT_NEON_MESSAGE, file=sys.stderr)
            return 2
        report = asyncio.run(run(settings, counts=args.counts))
    except Exception as error:
        print(f"{type(error).__name__}: {ERROR_MESSAGE}", file=sys.stderr)
        return 3
    print(json.dumps(report, sort_keys=True))
    return 0 if report["label_ok"] and report["marker_ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
