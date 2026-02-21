"""Unit tests for app/services/pdf_service.py."""

from unittest.mock import AsyncMock, patch

import httpx
import pytest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

DOC_ID = "doc-abc123"
DOWNLOAD_URL = "https://cdn.pdfmonkey.io/reports/report.pdf"
TEMPLATE_DATA = {"site_name": "אתר א", "defects": []}


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
async def test_generate_happy_path():
    """Submit → single poll (success) → return download URL."""
    from app.services.pdf_service import generate

    responses = [
        _response(200, {"document_generation": {"id": DOC_ID}}),           # POST
        _response(200, {"document_generation": {"status": "success",       # GET poll
                                                 "download_url": DOWNLOAD_URL}}),
    ]

    with (
        patch("app.services.pdf_service.asyncio.sleep", new_callable=AsyncMock),
        patch(
            "httpx.AsyncClient",
            return_value=httpx.AsyncClient(transport=_make_transport(responses)),
        ),
    ):
        url = await generate(TEMPLATE_DATA)

    assert url == DOWNLOAD_URL


@pytest.mark.asyncio
async def test_generate_polls_until_success():
    """Should keep polling while status is 'generating'."""
    from app.services.pdf_service import generate

    responses = [
        _response(200, {"document_generation": {"id": DOC_ID}}),
        _response(200, {"document_generation": {"status": "generating"}}),
        _response(200, {"document_generation": {"status": "generating"}}),
        _response(200, {"document_generation": {"status": "success",
                                                 "download_url": DOWNLOAD_URL}}),
    ]

    with (
        patch("app.services.pdf_service.asyncio.sleep", new_callable=AsyncMock),
        patch(
            "httpx.AsyncClient",
            return_value=httpx.AsyncClient(transport=_make_transport(responses)),
        ),
    ):
        url = await generate(TEMPLATE_DATA)

    assert url == DOWNLOAD_URL


# ---------------------------------------------------------------------------
# Error status
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_generate_raises_on_error_status():
    """RuntimeError must be raised if PDFMonkey reports status='error'."""
    from app.services.pdf_service import generate

    responses = [
        _response(200, {"document_generation": {"id": DOC_ID}}),
        _response(200, {"document_generation": {"status": "error",
                                                 "errors": "template not found"}}),
    ]

    with (
        patch("app.services.pdf_service.asyncio.sleep", new_callable=AsyncMock),
        patch(
            "httpx.AsyncClient",
            return_value=httpx.AsyncClient(transport=_make_transport(responses)),
        ),
    ):
        with pytest.raises(RuntimeError, match="failed"):
            await generate(TEMPLATE_DATA)


# ---------------------------------------------------------------------------
# Timeout
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_generate_raises_timeout_when_never_succeeds():
    """TimeoutError must be raised if PDF never reaches 'success'."""
    from app.services.pdf_service import generate

    poll_count = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal poll_count
        if request.method == "POST":
            return _response(200, {"document_generation": {"id": DOC_ID}})
        poll_count += 1
        return _response(200, {"document_generation": {"status": "generating"}})

    with (
        patch("app.services.pdf_service.asyncio.sleep", new_callable=AsyncMock),
        patch("app.services.pdf_service.MAX_POLL_SECONDS", 3),
        patch(
            "httpx.AsyncClient",
            return_value=httpx.AsyncClient(transport=httpx.MockTransport(handler)),
        ),
    ):
        with pytest.raises(TimeoutError, match="timed out"):
            await generate(TEMPLATE_DATA)

    assert poll_count >= 1


# ---------------------------------------------------------------------------
# HTTP errors
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_generate_raises_on_submit_http_error():
    """HTTPStatusError on submit should propagate directly."""
    from app.services.pdf_service import generate

    responses = [_response(401, {"error": "Unauthorized"})]

    with (
        patch("app.services.pdf_service.asyncio.sleep", new_callable=AsyncMock),
        patch(
            "httpx.AsyncClient",
            return_value=httpx.AsyncClient(transport=_make_transport(responses)),
        ),
    ):
        with pytest.raises(httpx.HTTPStatusError):
            await generate(TEMPLATE_DATA)


# ---------------------------------------------------------------------------
# send_pdf_report tool — graph tool wrapping the service
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_send_pdf_report_calls_service_and_bridge():
    """Happy path: fetches defects, calls pdf_service.generate, sends document."""
    from unittest.mock import AsyncMock, MagicMock, patch

    from app.agent.tools.send_report import send_pdf_report
    from app.services.site_cache import CachedSite

    cached = CachedSite(
        id=1, group_id="group-1@g.us", name="אתר ראשון",
        logo_url="", training_phase="", context={},
    )
    defect = MagicMock()
    defect.defect_id = 1
    defect.description = "סדק בקיר"
    defect.supplier = "קבלן א"
    defect.location = "קומה 1"
    defect.status = "פתוח"
    defect.reporter = "ישראל"

    with (
        patch("app.agent.tools.send_report.site_cache.get", new_callable=AsyncMock, return_value=cached),
        patch("app.agent.tools.send_report.defect_repo.get_all_for_site", new_callable=AsyncMock, return_value=[defect]),
        patch("app.agent.tools.send_report.get_db_session") as mock_ctx,
        patch("app.services.pdf_service.generate", new_callable=AsyncMock, return_value="https://cdn.example.com/report.pdf") as mock_gen,
        patch("app.agent.tools.send_report.bridge.send_document", new_callable=AsyncMock) as mock_doc,
    ):
        mock_session = AsyncMock()
        mock_ctx.return_value.__aenter__ = AsyncMock(return_value=mock_session)
        mock_ctx.return_value.__aexit__ = AsyncMock(return_value=False)

        result = await send_pdf_report.ainvoke({"group_id": "group-1@g.us"})

    mock_gen.assert_called_once()
    mock_doc.assert_called_once()
    assert "1" in result  # 1 defect


@pytest.mark.asyncio
async def test_send_pdf_report_no_defects():
    """When no defects match filter, sends a message and returns early."""
    from app.agent.tools.send_report import send_pdf_report
    from app.services.site_cache import CachedSite

    cached = CachedSite(
        id=1, group_id="group-1@g.us", name="אתר ראשון",
        logo_url="", training_phase="", context={},
    )

    with (
        patch("app.agent.tools.send_report.site_cache.get", new_callable=AsyncMock, return_value=cached),
        patch("app.agent.tools.send_report.defect_repo.get_all_for_site", new_callable=AsyncMock, return_value=[]),
        patch("app.agent.tools.send_report.get_db_session") as mock_ctx,
        patch("app.services.pdf_service.generate", new_callable=AsyncMock) as mock_gen,
        patch("app.agent.tools.send_report.bridge.send_message", new_callable=AsyncMock) as mock_msg,
    ):
        mock_session = AsyncMock()
        mock_ctx.return_value.__aenter__ = AsyncMock(return_value=mock_session)
        mock_ctx.return_value.__aexit__ = AsyncMock(return_value=False)

        result = await send_pdf_report.ainvoke({"group_id": "group-1@g.us"})

    mock_gen.assert_not_called()
    mock_msg.assert_called_once()
    assert "No defects" in result


@pytest.mark.asyncio
async def test_send_pdf_report_pdf_error_returns_message():
    """RuntimeError from pdf_service returns Hebrew error string (no re-raise)."""
    from app.agent.tools.send_report import send_pdf_report
    from app.services.site_cache import CachedSite

    cached = CachedSite(
        id=1, group_id="group-1@g.us", name="אתר ראשון",
        logo_url="", training_phase="", context={},
    )
    defect = MagicMock()
    defect.defect_id = 1
    defect.description = "סדק"
    defect.supplier = ""
    defect.location = ""
    defect.status = "פתוח"
    defect.reporter = ""

    with (
        patch("app.agent.tools.send_report.site_cache.get", new_callable=AsyncMock, return_value=cached),
        patch("app.agent.tools.send_report.defect_repo.get_all_for_site", new_callable=AsyncMock, return_value=[defect]),
        patch("app.agent.tools.send_report.get_db_session") as mock_ctx,
        patch("app.services.pdf_service.generate", new_callable=AsyncMock, side_effect=RuntimeError("template error")) as mock_gen,
        patch("app.agent.tools.send_report.bridge.send_document", new_callable=AsyncMock) as mock_doc,
    ):
        mock_session = AsyncMock()
        mock_ctx.return_value.__aenter__ = AsyncMock(return_value=mock_session)
        mock_ctx.return_value.__aexit__ = AsyncMock(return_value=False)

        result = await send_pdf_report.ainvoke({"group_id": "group-1@g.us"})

    mock_gen.assert_called_once()
    mock_doc.assert_not_called()
    assert "שגיאה" in result


from unittest.mock import MagicMock
