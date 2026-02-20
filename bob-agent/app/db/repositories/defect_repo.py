from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Defect


async def get_next_defect_id(session: AsyncSession, site_id: int) -> int:
    """Return the next site-scoped defect ID using a PostgreSQL advisory lock.

    The advisory lock is released automatically when the enclosing transaction
    commits or rolls back. Callers must open a transaction before calling this.
    """
    await session.execute(
        text("SELECT pg_advisory_xact_lock(:key)"),
        {"key": site_id},
    )
    result = await session.execute(
        select(func.max(Defect.defect_id)).where(Defect.site_id == site_id)
    )
    current_max = result.scalar() or 0
    return current_max + 1


async def create(session: AsyncSession, **kwargs: object) -> Defect:
    defect = Defect(**kwargs)
    session.add(defect)
    await session.flush()
    await session.refresh(defect)
    return defect


async def get_by_site_and_defect_id(
    session: AsyncSession, site_id: int, defect_id: int
) -> Defect | None:
    result = await session.execute(
        select(Defect).where(Defect.site_id == site_id, Defect.defect_id == defect_id)
    )
    return result.scalar_one_or_none()


async def get_all_for_site(session: AsyncSession, site_id: int) -> list[Defect]:
    result = await session.execute(
        select(Defect).where(Defect.site_id == site_id).order_by(Defect.defect_id)
    )
    return list(result.scalars().all())


async def update(
    session: AsyncSession, site_id: int, defect_id: int, **kwargs: object
) -> Defect | None:
    defect = await get_by_site_and_defect_id(session, site_id, defect_id)
    if defect is None:
        return None
    for key, value in kwargs.items():
        if value != "":  # only update non-empty fields
            setattr(defect, key, value)
    await session.flush()
    await session.refresh(defect)
    return defect
