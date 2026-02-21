"""Unit tests for app/admin/router.py — Admin API site CRUD."""

from unittest.mock import AsyncMock, patch

import httpx
import pytest
import pytest_asyncio
import fakeredis.aioredis
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

import app.db.models  # noqa: F401
from app.db.database import Base
from app.main import app
from app.services.bridge_service import bridge
from app.services.site_cache import site_cache

ADMIN_KEY = "test-admin-key"

# ---------------------------------------------------------------------------
# Fixtures — shared with test_webhook pattern
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture(autouse=True)
async def setup_app_state():
    """In-memory SQLite DB + fake Redis, bridge stubbed."""
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)

    import app.db.database as db_module
    original_factory = db_module._session_factory
    db_module._session_factory = session_factory
    db_module._engine = engine

    fake_redis = fakeredis.aioredis.FakeRedis(decode_responses=True)
    app.state.redis = fake_redis
    await site_cache.startup.__func__(site_cache, "redis://localhost")
    site_cache._redis = fake_redis

    bridge._client = httpx.AsyncClient(
        base_url="https://bridge.test",
        transport=httpx.MockTransport(lambda r: httpx.Response(200)),
    )

    mock_arq_pool = AsyncMock()
    mock_arq_pool.enqueue_job = AsyncMock()
    app.state.arq_pool = mock_arq_pool

    yield

    db_module._session_factory = original_factory
    await engine.dispose()
    await fake_redis.aclose()
    bridge._client = None
    site_cache._redis = None


@pytest_asyncio.fixture
async def client():
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as c:
        yield c


def _headers(key: str = ADMIN_KEY) -> dict:
    return {"X-Admin-Key": key}


def _site_payload(**kwargs) -> dict:
    base = {
        "group_id": "group-admin@g.us",
        "name": "אתר בדיקה",
        "training_phase": "",
        "context": {"locations": ["קומה 1"], "suppliers": ["ספק א"]},
    }
    base.update(kwargs)
    return base


# ---------------------------------------------------------------------------
# Auth
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_missing_admin_key_returns_401(client):
    r = await client.post("/admin/sites", json=_site_payload())
    assert r.status_code == 401


@pytest.mark.asyncio
async def test_wrong_admin_key_returns_401(client):
    r = await client.post("/admin/sites", json=_site_payload(), headers={"X-Admin-Key": "wrong"})
    assert r.status_code == 401


# ---------------------------------------------------------------------------
# POST /admin/sites
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_create_site_returns_201(client):
    r = await client.post("/admin/sites", json=_site_payload(), headers=_headers())
    assert r.status_code == 201
    body = r.json()
    assert body["group_id"] == "group-admin@g.us"
    assert body["name"] == "אתר בדיקה"
    assert "id" in body


@pytest.mark.asyncio
async def test_create_site_stores_context(client):
    payload = _site_payload(context={"locations": ["לובי"], "suppliers": ["שיכון ובינוי"]})
    r = await client.post("/admin/sites", json=payload, headers=_headers())
    assert r.status_code == 201
    assert r.json()["context"]["suppliers"] == ["שיכון ובינוי"]


# ---------------------------------------------------------------------------
# GET /admin/sites
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_list_sites_empty(client):
    r = await client.get("/admin/sites", headers=_headers())
    assert r.status_code == 200
    assert r.json() == []


@pytest.mark.asyncio
async def test_list_sites_after_create(client):
    await client.post("/admin/sites", json=_site_payload(), headers=_headers())
    r = await client.get("/admin/sites", headers=_headers())
    assert r.status_code == 200
    assert len(r.json()) == 1


# ---------------------------------------------------------------------------
# GET /admin/sites/{group_id}
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_site_not_found(client):
    r = await client.get("/admin/sites/nonexistent@g.us", headers=_headers())
    assert r.status_code == 404


@pytest.mark.asyncio
async def test_get_site_returns_site(client):
    await client.post("/admin/sites", json=_site_payload(), headers=_headers())
    r = await client.get("/admin/sites/group-admin@g.us", headers=_headers())
    assert r.status_code == 200
    assert r.json()["group_id"] == "group-admin@g.us"


# ---------------------------------------------------------------------------
# PATCH /admin/sites/{group_id}
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_patch_site_updates_name(client):
    await client.post("/admin/sites", json=_site_payload(), headers=_headers())
    r = await client.patch(
        "/admin/sites/group-admin@g.us",
        json={"name": "שם חדש"},
        headers=_headers(),
    )
    assert r.status_code == 200
    assert r.json()["name"] == "שם חדש"


@pytest.mark.asyncio
async def test_patch_site_not_found(client):
    r = await client.patch("/admin/sites/nonexistent@g.us", json={"name": "x"}, headers=_headers())
    assert r.status_code == 404


@pytest.mark.asyncio
async def test_patch_site_invalidates_cache(client):
    await client.post("/admin/sites", json=_site_payload(), headers=_headers())
    with patch.object(site_cache, "invalidate", new_callable=AsyncMock) as mock_inv:
        r = await client.patch(
            "/admin/sites/group-admin@g.us",
            json={"training_phase": "Active"},
            headers=_headers(),
        )
    assert r.status_code == 200
    mock_inv.assert_called_once_with("group-admin@g.us")


# ---------------------------------------------------------------------------
# DELETE /admin/sites/{group_id} (soft-delete)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_delete_site_disables_it(client):
    await client.post("/admin/sites", json=_site_payload(), headers=_headers())
    r = await client.delete("/admin/sites/group-admin@g.us", headers=_headers())
    assert r.status_code == 200
    assert r.json()["training_phase"] == "Disabled"


@pytest.mark.asyncio
async def test_delete_site_not_found(client):
    r = await client.delete("/admin/sites/nonexistent@g.us", headers=_headers())
    assert r.status_code == 404


@pytest.mark.asyncio
async def test_delete_site_invalidates_cache(client):
    await client.post("/admin/sites", json=_site_payload(), headers=_headers())
    with patch.object(site_cache, "invalidate", new_callable=AsyncMock) as mock_inv:
        r = await client.delete("/admin/sites/group-admin@g.us", headers=_headers())
    assert r.status_code == 200
    mock_inv.assert_called_once_with("group-admin@g.us")
