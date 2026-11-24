from contextlib import closing
from pathlib import Path
from urllib.parse import quote
from openpyxl import load_workbook
from yumekai_importer.importers.import_result import ImportResult


SD_IMAGE_BASE = "https://imagenes.zonalibros.com/img/58/"


def _sd_image_url(value: object) -> str | None:
    if not isinstance(value, str):
        return None

    filename = value.strip()
    if filename in {"", ".", "..", "-", "- -"} or "/" in filename or "\\" in filename:
        return None

    return SD_IMAGE_BASE + quote(filename, safe="")

def read_sd_excel(path: str | Path) -> ImportResult:
    result = ImportResult()

    with closing(load_workbook(path, read_only=True, data_only=True)) as book:
        rows = book.active.iter_rows(values_only=True)
        headers = tuple(str(value or "").strip() for value in next(rows, ()))
        missing = {"ISBN", "Titulo", "PVP"} - set(headers)
        if missing:
            raise ValueError(f"Faltan columnas de SD: {', '.join(sorted(missing))}")

        for row_number, row in enumerate(rows, start=2):
            if all(value is None or value == "" for value in row):
                continue

            data = dict(zip(headers, row))
            
            result.add_row(
                row_number,
                isbn_value=data["ISBN"],
                title_value=data["Titulo"],
                price_value=data["PVP"],
                author=data.get("Autor"),
                publisher=data.get("Editorial"),
                description=data.get("Sinopsis"),
                sd_reference=data.get("Ref"),
                image_url=_sd_image_url(data.get("Imagen")),
                source_data=data,
            )

    result.finalize_title_inferences()
    return result
