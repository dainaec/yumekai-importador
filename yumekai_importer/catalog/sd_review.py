"""Propose SD updates, using its format and preserving other reviewed data."""
from decimal import Decimal

from yumekai_importer.catalog.review_fields import normalize_price
from yumekai_importer.catalog.classification import canonical_demographic
from yumekai_importer.catalog.review_workflow import stock_code
from yumekai_importer.catalog.book_formats import normalize_sd_format
from yumekai_importer.catalog.descriptions import can_complete_description, description_may_be_shortened

FIELD_LABELS = {'work_type': 'tipo de obra', 'demographic': 'demografía', 'pages': 'páginas',
                'book_format': 'formato', 'author': 'autoría', 'description': 'sinopsis',
                'publisher': 'editorial', 'retail_price': 'PVP', 'image_url': 'portada', 'language': 'idioma',
                'yumekai_status': 'disponibilidad SD'}


def _empty(value):
    return value is None or str(value).strip().casefold() in {'', '-', '- -', 'n/d'}


def sd_review_changes(product, result):
    changes = {}
    notes = []
    if result.status != 'found':
        return changes, result.message or 'Sin consultar'
    previous_demographic = product.get('demographic')
    canonical = canonical_demographic(previous_demographic)
    if str(product.get('work_type') or '').casefold() == 'manga' and canonical is not None and canonical != previous_demographic:
        changes['demographic'] = canonical
    details = result.details
    if details is not None:
        values = {field: getattr(details, field) for field in
                  ('work_type', 'pages', 'author', 'description', 'publisher', 'image_url', 'language')}
        for field, value in values.items():
            if value is not None and (_empty(product.get(field))
                    or (field == 'description' and can_complete_description(product.get(field), value))):
                changes[field] = value
                if field == 'description' and not _empty(product.get(field)):
                    notes.append('Sinopsis abreviada completada desde SD')
        if (description_may_be_shortened(product.get('description')) and 'description' not in changes
                and details.description and details.description != product.get('description')):
            notes.append('Sinopsis guardada conservada: el texto de SD no amplía el mismo comienzo')
        if details.format_confirmed:
            book_format = normalize_sd_format(details.sd_format)
            if book_format != product.get('book_format'):
                changes['book_format'] = book_format
            notes.append(f'Formato SD: {details.sd_format or "sin datos"} → {book_format}')
        else:
            notes.append('Formato anterior conservado: falta confirmar la ficha pública de SD')
        work_type = changes.get('work_type', product.get('work_type'))
        if str(work_type or '').casefold() == 'manga' and canonical is not None and canonical != previous_demographic:
            changes['demographic'] = canonical
        if str(work_type or '').casefold() == 'manga' and _empty(product.get('demographic')) and details.demographic:
            changes['demographic'] = canonical_demographic(details.demographic)
        elif (str(work_type or '').casefold() == 'manga' and details.demographic
              and canonical and canonical != canonical_demographic(details.demographic)):
            notes.append(f'SD propone {canonical_demographic(details.demographic)}; se conserva la demografía revisada {canonical}')
        if _empty(product.get('retail_price')) and details.retail_price is not None:
            price = normalize_price(details.retail_price)
            if price is not None and Decimal(price) > 0:
                changes['retail_price'] = price
    status = stock_code(product.get('yumekai_status'))
    stock = result.stock_info or (details.stock_info if details is not None else None)
    updated = stock.yumekai_status if stock is not None else (
        'yk_on_demand' if result.available else 'outofstock' if result.available is False else None)
    if updated is not None:
        if status != updated:
            changes['yumekai_status'] = updated
        if stock is not None:
            notes.append(stock.explanation)
    else:
        notes.append(stock.explanation if stock is not None else 'Disponibilidad sin confirmar en SD; estado anterior conservado')
    if result.message:
        notes.append(result.message)
    merged = {**product, **changes}
    missing = [caption for field, caption in FIELD_LABELS.items()
               if field not in {'yumekai_status', 'demographic'} and _empty(merged.get(field))]
    if str(merged.get('work_type') or '').casefold() == 'manga' and _empty(merged.get('demographic')):
        missing.append('demografía')
    if missing:
        notes.append('Por completar: ' + ', '.join(missing))
    prefix = 'Actualiza: ' + ', '.join(FIELD_LABELS[field] for field in changes) if changes else 'Sin campos nuevos'
    return changes, ' · '.join([prefix, *notes])
