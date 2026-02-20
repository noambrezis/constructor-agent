import asyncio
import os
from logging.config import fileConfig
from urllib.parse import parse_qs, urlencode, urlparse, urlunparse

from alembic import context
from sqlalchemy.ext.asyncio import create_async_engine

import app.db.models  # noqa: F401 — ensure models are registered on Base.metadata
from app.db.database import Base

target_metadata = Base.metadata

config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name)


def _asyncpg_url(raw_url: str) -> tuple[str, dict]:
    """Strip params asyncpg doesn't accept; return (clean_url, connect_args)."""
    parsed = urlparse(raw_url)
    params = parse_qs(parsed.query, keep_blank_values=True)

    # asyncpg doesn't understand sslmode / channel_binding — handle SSL via connect_args
    needs_ssl = params.pop("sslmode", ["disable"])[0] in ("require", "verify-ca", "verify-full")
    params.pop("channel_binding", None)

    clean = urlunparse(parsed._replace(query=urlencode(params, doseq=True)))
    connect_args = {"ssl": needs_ssl} if needs_ssl else {}
    return clean, connect_args


_raw_db_url = os.environ["DATABASE_URL"]
_db_url, _connect_args = _asyncpg_url(_raw_db_url)
config.set_main_option("sqlalchemy.url", _db_url)


def run_migrations_offline() -> None:
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection):
    context.configure(connection=connection, target_metadata=target_metadata)
    with context.begin_transaction():
        context.run_migrations()


async def run_migrations_online() -> None:
    url = config.get_main_option("sqlalchemy.url")
    connectable = create_async_engine(url, connect_args=_connect_args)
    async with connectable.connect() as connection:
        await connection.run_sync(do_run_migrations)
    await connectable.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    asyncio.run(run_migrations_online())
