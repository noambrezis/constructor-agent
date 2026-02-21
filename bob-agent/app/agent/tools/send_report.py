from typing import Annotated

from langchain_core.tools import tool
from langgraph.prebuilt import InjectedState

from app.db.database import get_db_session
from app.db.repositories import defect_repo
from app.services.bridge_service import bridge
from app.services.site_cache import site_cache
from app.utils.formatting import filter_defects, format_defect_row


@tool
async def send_whatsapp_report(
    status_filter: str = "",
    description_filter: str = "",
    supplier_filter: str = "",
    defect_id_filter: str = "",
    group_id: Annotated[str, InjectedState("group_id")] = "",
) -> str:
    """Send a filtered defect list as WhatsApp messages."""
    site = await site_cache.get(group_id)
    if site is None:
        return "Error: site not found."

    async with get_db_session() as session:
        all_defects = await defect_repo.get_all_for_site(session, site.id)

    filtered = filter_defects(
        all_defects,
        status_filter=status_filter,
        description_filter=description_filter,
        supplier_filter=supplier_filter,
        defect_id_filter=defect_id_filter,
    )

    if not filtered:
        await bridge.send_message(group_id, "לא נמצאו ליקויים התואמים לחיפוש.")
        return "No defects matched."

    lines = [format_defect_row(d) for d in filtered]
    batches = [lines[i : i + 20] for i in range(0, len(lines), 20)]
    await bridge.send_messages(group_id, ["\n".join(b) for b in batches])
    return f"Sent {len(filtered)} defects."


@tool
async def send_pdf_report(
    status_filter: str = "",
    description_filter: str = "",
    supplier_filter: str = "",
    group_id: Annotated[str, InjectedState("group_id")] = "",
) -> str:
    """Generate and send a PDF defect report. (PDF generation implemented in M9.)"""
    # M9: pdf_service.generate() + bridge.send_document()
    return "PDF report generation coming soon (M9)."
