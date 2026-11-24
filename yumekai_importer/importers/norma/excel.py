from contextlib import closing
from pathlib import Path

from openpyxl import load_workbook

from yumekai_importer.importers.excel_values import normalize_isbn
from yumekai_importer.importers.import_result import ImportResult


REQUIRED_HEADERS = {"ISBN", "TÍTULO", "AUTORÍA", "PVP"}


def _find_table(book):
    for sheet in book.worksheets:
        rows = sheet.iter_rows(values_only=True)
        for row_number, row in enumerate(rows, start=1):
            headers = tuple(str(value or "").strip().upper() for value in row)
            if REQUIRED_HEADERS.issubset(headers):
                return headers, rows, row_number

    raise ValueError("No se encontraron las columnas ISBN, TÍTULO, AUTORÍA y PVP.")


def read_norma_excel(path: str | Path) -> ImportResult:
    result = ImportResult()

    with closing(load_workbook(path, read_only=True, data_only=True)) as book:
        headers, rows, header_row = _find_table(book)

        for row_number, row in enumerate(rows, start=header_row + 1):
            data = dict(zip(headers, row))
            has_details = any(
                data.get(field) not in (None, "")
                for field in ("TÍTULO", "AUTORÍA", "PVP", "SINOPSIS")
            )
            if not has_details and normalize_isbn(data["ISBN"]) is None:
                continue

            result.add_row(
                row_number,
                isbn_value=data["ISBN"],
                title_value=data["TÍTULO"],
                price_value=data["PVP"],
                author=data["AUTORÍA"] or None,
                publisher="Norma Editorial",
                description=data.get("SINOPSIS"),
                source_data=data,
            )

    result.finalize_title_inferences()
    return result
