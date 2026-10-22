from app.core import AppEnvironment, ConfigurationError, Settings


def validate_migration_target(settings: Settings, *, allow_prod: bool = False) -> str:
    expected_branch = {
        AppEnvironment.DEV: "dev",
        AppEnvironment.TEST: "test",
        AppEnvironment.PROD: "production",
    }.get(settings.app_env)
    if expected_branch is None or settings.neon_branch_name != expected_branch:
        raise ConfigurationError("NEON_BRANCH_NAME must match APP_ENV for migrations")
    if settings.app_env == AppEnvironment.PROD and not allow_prod:
        raise ConfigurationError("Production migrations require --allow-prod")
    return settings.require_database_url(direct=True)