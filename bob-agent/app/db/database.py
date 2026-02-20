from collections.abc import AsyncGenerator
from urllib.parse import parse_qs, urlencode, urlparse, urlunparse

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase

from app.config import settings


class Base(DeclarativeBase):
    pass


# Populated by init_db_engine() at startup; test fixtures inject their own.
_engine: AsyncEngine | None = None
_session_factory: async_sessionmaker[AsyncSession] | None = None


def _clean_pg_url(url: str) -> tuple[str, dict]:
    """Strip asyncpg-incompatible query params; return (clean_url, connect_args)."""
    parsed = urlparse(url)
    params = parse_qs(parsed.query, keep_blank_values=True)
    needs_ssl = params.pop("sslmode", ["disable"])[0] in ("require", "verify-ca", "verify-full")
    params.pop("channel_binding", None)
    clean = urlunparse(parsed._replace(query=urlencode(params, doseq=True)))
    connect_args = {"ssl": True} if needs_ssl else {}
    return clean, connect_args


def _make_engine(url: str) -> AsyncEngine:
    """Create an async engine. PostgreSQL gets pool tuning; SQLite gets bare engine."""
    if url.startswith("postgresql"):
        clean_url, connect_args = _clean_pg_url(url)
        return create_async_engine(
            clean_url,
            connect_args=connect_args,
            pool_size=settings.DB_POOL_SIZE,
            max_overflow=settings.DB_MAX_OVERFLOW,
            pool_pre_ping=True,
        )
    return create_async_engine(url)


async def init_db_engine(url: str | None = None) -> None:
    """Validate DB connection and initialise the module-level engine.

    Called from FastAPI lifespan. Tests can pass a custom URL to override.
    """
    global _engine, _session_factory
    _engine = _make_engine(url or settings.DATABASE_URL)
    _session_factory = async_sessionmaker(_engine, expire_on_commit=False)
    async with _engine.connect() as conn:
        await conn.execute(text("SELECT 1"))


async def get_session() -> AsyncGenerator[AsyncSession, None]:
    """FastAPI dependency that yields an AsyncSession."""
    if _session_factory is None:
        raise RuntimeError("Database engine is not initialised. Call init_db_engine() first.")
    async with _session_factory() as session:
        yield session
