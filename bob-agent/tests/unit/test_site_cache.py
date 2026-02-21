"""Unit tests for app/services/site_cache.py."""

import json
from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, MagicMock, patch

import fakeredis.aioredis
import pytest

from app.services.site_cache import CachedSite, SiteCache

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

GROUP_ID = "group-1@g.us"

SITE_DATA = CachedSite(
    id=1,
    group_id=GROUP_ID,
    name="Test Site",
    logo_url="https://example.com/logo.png",
    training_phase="Active",
    context={"suppliers": ["ספק א"], "locations": ["קומה 1"]},
)


def _make_db_site():
    """ORM-like mock object returned by site_repo.get_by_group_id."""
    obj = MagicMock()
    obj.id = SITE_DATA.id
    obj.group_id = SITE_DATA.group_id
    obj.name = SITE_DATA.name
    obj.logo_url = SITE_DATA.logo_url
    obj.training_phase = SITE_DATA.training_phase
    obj.context = SITE_DATA.context
    return obj


@asynccontextmanager
async def _mock_db_session(session):
    yield session


# ---------------------------------------------------------------------------
# Cache hit
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_returns_cached_value():
    cache = SiteCache()
    cache._redis = fakeredis.aioredis.FakeRedis(decode_responses=True)

    # Pre-populate
    import dataclasses
    payload = json.dumps(dataclasses.asdict(SITE_DATA))
    await cache._redis.setex(f"site:{GROUP_ID}", 300, payload)

    with patch("app.services.site_cache.get_db_session") as mock_db:
        result = await cache.get(GROUP_ID)

    assert result is not None
    assert result.id == SITE_DATA.id
    assert result.name == SITE_DATA.name
    assert result.context == SITE_DATA.context
    mock_db.assert_not_called()  # DB not touched on cache hit

    await cache._redis.aclose()


# ---------------------------------------------------------------------------
# Cache miss → DB fallback → cache population
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_populates_cache_on_miss():
    cache = SiteCache()
    cache._redis = fakeredis.aioredis.FakeRedis(decode_responses=True)

    db_obj = _make_db_site()
    mock_session = AsyncMock()

    with patch("app.services.site_cache.site_repo") as mock_repo, patch(
        "app.services.site_cache.get_db_session", lambda: _mock_db_session(mock_session)
    ):
        mock_repo.get_by_group_id = AsyncMock(return_value=db_obj)

        result = await cache.get(GROUP_ID)

    assert result is not None
    assert result.id == 1
    assert result.name == "Test Site"

    # Verify the value is now in Redis
    raw = await cache._redis.get(f"site:{GROUP_ID}")
    assert raw is not None
    data = json.loads(raw)
    assert data["id"] == 1

    await cache._redis.aclose()


@pytest.mark.asyncio
async def test_get_returns_none_for_unknown_group():
    cache = SiteCache()
    cache._redis = fakeredis.aioredis.FakeRedis(decode_responses=True)

    mock_session = AsyncMock()

    with patch("app.services.site_cache.site_repo") as mock_repo, patch(
        "app.services.site_cache.get_db_session", lambda: _mock_db_session(mock_session)
    ):
        mock_repo.get_by_group_id = AsyncMock(return_value=None)

        result = await cache.get("unknown@g.us")

    assert result is None
    # Nothing written to Redis
    raw = await cache._redis.get("site:unknown@g.us")
    assert raw is None

    await cache._redis.aclose()


# ---------------------------------------------------------------------------
# Cache TTL is set
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_cache_entry_has_ttl():
    cache = SiteCache()
    cache._redis = fakeredis.aioredis.FakeRedis(decode_responses=True)

    mock_session = AsyncMock()
    db_obj = _make_db_site()

    with patch("app.services.site_cache.site_repo") as mock_repo, patch(
        "app.services.site_cache.get_db_session", lambda: _mock_db_session(mock_session)
    ), patch("app.services.site_cache.settings") as mock_settings:
        mock_settings.SITE_CACHE_TTL_SECONDS = 120
        mock_repo.get_by_group_id = AsyncMock(return_value=db_obj)

        await cache.get(GROUP_ID)

    ttl = await cache._redis.ttl(f"site:{GROUP_ID}")
    assert ttl > 0

    await cache._redis.aclose()


# ---------------------------------------------------------------------------
# Invalidate
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_invalidate_removes_entry():
    cache = SiteCache()
    cache._redis = fakeredis.aioredis.FakeRedis(decode_responses=True)

    import dataclasses
    payload = json.dumps(dataclasses.asdict(SITE_DATA))
    await cache._redis.setex(f"site:{GROUP_ID}", 300, payload)

    await cache.invalidate(GROUP_ID)

    raw = await cache._redis.get(f"site:{GROUP_ID}")
    assert raw is None

    await cache._redis.aclose()


@pytest.mark.asyncio
async def test_invalidate_is_noop_when_no_redis():
    cache = SiteCache()
    cache._redis = None
    # Should not raise
    await cache.invalidate(GROUP_ID)


# ---------------------------------------------------------------------------
# Graceful degradation — Redis unavailable
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_falls_back_to_db_when_redis_errors():
    cache = SiteCache()
    # Redis that raises on every call
    bad_redis = AsyncMock()
    bad_redis.get = AsyncMock(side_effect=ConnectionError("redis down"))
    cache._redis = bad_redis

    mock_session = AsyncMock()
    db_obj = _make_db_site()

    with patch("app.services.site_cache.site_repo") as mock_repo, patch(
        "app.services.site_cache.get_db_session", lambda: _mock_db_session(mock_session)
    ):
        mock_repo.get_by_group_id = AsyncMock(return_value=db_obj)

        result = await cache.get(GROUP_ID)

    assert result is not None
    assert result.id == 1


@pytest.mark.asyncio
async def test_get_works_without_redis():
    """When _redis is None (Redis not started), falls back to DB silently."""
    cache = SiteCache()
    cache._redis = None

    mock_session = AsyncMock()
    db_obj = _make_db_site()

    with patch("app.services.site_cache.site_repo") as mock_repo, patch(
        "app.services.site_cache.get_db_session", lambda: _mock_db_session(mock_session)
    ):
        mock_repo.get_by_group_id = AsyncMock(return_value=db_obj)

        result = await cache.get(GROUP_ID)

    assert result is not None
    assert result.name == "Test Site"


# ---------------------------------------------------------------------------
# Second call hits cache (no extra DB round-trip)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_second_call_uses_cache_not_db():
    cache = SiteCache()
    cache._redis = fakeredis.aioredis.FakeRedis(decode_responses=True)

    mock_session = AsyncMock()
    db_obj = _make_db_site()

    with patch("app.services.site_cache.site_repo") as mock_repo, patch(
        "app.services.site_cache.get_db_session", lambda: _mock_db_session(mock_session)
    ):
        mock_repo.get_by_group_id = AsyncMock(return_value=db_obj)

        await cache.get(GROUP_ID)   # miss — hits DB
        await cache.get(GROUP_ID)   # hit — should NOT hit DB again

    assert mock_repo.get_by_group_id.call_count == 1

    await cache._redis.aclose()
