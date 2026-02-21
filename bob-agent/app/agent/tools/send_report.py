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
    """Generate and send a PDF defect report via PDFMonkey."""
    from app.services import pdf_service

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
    )

    if not filtered:
        await bridge.send_message(group_id, "לא נמצאו ליקויים לדוח.")
        return "No defects matched."

    template_data = {
        "site_name": site.name,
        "defects": [
            {
                "defect_id": d.defect_id,
                "description": d.description,
                "supplier": d.supplier,
                "location": d.location,
                "status": d.status,
                "reporter": d.reporter,
            }
            for d in filtered
        ],
    }

    try:
        download_url = await pdf_service.generate(template_data)
    except (RuntimeError, TimeoutError) as exc:
        return f"שגיאה ביצירת הדוח: {exc}"

    await bridge.send_document(
        group_id,
        download_url,
        filename=f"report_{site.name}.pdf",
        caption=f"דוח ליקויים — {len(filtered)} ליקויים",
    )
    return f"PDF sent with {len(filtered)} defects."
