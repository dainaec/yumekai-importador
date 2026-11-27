"""One Excel reader for all registered suppliers, with supplier-specific profiles."""
from contextlib import closing
from pathlib import Path

from openpyxl import load_workbook

from yumekai_importer.importers.excel_profile import FIELD_LABELS, header_key, text
from yumekai_importer.importers.excel_profiles import EXCEL_PROFILES
from yumekai_importer.importers.import_result import ImportIssue, ImportResult


def _find_table(book, profiles):
    best_missing = {"ISBN", "TITULO", "PVP"}
    mappings = [(profile, profile.header_fields()) for profile in profiles]
    sheets = [book.active] + [sheet for sheet in book.worksheets if sheet is not book.active]
    for sheet in sheets:
        rows = sheet.iter_rows(values_only=True)
        for row_number, row in enumerate(rows, start=1):
            headers = tuple(text(value) or "" for value in row)
            candidates = []
            for profile, mapping in mappings:
                fields = tuple(mapping.get(header_key(value)) for value in row)
                missing = profile.required_fields - set(fields)
                if len(missing) < len(best_missing):
                    best_missing = missing
                if not missing:
                    candidates.append(profile)
            if candidates:
                return headers, list(rows), row_number, candidates
    names = ", ".join(FIELD_LABELS.get(field, field) for field in sorted(best_missing))
    raise ValueError(f"No se encontró una tabla de catálogo. Faltan columnas: {names}. "
                     "Se admiten variantes como Titulo/Título y Autor/Autoría. "
                     "La columna Precio no sustituye al PVP salvo que un perfil lo defina expresamente.")


def _positions(headers, profile):
    mapping = profile.header_fields()
    positions = {}
    for index, header in enumerate(headers):
        field = mapping.get(header_key(header))
        if field is None:
            continue
        if field in positions:
            first = headers[positions[field]]
            raise ValueError(f"Las columnas {first!r} y {header!r} corresponden "
                             "al mismo campo. Deja una sola columna para ese dato.")
        positions[field] = index
    return positions


def _select_profile(headers, rows, candidates, profiles, supplier):
    distributor_positions = set()
    for profile in profiles:
        mapping = profile.header_fields()
        distributor_positions.update(index for index, header in enumerate(headers)
                                     if mapping.get(header_key(header)) == "DISTRIBUIDOR")
    found = set()
    has_distributor = False
    for row in rows:
        for index in distributor_positions:
            value = row[index] if index < len(row) else None
            has_distributor = has_distributor or bool(text(value))
            found.update(profile.code for profile in profiles if profile.matches_distributor(value))
    if len(found) > 1:
        if found == {"sd", "norma"}:
            names = "SD y de Norma"
        else:
            names = " y de ".join(EXCEL_PROFILES[code].name for code in sorted(found))
        raise ValueError(f"El Excel contiene filas de {names}. "
                         "Carga el catálogo de cada distribuidor en un archivo separado.")
    if supplier is not None:
        profile = EXCEL_PROFILES[supplier]
        if found and found != {supplier}:
            raise ValueError(f"El Excel indica otro distribuidor; no se puede cargar como {profile.name}.")
    elif found:
        profile = EXCEL_PROFILES[next(iter(found))]
    else:
        hints = [candidate for candidate in candidates if not has_distributor
                 and candidate.matches_headers is not None and candidate.matches_headers(headers)]
        if len(hints) > 1:
            raise ValueError("Las columnas coinciden con varios distribuidores. Indica el perfil del Excel.")
        defaults = [candidate for candidate in candidates if candidate.legacy_default]
        if hints:
            profile = hints[0]
        elif len(candidates) == 1:
            profile = candidates[0]
        elif len(defaults) == 1:
            # Preserve legacy SD files without a distributor marker, including DIRAC catalogues.
            profile = defaults[0]
        else:
            raise ValueError("No se pudo identificar el distribuidor del Excel.")
    if profile not in candidates:
        raise ValueError(f"Faltan columnas necesarias para el Excel de {profile.name}.")
    return profile


def _read_rows(headers, rows, header_row, profile):
    positions = _positions(headers, profile)
    result = ImportResult()
    for row_number, row in enumerate(rows, start=header_row + 1):
        empty = all(text(value) is None for value in row) if profile.strip_details else all(value is None or value == "" for value in row)
        if empty:
            continue
        data = {field: row[index] if index < len(row) else None for field, index in positions.items()}
        image_url, image_issue = profile.read_image(data.get("IMAGEN")) if profile.read_image else (None, None)
        details = {field: text(data.get(field)) if profile.strip_details else data.get(field)
                   for field in ("AUTOR", "EDITORIAL", "SINOPSIS")}
        publisher = details["EDITORIAL"]
        if not publisher and profile.default_publisher is not None:
            publisher = profile.default_publisher
        result.add_row(
            row_number, isbn_value=data.get("ISBN"), title_value=data.get("TITULO"), price_value=data.get("PVP"),
            author=details["AUTOR"], publisher=publisher, description=details["SINOPSIS"],
            sd_reference=data.get(profile.reference_field) if profile.reference_field else None,
            image_url=image_url, source_data=dict(zip(headers, row)),
        )
        if profile.apply_row:
            profile.apply_row(result, row_number, data)
        if image_issue:
            product = result.products_by_row.get(row_number)
            title = product.title if product is not None else (text(data.get("TITULO")) or "")
            result.issues.append(ImportIssue(row_number, title, "Imagen", image_issue))
    result.finalize_title_inferences()
    return result


def read_catalog_excel_with_supplier(path: str | Path, *, supplier: str | None = None) -> tuple[str, ImportResult]:
    """Detect a registered profile, or use an explicit profile for compatibility."""
    if supplier is not None and supplier not in EXCEL_PROFILES:
        raise ValueError(f"Perfil de importación no registrado: {supplier!r}.")
    profiles = tuple(EXCEL_PROFILES.values())
    if not profiles:
        raise ValueError("No hay perfiles de importación registrados.")
    if len({profile.code for profile in profiles}) != len(profiles):
        raise ValueError("Hay códigos de perfil de importación duplicados.")
    if any(code != profile.code for code, profile in EXCEL_PROFILES.items()):
        raise ValueError("La clave del registro debe coincidir con el código del perfil.")
    with closing(load_workbook(path, read_only=True, data_only=True)) as book:
        headers, rows, header_row, candidates = _find_table(book, profiles)
        profile = _select_profile(headers, rows, candidates, profiles, supplier)
        result = _read_rows(headers, rows, header_row, profile)
    return profile.code, result


def read_catalog_excel(path: str | Path, *, supplier: str | None = None) -> ImportResult:
    return read_catalog_excel_with_supplier(path, supplier=supplier)[1]
