from typing import Annotated

from langchain_core.tools import tool
from langgraph.prebuilt import InjectedState

from app.db.database import get_db_session
from app.db.repositories import defect_repo
from app.services.bridge_service import bridge
from app.services.site_cache import site_cache
from app.utils.formatting import filter_defects, format_defect_row


@tool
async def update_defect(
    defect_id: int,
    description: str = "",
    supplier: str = "",
    location: str = "",
    image: str = "",
    status: str = "",
    group_id: Annotated[str, InjectedState("group_id")] = "",
) -> str:
    """Update one or more fields of an existing defect."""
    site = await site_cache.get(group_id)
    if site is None:
        return "Error: site not found for this group."

    kwargs: dict = {}
    if description:
        kwargs["description"] = description
    if supplier:
        kwargs["supplier"] = supplier
    if location:
        kwargs["location"] = location
    if image:
        kwargs["image_url"] = image
    if status:
        kwargs["status"] = status

    async with get_db_session() as session:
        async with session.begin():
            updated = await defect_repo.update(session, site.id, defect_id, **kwargs)

    if updated is None:
        return f"Error: defect #{defect_id} not found."

    await bridge.send_message(group_id, "ליקוי עודכן בהצלחה")

    # Show the updated defect
    async with get_db_session() as session:
        all_defects = await defect_repo.get_all_for_site(session, site.id)

    filtered = filter_defects(all_defects, defect_id_filter=str(defect_id))
    if filtered:
        await bridge.send_message(group_id, format_defect_row(filtered[0]))

    return f"Defect #{defect_id} updated."
