from __future__ import annotations

import asyncio
import json
from pathlib import Path

import httpx
from sqlalchemy import text

from app.api_contract import create_app
from app.core import AppEnvironment, CursorPage, CursorParams, ProblemDetails, Settings
from app.db_migrations import direct_engine


async def verify() -> None:
    settings = Settings()
    if settings.app_env != AppEnvironment.TEST or settings.neon_branch_name != "test":
        raise SystemExit(
            "Phase 0 live verification requires APP_ENV=test and NEON_BRANCH_NAME=test"
        )

    engine = direct_engine(settings)
    try:
        async with engine.connect() as connection:
            extension_rows = await connection.execute(
                text(
                    "SELECT extname, extversion FROM pg_extension "
                    "WHERE extname IN ('citext', 'pgcrypto', 'vector') ORDER BY extname"
                )
            )
            extensions = {name: version for name, version in extension_rows}
            assert set(extensions) == {"citext", "pgcrypto", "vector"}
            assert await connection.scalar(text("SELECT 'ABC'::citext = 'abc'::citext"))
            uuid_type = await connection.scalar(text("SELECT pg_typeof(gen_random_uuid())::text"))
            assert uuid_type == "uuid"
            vector_columns = await connection.scalar(
                text(
                    "SELECT count(*) FROM information_schema.columns "
                    "WHERE table_schema=current_schema() "
                    "AND udt_name IN ('vector', 'halfvec', 'sparsevec')"
                )
            )
            assert vector_columns == 0
            revision = await connection.scalar(text("SELECT version_num FROM alembic_version"))
    finally:
        await engine.dispose()

    app = create_app(settings)
    schema = app.openapi()
    for model in (ProblemDetails, CursorParams, CursorPage):
        assert model.__name__ in schema["components"]["schemas"]
    artifact = Path(__file__).resolve().parents[1] / "openapi.json"
    assert json.loads(artifact.read_text(encoding="utf-8")) == schema
    error_content = schema["paths"]["/readyz"]["get"]["responses"]["404"]["content"]
    assert set(error_content) == {"application/problem+json"}

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://verification",
    ) as client:
        response = await client.get("/readyz")
    assert response.status_code == 200, response.json()
    assert response.json()["database"] == "ok"
    assert response.json()["redis"] == "ok"
    print(
        json.dumps(
            {
                "branch": settings.neon_branch_name,
                "revision": revision,
                "extensions": extensions,
                "uuid_generation": "ok",
                "vector_columns": vector_columns,
                "core_openapi_schemas": "ok",
                "readiness": response.json(),
            },
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    asyncio.run(verify())