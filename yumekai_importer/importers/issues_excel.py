"""Lossless review exports for rows with import issues, including rejected rows."""

from collections import defaultdict
from dataclasses import fields
from decimal import Decimal
from enum import Enum
from pathlib import Path
from tempfile import NamedTemporaryFile

from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter

from yumekai_importer.catalog.product import Product
from yumekai_importer.importers.import_result import ImportResult


def _append(sheet, values) -> None:
    converted = []
    for value in values:
        if isinstance(value, Enum):
            value = value.value
        if isinstance(value, Decimal):
            value = str(value)
        elif isinstance(value, (tuple, list)):
            value = " | ".join(str(item) for item in value)
        converted.append(value)
    sheet.append(converted)
    for cell in sheet[sheet.max_row]:
        if isinstance(cell.value, str):
            # Titles, ISBNs and descriptions must stay literal Excel text.
            cell.data_type = "s"


def export_import_issues(result: ImportResult, path: str | Path) -> int:
    """Write one original row per affected Excel row; return the row count.

    The first sheet retains the source headers so it can be corrected and
    imported again with the same SD/Norma reader. Completed product data and
    individual issue messages are kept on separate sheets.
    """
    issues_by_row = defaultdict(list)
    for issue in result.issues:
        issues_by_row[issue.row].append(issue)
    if not issues_by_row:
        raise ValueError("No hay incidencias para exportar.")

    row_numbers = sorted(issues_by_row)
    headers = list(dict.fromkeys(
        key for row in row_numbers for key in result.source_rows.get(row, {})
    ))
    if not headers:
        raise ValueError("No se conservan los datos originales de estas incidencias.")

    book = Workbook()
    original = book.active
    original.title = "Revisar"
    _append(original, [*headers, "Fila original", "Situación en la carga", "Incidencias"])
    for row in row_numbers:
        source = result.source_rows.get(row, {})
        eligible = row in result.products_by_row
        _append(original, [
            *(source.get(header) for header in headers),
            row,
            "Incluida en la carga; comprobar guardado" if eligible else "Descartada; no enviada a BD",
            " | ".join(f"{i.field}: {i.message}" for i in issues_by_row[row]),
        ])

    completed = book.create_sheet("Datos completados")
    product_fields = [field.name for field in fields(Product)]
    _append(completed, ["Fila original", *product_fields])
    for row in row_numbers:
        product = result.products_by_row.get(row)
        if product is not None:
            _append(completed, [row, *(getattr(product, name) for name in product_fields)])

    issues = book.create_sheet("Incidencias")
    _append(issues, ["Fila original", "Título", "Campo", "Incidencia"])
    for issue in result.issues:
        _append(issues, [issue.row, issue.title, issue.field, issue.message])

    for sheet in book:
        sheet.freeze_panes = "A2"
        sheet.auto_filter.ref = sheet.dimensions
        for cell in sheet[1]:
            cell.fill = PatternFill("solid", fgColor="355E50")
            cell.font = Font(color="FFFFFF", bold=True)
        for index, column in enumerate(sheet.iter_cols(), start=1):
            width = max(len(str(cell.value or "")) for cell in column[:101]) + 2
            sheet.column_dimensions[get_column_letter(index)].width = min(60, max(14, width))
        for cells in sheet.iter_rows(min_row=2):
            for cell in cells:
                cell.alignment = Alignment(vertical="top", wrap_text=True)

    destination = Path(path)
    temporary = None
    try:
        with NamedTemporaryFile(dir=destination.parent, suffix=".xlsx", delete=False) as temp:
            temporary = Path(temp.name)
        book.save(temporary)
        temporary.replace(destination)
    finally:
        book.close()
        if temporary is not None:
            temporary.unlink(missing_ok=True)
    return len(row_numbers)
