from __future__ import annotations

import argparse
from pathlib import Path

from alembic import command
from alembic.config import Config

from app.core import Settings
from app.db_migrations import validate_migration_target

parser = argparse.ArgumentParser()
parser.add_argument("action", choices=("upgrade", "downgrade", "check"))
parser.add_argument("--allow-prod", action="store_true")
parser.add_argument("--require-test", action="store_true")
args = parser.parse_args()

settings = Settings()
if args.require_test and (
    settings.app_env.value != "test" or settings.neon_branch_name != "test"
):
    raise SystemExit("Test migrations require APP_ENV=test and NEON_BRANCH_NAME=test")
validate_migration_target(settings, allow_prod=args.allow_prod)
config = Config(Path(__file__).resolve().parents[1] / "alembic.ini")
config.set_main_option(
    "script_location",
    str(Path(__file__).resolve().parents[1] / "app" / "db_migrations" / "alembic"),
)
config.attributes["allow_prod"] = args.allow_prod

if args.action == "upgrade":
    command.upgrade(config, "head")
elif args.action == "downgrade":
    command.downgrade(config, "base")
else:
    command.check(config)