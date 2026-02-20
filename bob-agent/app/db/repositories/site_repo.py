from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Site


async def get_by_group_id(session: AsyncSession, group_id: str) -> Site | None:
    result = await session.execute(select(Site).where(Site.group_id == group_id))
    return result.scalar_one_or_none()


async def get_all(session: AsyncSession) -> list[Site]:
    result = await session.execute(select(Site).order_by(Site.id))
    return list(result.scalars().all())


async def create(session: AsyncSession, **kwargs: object) -> Site:
    site = Site(**kwargs)
    session.add(site)
    await session.flush()
    await session.refresh(site)
    return site


async def update(session: AsyncSession, group_id: str, **kwargs: object) -> Site | None:
    site = await get_by_group_id(session, group_id)
    if site is None:
        return None
    for key, value in kwargs.items():
        setattr(site, key, value)
    await session.flush()
    await session.refresh(site)
    return site


async def disable(session: AsyncSession, group_id: str) -> Site | None:
    """Soft-delete: set training_phase to 'Disabled'."""
    return await update(session, group_id, training_phase="Disabled")
