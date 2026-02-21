"""Unit tests for M3 — BridgeClient.

Uses httpx.MockTransport so no real network calls are made.
"""

import pytest
import httpx
from unittest.mock import AsyncMock, patch

from app.services.bridge_service import BridgeClient


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_transport(status_code: int = 200, body: bytes = b'{"ok":true}') -> httpx.MockTransport:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(status_code, content=body)
    return httpx.MockTransport(handler)


def _error_transport(status_code: int = 500) -> httpx.MockTransport:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(status_code)
    return httpx.MockTransport(handler)


async def _started_client(transport: httpx.MockTransport) -> BridgeClient:
    """Return a BridgeClient with a mock transport already initialised."""
    bc = BridgeClient()
    bc._client = httpx.AsyncClient(
        base_url="https://bridge.test",
        transport=transport,
    )
    return bc


# ---------------------------------------------------------------------------
# Lifecycle tests
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_startup_creates_client():
    bc = BridgeClient()
    assert bc._client is None
    await bc.startup()
    assert bc._client is not None
    await bc.shutdown()


@pytest.mark.asyncio
async def test_shutdown_clears_client():
    bc = BridgeClient()
    await bc.startup()
    await bc.shutdown()
    assert bc._client is None


@pytest.mark.asyncio
async def test_client_property_raises_before_startup():
    bc = BridgeClient()
    with pytest.raises(RuntimeError, match="not initialized"):
        _ = bc.client


# ---------------------------------------------------------------------------
# send_message
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_send_message_posts_correct_payload():
    captured = []

    def handler(request: httpx.Request) -> httpx.Response:
        captured.append(request)
        return httpx.Response(200)

    bc = await _started_client(httpx.MockTransport(handler))
    await bc.send_message("group-1@g.us", "שלום")

    assert len(captured) == 1
    assert captured[0].url.path == "/send-message"
    import json
    body = json.loads(captured[0].content)
    assert body == {"groupId": "group-1@g.us", "message": "שלום"}


@pytest.mark.asyncio
async def test_send_message_raises_on_http_error():
    bc = await _started_client(_error_transport(500))
    # Patch asyncio.sleep so tenacity's wait_exponential doesn't actually sleep
    with patch("asyncio.sleep", new_callable=AsyncMock):
        with pytest.raises(httpx.HTTPStatusError):
            await bc.send_message("group-1@g.us", "test")


# ---------------------------------------------------------------------------
# send_messages
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_send_messages_posts_list():
    captured = []

    def handler(request: httpx.Request) -> httpx.Response:
        captured.append(request)
        return httpx.Response(200)

    bc = await _started_client(httpx.MockTransport(handler))
    await bc.send_messages("group-1@g.us", ["msg1", "msg2"])

    import json
    body = json.loads(captured[0].content)
    assert body["messages"] == ["msg1", "msg2"]


# ---------------------------------------------------------------------------
# confirm_processing
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_confirm_processing_posts_message_id():
    captured = []

    def handler(request: httpx.Request) -> httpx.Response:
        captured.append(request)
        return httpx.Response(200)

    bc = await _started_client(httpx.MockTransport(handler))
    await bc.confirm_processing("msg-abc-123")

    import json
    body = json.loads(captured[0].content)
    assert body == {"messageId": "msg-abc-123"}
    assert captured[0].url.path == "/confirm-processing"


# ---------------------------------------------------------------------------
# send_document
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_send_document_posts_correct_payload():
    captured = []

    def handler(request: httpx.Request) -> httpx.Response:
        captured.append(request)
        return httpx.Response(200)

    bc = await _started_client(httpx.MockTransport(handler))
    await bc.send_document("group-1@g.us", "https://example.com/doc.pdf", "report.pdf", "הדוח")

    import json
    body = json.loads(captured[0].content)
    assert body["documentUrl"] == "https://example.com/doc.pdf"
    assert body["filename"] == "report.pdf"
    assert body["caption"] == "הדוח"
