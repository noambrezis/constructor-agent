"""Unit tests for app/worker.py — process_message task and WorkerSettings."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# process_message
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_process_message_calls_run_agent():
    from app.worker import process_message

    body = {
        "messageId": "msg-001",
        "groupId": "group-1@g.us",
        "sender": "972501234567@s.whatsapp.net",
        "type": "message",
        "messageText": "שלום",
    }

    with patch("app.worker.run_agent", new_callable=AsyncMock) as mock_run:
        await process_message({}, body)

    mock_run.assert_called_once()
    call_arg = mock_run.call_args[0][0]
    assert call_arg.groupId == "group-1@g.us"
    assert call_arg.messageId == "msg-001"
    assert call_arg.messageText == "שלום"


@pytest.mark.asyncio
async def test_process_message_passes_reaction_fields():
    from app.worker import process_message

    body = {
        "messageId": "msg-002",
        "groupId": "group-1@g.us",
        "sender": "972501234567@s.whatsapp.net",
        "type": "reaction",
        "emoji": "👍",
        "originalMessage": {"text": "crack in wall"},
    }

    with patch("app.worker.run_agent", new_callable=AsyncMock) as mock_run:
        await process_message({}, body)

    call_arg = mock_run.call_args[0][0]
    assert call_arg.type == "reaction"
    assert call_arg.emoji == "👍"
    assert call_arg.originalMessage is not None
    assert call_arg.originalMessage.text == "crack in wall"


@pytest.mark.asyncio
async def test_process_message_propagates_run_agent_exception():
    """Unhandled exceptions should propagate so ARQ can retry the job."""
    from app.worker import process_message

    body = {
        "messageId": "msg-003",
        "groupId": "group-1@g.us",
        "sender": "972501234567@s.whatsapp.net",
        "type": "message",
        "messageText": "שלום",
    }

    with patch("app.worker.run_agent", new_callable=AsyncMock, side_effect=RuntimeError("LLM timeout")):
        with pytest.raises(RuntimeError, match="LLM timeout"):
            await process_message({}, body)


@pytest.mark.asyncio
async def test_process_message_invalid_body_raises_validation_error():
    """Pydantic validation failure should propagate (ARQ will move job to failed)."""
    from pydantic import ValidationError

    from app.worker import process_message

    bad_body = {"groupId": "group-1@g.us"}  # missing required messageId, sender, type

    with pytest.raises(ValidationError):
        await process_message({}, bad_body)


# ---------------------------------------------------------------------------
# WorkerSettings
# ---------------------------------------------------------------------------


def test_worker_settings_has_process_message():
    from app.worker import WorkerSettings, process_message

    assert process_message in WorkerSettings.functions


def test_worker_settings_retry_config():
    from app.worker import WorkerSettings

    assert WorkerSettings.max_tries == 3
    assert WorkerSettings.retry_jobs is True
    assert WorkerSettings.job_timeout == 300


def test_worker_settings_redis_settings_from_config():
    from app.worker import WorkerSettings

    # RedisSettings should be constructed from the configured REDIS_URL
    rs = WorkerSettings.redis_settings
    assert rs is not None


def test_worker_settings_lifecycle_hooks():
    from app.worker import WorkerSettings, shutdown, startup

    assert WorkerSettings.on_startup is startup
    assert WorkerSettings.on_shutdown is shutdown


# ---------------------------------------------------------------------------
# Webhook enqueue integration — verify enqueue_job is called
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_webhook_enqueues_process_message(monkeypatch):
    """Accepted messages must be enqueued with the 'process_message' task name."""
    import httpx
    import fakeredis.aioredis
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
    from unittest.mock import AsyncMock

    import app.db.models  # noqa: F401
    from app.db.database import Base
    from app.main import app
    from app.services.bridge_service import bridge

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

    bridge._client = httpx.AsyncClient(
        base_url="https://bridge.test",
        transport=httpx.MockTransport(lambda r: httpx.Response(200)),
    )

    mock_pool = AsyncMock()
    mock_pool.enqueue_job = AsyncMock()
    app.state.arq_pool = mock_pool

    try:
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            r = await client.post(
                "/webhook/agent",
                json={
                    "body": {
                        "messageId": "enqueue-test-001",
                        "groupId": "group-1@g.us",
                        "sender": "972501234567@s.whatsapp.net",
                        "type": "message",
                        "messageText": "test",
                    }
                },
                headers={"X-Webhook-Secret": "test-secret"},
            )
    finally:
        db_module._session_factory = original_factory
        await engine.dispose()
        await fake_redis.aclose()
        bridge._client = None

    assert r.status_code == 200
    assert r.json()["status"] == "accepted"
    mock_pool.enqueue_job.assert_called_once_with("process_message", mock_pool.enqueue_job.call_args[0][1])
    task_name = mock_pool.enqueue_job.call_args[0][0]
    assert task_name == "process_message"
