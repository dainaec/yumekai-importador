"""Register only supported Excel formats here; review/web providers stay separate."""
from yumekai_importer.importers.norma.excel import NORMA_PROFILE
from yumekai_importer.importers.sd.excel import SD_PROFILE


EXCEL_PROFILES = {
    "sd": SD_PROFILE,
    "norma": NORMA_PROFILE,
}
