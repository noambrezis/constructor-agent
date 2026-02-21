from app.db.models import Defect


def format_defect_row(defect: Defect) -> str:
    """Format a defect as a single WhatsApp text line."""
    parts = [f"#{defect.defect_id}"]
    if defect.location:
        parts.append(defect.location)
    if defect.supplier:
        parts.append(defect.supplier)
    parts.append(defect.description)
    parts.append(f"[{defect.status}]")
    return " | ".join(parts)


def parse_id_filter(filter_str: str) -> set[int]:
    """Parse "77-90" → {77,78,...,90}  or "5,7,12" → {5,7,12}."""
    filter_str = filter_str.strip()
    if "-" in filter_str:
        lo, hi = filter_str.split("-", 1)
        return set(range(int(lo.strip()), int(hi.strip()) + 1))
    return {int(x.strip()) for x in filter_str.split(",") if x.strip()}


def filter_defects(
    defects: list[Defect],
    status_filter: str = "",
    description_filter: str = "",
    supplier_filter: str = "",
    defect_id_filter: str = "",
) -> list[Defect]:
    result = list(defects)

    if status_filter:
        result = [d for d in result if d.status == status_filter]

    if description_filter:
        result = [d for d in result if description_filter.lower() in d.description.lower()]

    if supplier_filter:
        result = [d for d in result if d.supplier == supplier_filter]

    if defect_id_filter:
        ids = parse_id_filter(defect_id_filter)
        result = [d for d in result if d.defect_id in ids]

    return result
