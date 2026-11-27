"""Norma's Excel rules; workbook iteration belongs to catalog_excel."""
from pathlib import Path

from yumekai_importer.catalog.product import YumekaiStatus
from yumekai_importer.importers.excel_profile import ExcelProfile, label, text
from yumekai_importer.importers.import_result import ImportIssue, ImportResult


NORMA_STATUSES = {
    "NORMAL/DISPONBLE": YumekaiStatus.ON_DEMAND,
    "AGOTADO": YumekaiStatus.OUT_OF_STOCK,
    "EN REIMPRESION / PDTE.": None,
}
NORMA_INCIDENT_STATUSES = {"DESCATALOGADO", "CANCELADO", "SIN EXISTENCIAS INDEFINDAMENTE"}
YUMEKAI_STATUSES = {
    "INSTOCK": YumekaiStatus.IN_STOCK, "HAY EXISTENCIAS": YumekaiStatus.IN_STOCK,
    "OUTOFSTOCK": YumekaiStatus.OUT_OF_STOCK, "SIN EXISTENCIAS": YumekaiStatus.OUT_OF_STOCK,
    "SIN STOCK": YumekaiStatus.OUT_OF_STOCK,
    "YK_ON_DEMAND": YumekaiStatus.ON_DEMAND, "BAJO DEMANDA": YumekaiStatus.ON_DEMAND,
    "ONBACKORDER": YumekaiStatus.ON_BACKORDER, "SE PUEDE RESERVAR": YumekaiStatus.ON_BACKORDER,
    "POR COMPROBAR": None,
}


def _read_image(value: object) -> tuple[str | None, str | None]:
    image = text(value)
    if image is None or image in {".", "..", "-", "- -"}:
        return None, None
    if image.lower().startswith(("https://", "http://")):
        return image, None
    return None, (f"No se pudo obtener el enlace de la imagen {image!r}. "
                  "Indica una URL completa para la portada de Norma.")


def _apply_status(result: ImportResult, row_number: int, data: dict[str, object]) -> None:
    original = text(data.get("ESTADO"))
    status = label(original)
    product = result.products_by_row.get(row_number)
    if status in YUMEKAI_STATUSES:
        if product is not None:
            product.yumekai_status = YUMEKAI_STATUSES[status]
        return
    if product is not None:
        product.yumekai_status = NORMA_STATUSES.get(status)
    if status in NORMA_STATUSES:
        return
    if status in NORMA_INCIDENT_STATUSES:
        message = f"Estado de Norma: {original}. Requiere revisión manual."
    elif original:
        message = f"Estado de Norma no reconocido: {original!r}. Revisar."
    else:
        message = "Falta el estado de Norma. Requiere revisión manual."
    title = product.title if product is not None else (text(data.get("TITULO")) or "")
    result.issues.append(ImportIssue(row_number, title, "Estado", message))


def _legacy_headers(headers: tuple[str, ...]) -> bool:
    return "Titulo" not in headers and {"TÍTULO", "AUTORÍA"}.issubset({value.upper() for value in headers})


NORMA_PROFILE = ExcelProfile(
    code="norma", name="Norma Editorial", distributor_prefixes=("NORMA",),
    matches_headers=_legacy_headers, read_image=_read_image, apply_row=_apply_status,
    default_publisher="Norma Editorial",
)


def read_norma_excel(path: str | Path) -> ImportResult:
    """Compatibility entry point; uses the same reader as the Import Excel button."""
    from yumekai_importer.importers.catalog_excel import read_catalog_excel
    return read_catalog_excel(path, supplier="norma")
