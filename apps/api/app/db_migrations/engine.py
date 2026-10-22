from __future__ import annotations

from collections.abc import Mapping
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from sqlalchemy.engine import URL
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker, create_async_engine

from app.core import Settings


def normalize_postgres_url(url: str) -> tuple[str, bool]:
    parsed = urlsplit(url)
    if parsed.scheme not in ("postgres", "postgresql", "postgresql+asyncpg"):
        raise ValueError("Database URL must use a PostgreSQL scheme")

    tls_requested = False
    retained: list[tuple[str, str]] = []
    for key, value in parse_qsl(parsed.query, keep_blank_values=True):
        lowered = value.lower()
        if key == "sslmode":
            tls_requested = lowered not in ("", "disable", "allow", "prefer")
        elif key == "channel_binding":
            tls_requested = tls_requested or lowered not in ("", "disable")
        else:
            retained.append((key, value))

    scheme = "postgresql+asyncpg" if parsed.scheme in ("postgres", "postgresql") else parsed.scheme
    normalized = urlunsplit(
        (scheme, parsed.netloc, parsed.path, urlencode(retained), parsed.fragment)
    )
    return normalized, tls_requested


def build_async_engine(
    url: str | URL,
    *,
    pooled: bool,
    engine_options: Mapping[str, object] | None = None,
) -> AsyncEngine:
    url_text = url.render_as_string(hide_password=False) if isinstance(url, URL) else url
    normalized_url, tls_requested = normalize_postgres_url(url_text)
    connect_args: dict[str, object] = {"timeout": 30}
    if tls_requested:
        connect_args["ssl"] = "require"
    options: dict[str, object] = {"pool_pre_ping": True, "connect_args": connect_args}
    if pooled:
        connect_args["statement_cache_size"] = 0
        connect_args["prepared_statement_cache_size"] = 0
    if engine_options:
        options.update(engine_options)
    return create_async_engine(normalized_url, **options)


def async_session_factory(
    engine: AsyncEngine,
) -> async_sessionmaker:
    return async_sessionmaker(engine, expire_on_commit=False)


def runtime_engine(settings: Settings) -> AsyncEngine:
    return build_async_engine(settings.require_database_url(), pooled=True)


def direct_engine(settings: Settings) -> AsyncEngine:
    return build_async_engine(settings.require_database_url(direct=True), pooled=False)