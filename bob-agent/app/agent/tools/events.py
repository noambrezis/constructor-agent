from typing import Annotated

from langchain_core.tools import tool
from langgraph.prebuilt import InjectedState

from app.db.database import get_db_session
from app.db.repositories import site_repo
from app.services.bridge_service import bridge
from app.services.site_cache import site_cache


@tool
async def add_event(
    description: str,
    time: str,
    group_id: Annotated[str, InjectedState("group_id")] = "",
) -> str:
    """Schedule a reminder or event to be sent to the WhatsApp group.

    Args:
        description: Event details in Hebrew.
        time: ISO 8601 datetime string (e.g. 2026-02-19T18:00:00).
    """
    await bridge.schedule_message(
        group_id=group_id,
        name=description,
        start_date=time,
    )
    return f"Event '{description}' scheduled for {time}."


@tool
async def update_logo(
    image_url: str,
    group_id: Annotated[str, InjectedState("group_id")] = "",
) -> str:
    """Update the site logo used in PDF reports."""
    async with get_db_session() as session:
        async with session.begin():
            updated = await site_repo.update(session, group_id, logo_url=image_url)
    if updated is None:
        return "Error: site not found."
    await site_cache.invalidate(group_id)
    return "Logo updated."
