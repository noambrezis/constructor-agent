"""Admin API router — site CRUD with cache invalidation."""

import hmac
import logging
from typing import Annotated

from fastapi import APIRouter, Depends, Header, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.db.database import get_session
from app.db.repositories import site_repo
from app.services.site_cache import site_cache

from .schemas import SiteCreate, SiteResponse, SiteUpdate

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/admin", tags=["admin"])


# ---------------------------------------------------------------------------
# Auth dependency
# ---------------------------------------------------------------------------


def require_admin_key(x_admin_key: Annotated[str | None, Header()] = None) -> None:
    if not x_admin_key or not hmac.compare_digest(
        x_admin_key.encode(), settings.ADMIN_API_KEY.encode()
    ):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid admin key")


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------


@router.post("/sites", response_model=SiteResponse, status_code=status.HTTP_201_CREATED,
             dependencies=[Depends(require_admin_key)])
async def create_site(
    payload: SiteCreate,
    session: AsyncSession = Depends(get_session),
) -> SiteResponse:
    site = await site_repo.create(
        session,
        group_id=payload.group_id,
        name=payload.name,
        training_phase=payload.training_phase,
        context=payload.context,
        logo_url=payload.logo_url,
    )
    await session.commit()
    await session.refresh(site)
    logger.info("admin_site_created", extra={"group_id": site.group_id})
    return SiteResponse.model_validate(site)


@router.get("/sites", response_model=list[SiteResponse],
            dependencies=[Depends(require_admin_key)])
async def list_sites(session: AsyncSession = Depends(get_session)) -> list[SiteResponse]:
    sites = await site_repo.get_all(session)
    return [SiteResponse.model_validate(s) for s in sites]


@router.get("/sites/{group_id}", response_model=SiteResponse,
            dependencies=[Depends(require_admin_key)])
async def get_site(group_id: str, session: AsyncSession = Depends(get_session)) -> SiteResponse:
    site = await site_repo.get_by_group_id(session, group_id)
    if site is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Site not found")
    return SiteResponse.model_validate(site)


@router.patch("/sites/{group_id}", response_model=SiteResponse,
              dependencies=[Depends(require_admin_key)])
async def update_site(
    group_id: str,
    payload: SiteUpdate,
    session: AsyncSession = Depends(get_session),
) -> SiteResponse:
    updates = payload.model_dump(exclude_none=True)
    if not updates:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="No fields to update")

    site = await site_repo.update(session, group_id, **updates)
    if site is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Site not found")
    await session.commit()
    await session.refresh(site)
    await site_cache.invalidate(group_id)
    logger.info("admin_site_updated", extra={"group_id": group_id, "fields": list(updates.keys())})
    return SiteResponse.model_validate(site)


@router.delete("/sites/{group_id}", response_model=SiteResponse,
               dependencies=[Depends(require_admin_key)])
async def delete_site(
    group_id: str,
    session: AsyncSession = Depends(get_session),
) -> SiteResponse:
    site = await site_repo.disable(session, group_id)
    if site is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Site not found")
    await session.commit()
    await session.refresh(site)
    await site_cache.invalidate(group_id)
    logger.info("admin_site_disabled", extra={"group_id": group_id})
    return SiteResponse.model_validate(site)
