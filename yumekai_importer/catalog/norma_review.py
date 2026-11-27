"""Review Norma details and the explicitly confirmed ZonaLibros availability."""
from yumekai_importer.catalog.descriptions import format_description
from yumekai_importer.catalog.review_fields import supplier_price_changes
from yumekai_importer.catalog.book_formats import normalize_yumekai_format


LABELS = {"author": "autoría", "description": "sinopsis", "series": "colección", "volume": "tomo",
          "pages": "páginas", "book_format": "formato", "retail_price": "PVP",
          "sale_price": "rebajado", "image_url": "portada", "work_type": "tipo de obra",
          "demographic": "demografía", "yumekai_status": "estado Yumekai"}


def _empty(value):
    return value is None or str(value).strip().casefold() in {"", "-", "- -", "n/d"}


def norma_review_changes(product, result, *, stock_only=False):
    if result.status != "found" or result.details is None:
        return {}, result.message or "Sin consultar en Norma; datos anteriores conservados."
    details = result.details
    changes, notes = {}, []
    if stock_only:
        if details.availability is not None:
            if product.get("yumekai_status") != details.yumekai_status:
                changes["yumekai_status"] = details.yumekai_status
            notes.append("ZonaLibros: " + details.availability)
            if details.yumekai_status is None:
                notes.append("Estado sin equivalencia confirmada: Por comprobar. Revisar manualmente.")
        return changes, " · ".join(notes) or "Disponibilidad sin confirmar en ZonaLibros."
    for field in ("author", "description", "series", "volume", "pages", "image_url"):
        value = getattr(details, field)
        if not _empty(value) and value != product.get(field):
            changes[field] = value

    current_format = product.get("book_format")
    canonical_format = normalize_yumekai_format(current_format)
    candidate_format = normalize_yumekai_format(details.book_format)
    proposed_format = candidate_format or canonical_format
    if proposed_format and proposed_format != current_format:
        changes["book_format"] = proposed_format
    if details.format_note:
        notes.append(details.format_note)

    if details.availability is not None:
        if product.get("yumekai_status") != details.yumekai_status:
            changes["yumekai_status"] = details.yumekai_status
        notes.append("ZonaLibros: " + details.availability)
        if details.yumekai_status is None:
            notes.append("Estado sin equivalencia confirmada: Por comprobar. Revisar manualmente.")

    if details.work_type:
        current = str(product.get("work_type") or "").strip()
        if current != details.work_type:
            changes["work_type"] = details.work_type
    if details.classification_note:
        notes.append(details.classification_note)
    effective_type = changes.get("work_type", product.get("work_type"))
    if (str(effective_type or "").casefold() == "manga" and details.work_type not in {"Manhwa", "Manhua"}
            and details.demographic and details.demographic != product.get("demographic")):
        changes["demographic"] = details.demographic
    changes.update(supplier_price_changes(product, details.retail_price))
    formatted = format_description(changes.get("description", product.get("description")))
    if formatted.changed:
        changes["description"] = formatted.text
    if formatted.note:
        notes.append(formatted.note)
    changes = {field: value for field, value in changes.items() if value != product.get(field)}
    if details.availability is None:
        notes.append("Disponibilidad conservada según el Excel; la ficha pública no confirma stock.")
    missing = [label for field, label in LABELS.items() if field not in {"sale_price", "demographic"}
               and _empty(changes.get(field, product.get(field)))]
    if missing:
        notes.append("Por completar: " + ", ".join(missing))
    prefix = "Propone: " + ", ".join(LABELS[field] for field in changes) if changes else "Sin campos nuevos"
    return changes, " · ".join([prefix, *notes])
