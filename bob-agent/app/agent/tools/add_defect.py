from typing import Annotated

from langchain_core.tools import tool
from langgraph.prebuilt import InjectedState

from app.db.database import get_db_session
from app.db.repositories import defect_repo
from app.services.bridge_service import bridge
from app.services.site_cache import site_cache
from app.utils.formatting import format_defect_row


@tool
async def add_defect(
    description: str,
    supplier: str = "",
    location: str = "",
    image: str = "",
    group_id: Annotated[str, InjectedState("group_id")] = "",
    sender: Annotated[str, InjectedState("sender")] = "",
) -> str:
    """Log a new site defect record."""
    site = await site_cache.get(group_id)
    if site is None:
        return "Error: site not found for this group."

    async with get_db_session() as session:
        async with session.begin():
            next_id = await defect_repo.get_next_defect_id(session, site.id)
            defect = await defect_repo.create(
                session,
                defect_id=next_id,
                site_id=site.id,
                description=description,
                reporter=sender,
                supplier=supplier,
                location=location,
                image_url=image,
                status="פתוח",
            )

    formatted = format_defect_row(defect)
    await bridge.send_message(group_id, f"*ליקוי התווסף בהצלחה*\n{formatted}")

    # Show the updated defect list
    async with get_db_session() as session:
        all_defects = await defect_repo.get_all_for_site(session, site.id)

    lines = [format_defect_row(d) for d in all_defects]
    batches = [lines[i : i + 20] for i in range(0, len(lines), 20)]
    await bridge.send_messages(group_id, ["\n".join(b) for b in batches])

    return f"Defect #{next_id} added successfully."
