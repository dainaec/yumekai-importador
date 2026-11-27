"""Scope and validate edits to the shared fields of one collection."""
import unicodedata

from yumekai_importer.catalog.book_formats import normalize_yumekai_format
from yumekai_importer.catalog.classification import DEMOGRAPHICS, canonical_demographic
from yumekai_importer.catalog.review_fields import BOOK_FORMATS, normalize_pages
from yumekai_importer.catalog.review_workflow import WORK_TYPES


COLLECTION_FIELDS = (
    ("work_type", "Tipo de obra"),
    ("demographic", "Demografía"),
    ("book_format", "Formato"),
    ("pages", "Número de páginas"),
    ("description", "Sinopsis"),
)


def collection_key(value):
    # Preserve accents and punctuation: similarly named editions stay separate.
    return " ".join(unicodedata.normalize("NFKC", str(value or "")).casefold().split())


def collection_products(products, series, publisher=None):
    key = collection_key(series)
    if not key:
        return {}
    return {
        original: product for original, product in products.items()
        if collection_key(product.get("series")) == key
        and (publisher is None or collection_key(product.get("publisher")) == collection_key(publisher))
    }


def common_value(products, field):
    values = [_comparable(field, product.get(field)) for product in products.values()]
    return values[0] if values and all(value == values[0] for value in values) else None


def _comparable(field, value):
    if field == "demographic":
        return canonical_demographic(value)
    if field == "book_format":
        return normalize_yumekai_format(value)
    text = str(value).strip() if value is not None else ""
    if field == "pages" and text.isascii() and text.isdigit():
        return int(text)
    return text or None


def collection_changes(products, values):
    """Return only actual changes; never mutate the supplied product snapshots."""
    if not products:
        raise ValueError("Selecciona una colección con fichas para editar.")
    labels = dict(COLLECTION_FIELDS)
    if not values or set(values) - labels.keys():
        raise ValueError("Marca al menos uno de los cinco campos de la edición por colección.")

    normalized = {}
    for field, value in values.items():
        value = _comparable(field, value)
        if field == "pages":
            value = normalize_pages("" if value is None else str(value))
        if value is None:
            raise ValueError(f"Completa {labels[field].lower()} o desmarca ese campo.")
        choices = {"work_type": WORK_TYPES, "demographic": DEMOGRAPHICS, "book_format": BOOK_FORMATS}
        if field in choices and value not in choices[field]:
            raise ValueError(f"Selecciona un valor válido para {labels[field].lower()}.")
        normalized[field] = value

    if "demographic" in normalized and any(
        normalized.get("work_type", product.get("work_type")) != "Manga"
        for product in products.values()
    ):
        raise ValueError("La demografía solo se aplica a Manga. Marca también Tipo de obra y elige Manga "
                         "para aplicarla a todas las fichas de esta colección.")

    return {
        original: changes
        for original, product in products.items()
        if (changes := {field: value for field, value in normalized.items()
                        if _comparable(field, product.get(field)) != value})
    }
