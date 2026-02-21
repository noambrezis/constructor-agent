"""Redis-backed site context cache.

Caches the fields tools need from a Site row keyed by group_id.
On a cache miss (or Redis unavailable) falls back to the database.
Invalidation is called after any admin update or logo change.
"""

import json
import logging
from dataclasses import asdict, dataclass

import redis.asyncio as aioredis

from app.config import settings
from app.db.database import get_db_session
from app.db.repositories import site_repo

logger = logging.getLogger(__name__)

_CACHE_KEY_PREFIX = "site:"


@dataclass
class CachedSite:
    """Lightweight representation of the Site row used throughout the agent."""

    id: int
    group_id: str
    name: str
    logo_url: str
    training_phase: str
    context: dict


class SiteCache:
    """Singleton that caches site data in Redis with a configurable TTL.

    Usage:
        await site_cache.startup(redis_url)   # called from FastAPI lifespan
        site = await site_cache.get(group_id)
        await site_cache.invalidate(group_id) # after admin / logo update
        await site_cache.shutdown()
    """

    def __init__(self) -> None:
        self._redis: aioredis.Redis | None = None

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def startup(self, redis_url: str) -> None:
        self._redis = aioredis.from_url(redis_url, decode_responses=True)

    async def shutdown(self) -> None:
        if self._redis is not None:
            await self._redis.aclose()
            self._redis = None

    # ------------------------------------------------------------------
    # Cache operations
    # ------------------------------------------------------------------

    async def get(self, group_id: str) -> CachedSite | None:
        """Return a CachedSite for *group_id*, populating cache on a miss."""
        cached = await self._redis_get(group_id)
        if cached is not None:
            return cached

        # Cache miss — hit the database
        site = await self._load_from_db(group_id)
        if site is not None:
            await self._redis_set(group_id, site)
        return site

    async def invalidate(self, group_id: str) -> None:
        """Remove the cached entry so the next call re-reads from the DB."""
        if self._redis is None:
            return
        try:
            await self._redis.delete(f"{_CACHE_KEY_PREFIX}{group_id}")
        except Exception:
            logger.warning("site_cache_invalidate_error", exc_info=True)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    async def _redis_get(self, group_id: str) -> CachedSite | None:
        if self._redis is None:
            return None
        try:
            raw = await self._redis.get(f"{_CACHE_KEY_PREFIX}{group_id}")
            if raw is None:
                return None
            data = json.loads(raw)
            return CachedSite(**data)
        except Exception:
            logger.warning("site_cache_read_error", exc_info=True)
            return None

    async def _redis_set(self, group_id: str, site: CachedSite) -> None:
        if self._redis is None:
            return
        try:
            payload = json.dumps(asdict(site))
            await self._redis.setex(
                f"{_CACHE_KEY_PREFIX}{group_id}",
                settings.SITE_CACHE_TTL_SECONDS,
                payload,
            )
        except Exception:
            logger.warning("site_cache_write_error", exc_info=True)

    @staticmethod
    async def _load_from_db(group_id: str) -> CachedSite | None:
        async with get_db_session() as session:
            site_obj = await site_repo.get_by_group_id(session, group_id)
        if site_obj is None:
            return None
        return CachedSite(
            id=site_obj.id,
            group_id=site_obj.group_id,
            name=site_obj.name or "",
            logo_url=site_obj.logo_url or "",
            training_phase=site_obj.training_phase or "",
            context=site_obj.context or {},
        )


# Module-level singleton — shared across the whole process.
site_cache = SiteCache()
