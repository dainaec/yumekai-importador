"""SD's Excel configuration and legacy entry point for the shared reader."""
from pathlib import Path
from urllib.parse import quote
from yumekai_importer.importers.excel_profile import ExcelProfile
from yumekai_importer.importers.import_result import ImportResult


SD_IMAGE_BASE = "https://imagenes.zonalibros.com/img/58/"


def _sd_image_url(value: object) -> str | None:
    if not isinstance(value, str):
        return None

    filename = value.strip()
    if filename in {"", ".", "..", "-", "- -"} or "/" in filename or "\\" in filename:
        return None

    return SD_IMAGE_BASE + quote(filename, safe="")

def _read_image(value: object) -> tuple[str | None, str | None]:
    return _sd_image_url(value), None


SD_PROFILE = ExcelProfile(
    code="sd", name="SD Distribuciones", distributor_aliases=("SD",),
    distributor_prefixes=("SDDISTRIBUCIONES",), read_image=_read_image,
    strip_details=False, reference_field="REF", legacy_default=True,
)


def read_sd_excel(path: str | Path) -> ImportResult:
    """Compatibility entry point; workbook reading is shared with other suppliers."""
    from yumekai_importer.importers.catalog_excel import read_catalog_excel
    return read_catalog_excel(path, supplier="sd")
