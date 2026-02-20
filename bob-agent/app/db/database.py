from collections.abc import AsyncGenerator

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase

from app.config import settings


class Base(DeclarativeBase):
    pass


# Populated by init_db_engine() at startup; test fixtures inject their own.
_engine: AsyncEngine | None = None
_session_factory: async_sessionmaker[AsyncSession] | None = None


def _make_engine(url: str) -> AsyncEngine:
    """Create an async engine. PostgreSQL gets pool tuning; SQLite gets bare engine."""
    if url.startswith("postgresql"):
        return create_async_engine(
            url,
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
