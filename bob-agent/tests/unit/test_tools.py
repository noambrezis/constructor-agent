"""Unit tests for agent tools — all external deps are mocked."""

from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------


def _make_site(id=1, group_id="G1", name="Test Site"):
    site = MagicMock()
    site.id = id
    site.group_id = group_id
    site.name = name
    site.logo_url = ""
    site.context = {
        "suppliers": ["ספק א", "ספק ב"],
        "locations": ["קומה 1", "קומה 2"],
    }
    site.training_phase = "Active"
    return site


def _make_defect(defect_id=1, description="crack", supplier="ספק א", location="קומה 1", status="פתוח"):
    d = MagicMock()
    d.defect_id = defect_id
    d.description = description
    d.supplier = supplier
    d.location = location
    d.status = status
    d.image_url = ""
    return d


def _mock_session():
    """Return a mock AsyncSession whose .begin() is an async context manager."""
    session = AsyncMock()
    begin_cm = MagicMock()
    begin_cm.__aenter__ = AsyncMock(return_value=None)
    begin_cm.__aexit__ = AsyncMock(return_value=False)
    session.begin = MagicMock(return_value=begin_cm)
    return session


def _db_ctx(session):
    """Return an asynccontextmanager factory that always yields *session*."""

    @asynccontextmanager
    async def _inner():
        yield session

    return _inner


# ---------------------------------------------------------------------------
# add_defect
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_add_defect_site_not_found():
    from app.agent.tools.add_defect import add_defect

    session = _mock_session()

    with (
        patch("app.agent.tools.add_defect.get_db_session", _db_ctx(session)),
        patch("app.agent.tools.add_defect.site_repo") as mock_site_repo,
        patch("app.agent.tools.add_defect.defect_repo") as mock_defect_repo,
        patch("app.agent.tools.add_defect.bridge") as mock_bridge,
    ):
        mock_site_repo.get_by_group_id = AsyncMock(return_value=None)

        result = await add_defect.coroutine(
            description="crack",
            group_id="G1",
            sender="user1",
        )

    assert "Error" in result
    mock_defect_repo.create.assert_not_called()
    mock_bridge.send_message.assert_not_called()


@pytest.mark.asyncio
async def test_add_defect_success():
    from app.agent.tools.add_defect import add_defect

    site = _make_site()
    defect = _make_defect(defect_id=3)
    session = _mock_session()

    with (
        patch("app.agent.tools.add_defect.get_db_session", _db_ctx(session)),
        patch("app.agent.tools.add_defect.site_repo") as mock_site_repo,
        patch("app.agent.tools.add_defect.defect_repo") as mock_defect_repo,
        patch("app.agent.tools.add_defect.bridge") as mock_bridge,
    ):
        mock_site_repo.get_by_group_id = AsyncMock(return_value=site)
        mock_defect_repo.get_next_defect_id = AsyncMock(return_value=3)
        mock_defect_repo.create = AsyncMock(return_value=defect)
        mock_defect_repo.get_all_for_site = AsyncMock(return_value=[defect])
        mock_bridge.send_message = AsyncMock()
        mock_bridge.send_messages = AsyncMock()

        result = await add_defect.coroutine(
            description="crack in wall",
            supplier="ספק א",
            location="קומה 1",
            group_id="G1",
            sender="user1",
        )

    assert "3" in result
    mock_defect_repo.create.assert_called_once()
    mock_bridge.send_message.assert_called_once()
    mock_bridge.send_messages.assert_called_once()


@pytest.mark.asyncio
async def test_add_defect_calls_create_with_correct_fields():
    from app.agent.tools.add_defect import add_defect

    site = _make_site(id=7)
    defect = _make_defect(defect_id=1)
    session = _mock_session()

    with (
        patch("app.agent.tools.add_defect.get_db_session", _db_ctx(session)),
        patch("app.agent.tools.add_defect.site_repo") as mock_site_repo,
        patch("app.agent.tools.add_defect.defect_repo") as mock_defect_repo,
        patch("app.agent.tools.add_defect.bridge") as mock_bridge,
    ):
        mock_site_repo.get_by_group_id = AsyncMock(return_value=site)
        mock_defect_repo.get_next_defect_id = AsyncMock(return_value=1)
        mock_defect_repo.create = AsyncMock(return_value=defect)
        mock_defect_repo.get_all_for_site = AsyncMock(return_value=[defect])
        mock_bridge.send_message = AsyncMock()
        mock_bridge.send_messages = AsyncMock()

        await add_defect.coroutine(
            description="leaking pipe",
            supplier="ספק ב",
            location="קומה 2",
            group_id="G1",
            sender="alice",
        )

    call_kwargs = mock_defect_repo.create.call_args.kwargs
    assert call_kwargs["site_id"] == 7
    assert call_kwargs["description"] == "leaking pipe"
    assert call_kwargs["supplier"] == "ספק ב"
    assert call_kwargs["location"] == "קומה 2"
    assert call_kwargs["reporter"] == "alice"
    assert call_kwargs["status"] == "פתוח"


# ---------------------------------------------------------------------------
# update_defect
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_update_defect_site_not_found():
    from app.agent.tools.update_defect import update_defect

    session = _mock_session()

    with (
        patch("app.agent.tools.update_defect.get_db_session", _db_ctx(session)),
        patch("app.agent.tools.update_defect.site_repo") as mock_site_repo,
        patch("app.agent.tools.update_defect.defect_repo") as mock_defect_repo,
        patch("app.agent.tools.update_defect.bridge") as mock_bridge,
    ):
        mock_site_repo.get_by_group_id = AsyncMock(return_value=None)

        result = await update_defect.coroutine(defect_id=1, group_id="G1")

    assert "Error" in result
    mock_defect_repo.update.assert_not_called()
    mock_bridge.send_message.assert_not_called()


@pytest.mark.asyncio
async def test_update_defect_not_found():
    from app.agent.tools.update_defect import update_defect

    site = _make_site()
    session = _mock_session()

    with (
        patch("app.agent.tools.update_defect.get_db_session", _db_ctx(session)),
        patch("app.agent.tools.update_defect.site_repo") as mock_site_repo,
        patch("app.agent.tools.update_defect.defect_repo") as mock_defect_repo,
        patch("app.agent.tools.update_defect.bridge") as mock_bridge,
    ):
        mock_site_repo.get_by_group_id = AsyncMock(return_value=site)
        mock_defect_repo.update = AsyncMock(return_value=None)

        result = await update_defect.coroutine(defect_id=99, group_id="G1")

    assert "Error" in result
    assert "99" in result
    mock_bridge.send_message.assert_not_called()


@pytest.mark.asyncio
async def test_update_defect_success():
    from app.agent.tools.update_defect import update_defect

    site = _make_site()
    updated = _make_defect(defect_id=2, status="בעבודה")
    session = _mock_session()

    with (
        patch("app.agent.tools.update_defect.get_db_session", _db_ctx(session)),
        patch("app.agent.tools.update_defect.site_repo") as mock_site_repo,
        patch("app.agent.tools.update_defect.defect_repo") as mock_defect_repo,
        patch("app.agent.tools.update_defect.bridge") as mock_bridge,
    ):
        mock_site_repo.get_by_group_id = AsyncMock(return_value=site)
        mock_defect_repo.update = AsyncMock(return_value=updated)
        mock_defect_repo.get_all_for_site = AsyncMock(return_value=[updated])
        mock_bridge.send_message = AsyncMock()

        result = await update_defect.coroutine(defect_id=2, status="בעבודה", group_id="G1")

    assert "2" in result
    mock_bridge.send_message.assert_called()


@pytest.mark.asyncio
async def test_update_defect_only_updates_provided_fields():
    from app.agent.tools.update_defect import update_defect

    site = _make_site()
    updated = _make_defect(defect_id=1)
    session = _mock_session()

    with (
        patch("app.agent.tools.update_defect.get_db_session", _db_ctx(session)),
        patch("app.agent.tools.update_defect.site_repo") as mock_site_repo,
        patch("app.agent.tools.update_defect.defect_repo") as mock_defect_repo,
        patch("app.agent.tools.update_defect.bridge") as mock_bridge,
    ):
        mock_site_repo.get_by_group_id = AsyncMock(return_value=site)
        mock_defect_repo.update = AsyncMock(return_value=updated)
        mock_defect_repo.get_all_for_site = AsyncMock(return_value=[updated])
        mock_bridge.send_message = AsyncMock()

        # Only pass description — supplier/location/status should NOT appear in kwargs
        await update_defect.coroutine(defect_id=1, description="new description", group_id="G1")

    call_kwargs = mock_defect_repo.update.call_args.kwargs
    assert "description" in call_kwargs
    assert "supplier" not in call_kwargs
    assert "location" not in call_kwargs
    assert "status" not in call_kwargs


# ---------------------------------------------------------------------------
# send_whatsapp_report
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_send_whatsapp_report_no_match():
    from app.agent.tools.send_report import send_whatsapp_report

    site = _make_site()
    session = _mock_session()

    with (
        patch("app.agent.tools.send_report.get_db_session", _db_ctx(session)),
        patch("app.agent.tools.send_report.site_repo") as mock_site_repo,
        patch("app.agent.tools.send_report.defect_repo") as mock_defect_repo,
        patch("app.agent.tools.send_report.bridge") as mock_bridge,
    ):
        mock_site_repo.get_by_group_id = AsyncMock(return_value=site)
        mock_defect_repo.get_all_for_site = AsyncMock(return_value=[])
        mock_bridge.send_message = AsyncMock()
        mock_bridge.send_messages = AsyncMock()

        result = await send_whatsapp_report.coroutine(group_id="G1")

    assert "No defects matched" in result
    mock_bridge.send_message.assert_called_once()
    mock_bridge.send_messages.assert_not_called()


@pytest.mark.asyncio
async def test_send_whatsapp_report_sends_filtered_results():
    from app.agent.tools.send_report import send_whatsapp_report

    site = _make_site()
    defects = [_make_defect(defect_id=i, status="פתוח") for i in range(1, 4)]
    session = _mock_session()

    with (
        patch("app.agent.tools.send_report.get_db_session", _db_ctx(session)),
        patch("app.agent.tools.send_report.site_repo") as mock_site_repo,
        patch("app.agent.tools.send_report.defect_repo") as mock_defect_repo,
        patch("app.agent.tools.send_report.bridge") as mock_bridge,
    ):
        mock_site_repo.get_by_group_id = AsyncMock(return_value=site)
        mock_defect_repo.get_all_for_site = AsyncMock(return_value=defects)
        mock_bridge.send_message = AsyncMock()
        mock_bridge.send_messages = AsyncMock()

        result = await send_whatsapp_report.coroutine(status_filter="פתוח", group_id="G1")

    assert "3" in result
    mock_bridge.send_messages.assert_called_once()


@pytest.mark.asyncio
async def test_send_whatsapp_report_site_not_found():
    from app.agent.tools.send_report import send_whatsapp_report

    session = _mock_session()

    with (
        patch("app.agent.tools.send_report.get_db_session", _db_ctx(session)),
        patch("app.agent.tools.send_report.site_repo") as mock_site_repo,
        patch("app.agent.tools.send_report.bridge") as mock_bridge,
    ):
        mock_site_repo.get_by_group_id = AsyncMock(return_value=None)

        result = await send_whatsapp_report.coroutine(group_id="G1")

    assert "Error" in result
    mock_bridge.send_message.assert_not_called()


@pytest.mark.asyncio
async def test_send_whatsapp_report_batches_large_lists():
    """More than 20 defects should be split into multiple batches."""
    from app.agent.tools.send_report import send_whatsapp_report

    site = _make_site()
    defects = [_make_defect(defect_id=i) for i in range(1, 45)]  # 44 defects → 3 batches
    session = _mock_session()

    with (
        patch("app.agent.tools.send_report.get_db_session", _db_ctx(session)),
        patch("app.agent.tools.send_report.site_repo") as mock_site_repo,
        patch("app.agent.tools.send_report.defect_repo") as mock_defect_repo,
        patch("app.agent.tools.send_report.bridge") as mock_bridge,
    ):
        mock_site_repo.get_by_group_id = AsyncMock(return_value=site)
        mock_defect_repo.get_all_for_site = AsyncMock(return_value=defects)
        mock_bridge.send_messages = AsyncMock()

        await send_whatsapp_report.coroutine(group_id="G1")

    batches_sent = mock_bridge.send_messages.call_args[0][1]
    assert len(batches_sent) == 3  # ceil(44/20) = 3


# ---------------------------------------------------------------------------
# add_event
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_add_event_calls_schedule_message():
    from app.agent.tools.events import add_event

    with patch("app.agent.tools.events.bridge") as mock_bridge:
        mock_bridge.schedule_message = AsyncMock()

        result = await add_event.coroutine(
            description="פגישת ביקורת",
            time="2026-03-01T10:00:00",
            group_id="G1",
        )

    mock_bridge.schedule_message.assert_called_once_with(
        group_id="G1",
        name="פגישת ביקורת",
        start_date="2026-03-01T10:00:00",
    )
    assert "פגישת ביקורת" in result


# ---------------------------------------------------------------------------
# update_logo
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_update_logo_success():
    from app.agent.tools.events import update_logo

    updated_site = MagicMock()
    updated_site.logo_url = "https://example.com/logo.png"
    session = _mock_session()

    with (
        patch("app.agent.tools.events.get_db_session", _db_ctx(session)),
        patch("app.agent.tools.events.site_repo") as mock_site_repo,
    ):
        mock_site_repo.update = AsyncMock(return_value=updated_site)

        result = await update_logo.coroutine(
            image_url="https://example.com/logo.png",
            group_id="G1",
        )

    assert "Logo updated" in result
    mock_site_repo.update.assert_called_once_with(
        session, "G1", logo_url="https://example.com/logo.png"
    )


@pytest.mark.asyncio
async def test_update_logo_site_not_found():
    from app.agent.tools.events import update_logo

    session = _mock_session()

    with (
        patch("app.agent.tools.events.get_db_session", _db_ctx(session)),
        patch("app.agent.tools.events.site_repo") as mock_site_repo,
    ):
        mock_site_repo.update = AsyncMock(return_value=None)

        result = await update_logo.coroutine(
            image_url="https://example.com/logo.png",
            group_id="UNKNOWN",
        )

    assert "Error" in result
