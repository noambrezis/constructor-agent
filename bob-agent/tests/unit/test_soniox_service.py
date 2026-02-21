"""Unit tests for app/services/soniox_service.py."""

from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

FILE_ID = "soniox-file-abc123"
JOB_ID = "job-xyz789"
SITE_CONTEXT = {"locations": ["קומה 1", "קומה 2"], "suppliers": ["ספק א"]}


def _response(status_code: int, body: dict) -> httpx.Response:
    return httpx.Response(status_code, json=body)


def _make_transport(responses: list[httpx.Response]):
    """Return a MockTransport that serves responses in order."""
    responses_iter = iter(responses)

    def handler(request: httpx.Request) -> httpx.Response:
        return next(responses_iter)

    return httpx.MockTransport(handler)


# ---------------------------------------------------------------------------
# Happy path
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_transcribe_happy_path():
    """Submit → single poll (completed) → fetch transcript."""
    from app.services.soniox_service import transcribe

    responses = [
        _response(200, {"id": JOB_ID}),                          # POST /transcriptions
        _response(200, {"status": "completed"}),                  # GET /transcriptions/{id}
        _response(200, {"text": "יש סדק בקיר הצפוני"}),          # GET /transcriptions/{id}/transcript
    ]

    with (
        patch("app.services.soniox_service.asyncio.sleep", new_callable=AsyncMock),
        patch(
            "httpx.AsyncClient",
            return_value=httpx.AsyncClient(transport=_make_transport(responses)),
        ),
    ):
        result = await transcribe(FILE_ID, SITE_CONTEXT)

    assert result == "יש סדק בקיר הצפוני"


@pytest.mark.asyncio
async def test_transcribe_polls_until_completed():
    """Should keep polling while status is 'processing'."""
    from app.services.soniox_service import transcribe

    responses = [
        _response(200, {"id": JOB_ID}),                       # submit
        _response(200, {"status": "processing"}),              # poll 1
        _response(200, {"status": "processing"}),              # poll 2
        _response(200, {"status": "completed"}),               # poll 3
        _response(200, {"text": "נזילה מהתקרה"}),              # transcript
    ]

    with (
        patch("app.services.soniox_service.asyncio.sleep", new_callable=AsyncMock),
        patch(
            "httpx.AsyncClient",
            return_value=httpx.AsyncClient(transport=_make_transport(responses)),
        ),
    ):
        result = await transcribe(FILE_ID, SITE_CONTEXT)

    assert result == "נזילה מהתקרה"


@pytest.mark.asyncio
async def test_transcribe_empty_transcript():
    """Soniox may return empty text; service should return '' not raise."""
    from app.services.soniox_service import transcribe

    responses = [
        _response(200, {"id": JOB_ID}),
        _response(200, {"status": "completed"}),
        _response(200, {}),   # no "text" key
    ]

    with (
        patch("app.services.soniox_service.asyncio.sleep", new_callable=AsyncMock),
        patch(
            "httpx.AsyncClient",
            return_value=httpx.AsyncClient(transport=_make_transport(responses)),
        ),
    ):
        result = await transcribe(FILE_ID, SITE_CONTEXT)

    assert result == ""


@pytest.mark.asyncio
async def test_transcribe_includes_site_terms_in_request():
    """Site locations and suppliers should be sent as context terms."""
    from app.services.soniox_service import transcribe

    captured_requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        captured_requests.append(request)
        if request.method == "POST":
            return _response(200, {"id": JOB_ID})
        url = str(request.url)
        if url.endswith("/transcript"):
            return _response(200, {"text": "test"})
        return _response(200, {"status": "completed"})

    with (
        patch("app.services.soniox_service.asyncio.sleep", new_callable=AsyncMock),
        patch(
            "httpx.AsyncClient",
            return_value=httpx.AsyncClient(transport=httpx.MockTransport(handler)),
        ),
    ):
        await transcribe(FILE_ID, {"locations": ["לובי"], "suppliers": ["שיכון ובינוי"]})

    import json
    submit_body = json.loads(captured_requests[0].content)
    terms = submit_body["context"]["terms"]
    assert "לובי" in terms
    assert "שיכון ובינוי" in terms


# ---------------------------------------------------------------------------
# Timeout
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_transcribe_raises_timeout_when_never_completes():
    """TimeoutError must be raised if job never reaches 'completed'."""
    from app.services.soniox_service import transcribe

    poll_count = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal poll_count
        if request.method == "POST":
            return _response(200, {"id": JOB_ID})
        poll_count += 1
        return _response(200, {"status": "processing"})

    with (
        patch("app.services.soniox_service.asyncio.sleep", new_callable=AsyncMock),
        patch("app.services.soniox_service.settings") as mock_settings,
        patch(
            "httpx.AsyncClient",
            return_value=httpx.AsyncClient(transport=httpx.MockTransport(handler)),
        ),
    ):
        mock_settings.SONIOX_API_KEY = "test-key"
        mock_settings.STT_TIMEOUT_SECONDS = 3  # 3 polls

        with pytest.raises(TimeoutError, match="timed out"):
            await transcribe(FILE_ID, {})


# ---------------------------------------------------------------------------
# Failed status
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_transcribe_raises_on_failed_status():
    """RuntimeError should be raised if Soniox reports status='failed'."""
    from app.services.soniox_service import transcribe

    responses = [
        _response(200, {"id": JOB_ID}),
        _response(200, {"status": "failed"}),
    ]

    with (
        patch("app.services.soniox_service.asyncio.sleep", new_callable=AsyncMock),
        patch(
            "httpx.AsyncClient",
            return_value=httpx.AsyncClient(transport=_make_transport(responses)),
        ),
    ):
        with pytest.raises(RuntimeError, match="failed"):
            await transcribe(FILE_ID, {})


# ---------------------------------------------------------------------------
# HTTP errors
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_transcribe_raises_on_submit_http_error():
    """HTTPStatusError on submit should propagate directly."""
    from app.services.soniox_service import transcribe

    responses = [_response(401, {"error": "Unauthorized"})]

    with (
        patch("app.services.soniox_service.asyncio.sleep", new_callable=AsyncMock),
        patch(
            "httpx.AsyncClient",
            return_value=httpx.AsyncClient(transport=_make_transport(responses)),
        ),
    ):
        with pytest.raises(httpx.HTTPStatusError):
            await transcribe(FILE_ID, {})


# ---------------------------------------------------------------------------
# transcribe_node — graph node wrapping the service
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_transcribe_node_calls_service():
    from app.agent.graph import transcribe_node

    state = {
        "sonioxFileId": "file-001",
        "site": {"context": {"locations": ["קומה 1"], "suppliers": []}},
        "group_id": "G1",
    }

    with patch("app.agent.graph.soniox_service.transcribe", new_callable=AsyncMock, return_value="נזילה") as mock_t:
        result = await transcribe_node(state)

    mock_t.assert_called_once_with("file-001", {"locations": ["קומה 1"], "suppliers": []})
    assert result == {"transcript": "נזילה"}


@pytest.mark.asyncio
async def test_transcribe_node_skips_when_no_file_id():
    from app.agent.graph import transcribe_node

    state = {"sonioxFileId": None, "site": {}, "group_id": "G1"}

    with patch("app.agent.graph.soniox_service.transcribe", new_callable=AsyncMock) as mock_t:
        result = await transcribe_node(state)

    mock_t.assert_not_called()
    assert result == {}


@pytest.mark.asyncio
async def test_transcribe_node_returns_empty_on_timeout():
    from app.agent.graph import transcribe_node

    state = {"sonioxFileId": "file-001", "site": {}, "group_id": "G1"}

    with patch(
        "app.agent.graph.soniox_service.transcribe",
        new_callable=AsyncMock,
        side_effect=TimeoutError("timed out"),
    ):
        result = await transcribe_node(state)

    assert result == {"transcript": ""}


@pytest.mark.asyncio
async def test_transcribe_node_returns_empty_on_runtime_error():
    from app.agent.graph import transcribe_node

    state = {"sonioxFileId": "file-001", "site": {}, "group_id": "G1"}

    with patch(
        "app.agent.graph.soniox_service.transcribe",
        new_callable=AsyncMock,
        side_effect=RuntimeError("failed"),
    ):
        result = await transcribe_node(state)

    assert result == {"transcript": ""}


# ---------------------------------------------------------------------------
# route_preprocess routing
# ---------------------------------------------------------------------------


def test_route_preprocess_routes_audio_to_transcribe():
    from app.agent.graph import route_preprocess

    state = {"site": {"id": 1}, "sonioxFileId": "file-001"}
    assert route_preprocess(state) == "transcribe"


def test_route_preprocess_routes_text_to_build_input():
    from app.agent.graph import route_preprocess

    state = {"site": {"id": 1}, "sonioxFileId": None}
    assert route_preprocess(state) == "build_input"


def test_route_preprocess_routes_unknown_site_to_end():
    from langgraph.graph import END

    from app.agent.graph import route_preprocess

    state = {"site": {}, "sonioxFileId": None}
    assert route_preprocess(state) == END
