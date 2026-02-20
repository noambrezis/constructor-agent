"""Unit tests for M2 — Database Layer repositories.

All tests use an in-memory SQLite database (via aiosqlite) for speed.
The one exception is test_get_next_defect_id_advisory_lock which requires
PostgreSQL for the pg_advisory_xact_lock call and is skipped when SQLite is used.
"""

import asyncio

import pytest
import pytest_asyncio
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.db.database import Base
from app.db.models import Defect, ProcessedMessage, Site
from app.db.repositories import defect_repo, dedup_repo, site_repo


# ---------------------------------------------------------------------------
# In-memory SQLite fixtures
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture
async def sqlite_session():
    """Ephemeral SQLite DB, tables created fresh for each test."""
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with session_factory() as session:
        yield session

    await engine.dispose()


# ---------------------------------------------------------------------------
# Site repository tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_create_and_get_site(sqlite_session: AsyncSession):
    site = await site_repo.create(sqlite_session, group_id="group-1", name="Test Site")
    await sqlite_session.commit()

    found = await site_repo.get_by_group_id(sqlite_session, "group-1")
    assert found is not None
    assert found.name == "Test Site"
    assert found.id == site.id


@pytest.mark.asyncio
async def test_get_by_group_id_missing(sqlite_session: AsyncSession):
    result = await site_repo.get_by_group_id(sqlite_session, "nonexistent")
    assert result is None


@pytest.mark.asyncio
async def test_update_site(sqlite_session: AsyncSession):
    await site_repo.create(sqlite_session, group_id="group-2", name="Before")
    await sqlite_session.commit()

    updated = await site_repo.update(sqlite_session, "group-2", name="After")
    await sqlite_session.commit()

    assert updated is not None
    assert updated.name == "After"


@pytest.mark.asyncio
async def test_disable_site(sqlite_session: AsyncSession):
    await site_repo.create(sqlite_session, group_id="group-3", name="Active")
    await sqlite_session.commit()

    disabled = await site_repo.disable(sqlite_session, "group-3")
    await sqlite_session.commit()

    assert disabled is not None
    assert disabled.training_phase == "Disabled"


@pytest.mark.asyncio
async def test_get_all_sites(sqlite_session: AsyncSession):
    await site_repo.create(sqlite_session, group_id="group-4", name="A")
    await site_repo.create(sqlite_session, group_id="group-5", name="B")
    await sqlite_session.commit()

    sites = await site_repo.get_all(sqlite_session)
    group_ids = [s.group_id for s in sites]
    assert "group-4" in group_ids
    assert "group-5" in group_ids


# ---------------------------------------------------------------------------
# Defect repository tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_create_defect(sqlite_session: AsyncSession):
    site = await site_repo.create(sqlite_session, group_id="group-d1")
    defect = await defect_repo.create(
        sqlite_session,
        defect_id=1,
        site_id=site.id,
        description="Crack in wall",
        reporter="user@s.whatsapp.net",
    )
    await sqlite_session.commit()

    found = await defect_repo.get_by_site_and_defect_id(sqlite_session, site.id, 1)
    assert found is not None
    assert found.description == "Crack in wall"
    assert found.status == "פתוח"


@pytest.mark.asyncio
async def test_update_defect_skips_empty_fields(sqlite_session: AsyncSession):
    site = await site_repo.create(sqlite_session, group_id="group-d2")
    await defect_repo.create(
        sqlite_session,
        defect_id=1,
        site_id=site.id,
        description="Original",
        supplier="SupplierA",
    )
    await sqlite_session.commit()

    # Empty string should NOT overwrite existing value
    updated = await defect_repo.update(
        sqlite_session, site.id, 1, description="Updated", supplier=""
    )
    await sqlite_session.commit()

    assert updated is not None
    assert updated.description == "Updated"
    assert updated.supplier == "SupplierA"  # unchanged


@pytest.mark.asyncio
async def test_get_all_for_site(sqlite_session: AsyncSession):
    site = await site_repo.create(sqlite_session, group_id="group-d3")
    await defect_repo.create(
        sqlite_session, defect_id=1, site_id=site.id, description="D1"
    )
    await defect_repo.create(
        sqlite_session, defect_id=2, site_id=site.id, description="D2"
    )
    await sqlite_session.commit()

    defects = await defect_repo.get_all_for_site(sqlite_session, site.id)
    assert len(defects) == 2
    assert defects[0].defect_id == 1
    assert defects[1].defect_id == 2


# ---------------------------------------------------------------------------
# Dedup repository tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_mark_and_check_processed(sqlite_session: AsyncSession):
    assert not await dedup_repo.is_already_processed(sqlite_session, "msg-1")

    await dedup_repo.mark_as_processed(sqlite_session, "msg-1", "group-dup")
    await sqlite_session.commit()

    assert await dedup_repo.is_already_processed(sqlite_session, "msg-1")


@pytest.mark.asyncio
async def test_duplicate_mark_is_idempotent(sqlite_session: AsyncSession):
    await dedup_repo.mark_as_processed(sqlite_session, "msg-2", "group-dup")
    await sqlite_session.commit()

    # Second insert should silently succeed (ON CONFLICT DO NOTHING)
    await dedup_repo.mark_as_processed(sqlite_session, "msg-2", "group-dup")
    await sqlite_session.commit()

    assert await dedup_repo.is_already_processed(sqlite_session, "msg-2")
