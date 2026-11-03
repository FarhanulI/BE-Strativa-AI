# Importing the models registers the ai_* tables on the shared metadata (alembic, tenant-scope
# validation). Nothing is exported: the ORM classes are not part of the public surface (spec 5.6).
from app.ai_platform import models as _models  # noqa: F401

__all__: list[str] = []
