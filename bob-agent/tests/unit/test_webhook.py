"""Unit tests for M4 — /webhook/agent endpoint.

Uses:
- httpx.AsyncClient + ASGITransport to call the real FastAPI app
- aiosqlite in-memory DB for dedup (processed_messages)
- fakeredis for the rate limiter
- MockTransport for the Bridge HTTP client
"""

import pytest
import pytest_asyncio
import httpx
import fakeredis.aioredis
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

import app.db.models  # noqa: F401 — register models on Base.metadata
from app.db.database import Base, _session_factory
from app.main import app
from app.services.bridge_service import bridge

# ---------------------------------------------------------------------------
# Shared test payload factory
# ---------------------------------------------------------------------------

def _payload(message_id: str = "msg-001", group_id: str = "group-1@g.us") -> dict:
    return {
        "body": {
            "messageId": message_id,
            "groupId": group_id,
            "sender": "9720501234567@s.whatsapp.net",
            "type": "message",
            "messageText": "בדיקה",
        }
    }

WEBHOOK_SECRET = "test-secret"

# ---------------------------------------------------------------------------
# App-level fixture: override DB + Redis + Bridge for the entire test session
# ---------------------------------------------------------------------------

@pytest_asyncio.fixture(autouse=True)
async def setup_app_state():
    """Replace app.state.redis and db engine with in-memory test doubles."""
    # 1. In-memory SQLite DB — create tables
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)

    # 2. Patch module-level session factory used by get_session()
    import app.db.database as db_module
    original_factory = db_module._session_factory
    db_module._session_factory = session_factory
    db_module._engine = engine

    # 3. Fake Redis
    fake_redis = fakeredis.aioredis.FakeRedis(decode_responses=True)
    app.state.redis = fake_redis

    # 4. Stub out Bridge so no real HTTP calls are made
    bridge._client = httpx.AsyncClient(
        base_url="https://bridge.test",
        transport=httpx.MockTransport(lambda r: httpx.Response(200)),
    )

    yield

    # Cleanup
    db_module._session_factory = original_factory
    await engine.dispose()
    await fake_redis.aclose()
    bridge._client = None


# ---------------------------------------------------------------------------
# Test client fixture
# ---------------------------------------------------------------------------

@pytest_asyncio.fixture
async def client():
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as c:
        yield c


def _headers(secret: str = WEBHOOK_SECRET) -> dict:
    return {"X-Webhook-Secret": secret}


# ---------------------------------------------------------------------------
# Auth tests
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_missing_secret_returns_401(client):
    r = await client.post("/webhook/agent", json=_payload())
    assert r.status_code == 401


@pytest.mark.asyncio
async def test_wrong_secret_returns_401(client):
    r = await client.post("/webhook/agent", json=_payload(), headers={"X-Webhook-Secret": "wrong"})
    assert r.status_code == 401


@pytest.mark.asyncio
async def test_valid_secret_accepts_message(client):
    r = await client.post("/webhook/agent", json=_payload(), headers=_headers())
    assert r.status_code == 200
    assert r.json()["status"] == "accepted"


# ---------------------------------------------------------------------------
# Deduplication tests
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_duplicate_message_returns_duplicate(client):
    payload = _payload("msg-dup-001")
    headers = _headers()

    r1 = await client.post("/webhook/agent", json=payload, headers=headers)
    assert r1.json()["status"] == "accepted"

    r2 = await client.post("/webhook/agent", json=payload, headers=headers)
    assert r2.status_code == 200
    assert r2.json()["status"] == "duplicate"


@pytest.mark.asyncio
async def test_different_message_ids_both_accepted(client):
    headers = _headers()
    r1 = await client.post("/webhook/agent", json=_payload("msg-a"), headers=headers)
    r2 = await client.post("/webhook/agent", json=_payload("msg-b"), headers=headers)
    assert r1.json()["status"] == "accepted"
    assert r2.json()["status"] == "accepted"


# ---------------------------------------------------------------------------
# Rate limiting tests
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_rate_limit_exceeded_returns_429(client):
    headers = _headers()
    max_msgs = 20  # RATE_LIMIT_MAX_MESSAGES default

    # Send max+1 messages with unique IDs to avoid dedup
    for i in range(max_msgs + 1):
        r = await client.post("/webhook/agent", json=_payload(f"msg-rl-{i}"), headers=headers)

    assert r.status_code == 429


@pytest.mark.asyncio
async def test_rate_limit_different_groups_independent(client):
    headers = _headers()
    max_msgs = 20

    # Exhaust rate limit for group-A
    for i in range(max_msgs + 1):
        await client.post(
            "/webhook/agent", json=_payload(f"msg-ga-{i}", "group-A@g.us"), headers=headers
        )

    # group-B should still be accepted
    r = await client.post(
        "/webhook/agent", json=_payload("msg-gb-0", "group-B@g.us"), headers=headers
    )
    assert r.status_code == 200
    assert r.json()["status"] == "accepted"


# ---------------------------------------------------------------------------
# Health endpoint
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_health(client):
    r = await client.get("/health")
    assert r.status_code == 200
    assert r.json() == {"status": "ok"}
