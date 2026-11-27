"""Combined filters over the reviewed values, including unsaved corrections."""
from decimal import Decimal, InvalidOperation

from yumekai_importer.catalog.classification import canonical_demographic
from yumekai_importer.catalog.review_quality import empty_data
from yumekai_importer.catalog.manual_completion import manually_complete, pending_data_issues
from yumekai_importer.catalog.review_workflow import readiness_issues, search_text, stock_code


TEXT_FILTERS = ("isbn", "sku", "author", "series")
CHOICE_FILTERS = ("demographic", "book_format", "language", "yumekai_status")
RANGE_FIELDS = ("retail_price", "pages", "volume")


def _number(value):
    try:
        number = Decimal(str(value).strip().replace(",", "."))
        return number if number.is_finite() else None
    except (InvalidOperation, ValueError):
        return None


def filter_error(criteria: dict) -> str:
    captions = {"retail_price": "PVP", "pages": "páginas", "volume": "tomo"}
    for field in RANGE_FIELDS:
        lower, upper = criteria.get(field + "_min", ""), criteria.get(field + "_max", "")
        if lower == upper == "":
            continue
        minimum, maximum = _number(lower), _number(upper)
        if (lower != "" and minimum is None) or (upper != "" and maximum is None):
            return "Revisa los valores del intervalo de " + captions[field] + "."
        if minimum is not None and maximum is not None and minimum > maximum:
            return "El mínimo de " + captions[field] + " no puede superar al máximo."
    return ""


def matches_review_filters(product: dict, query="", publisher=None, work_type=None, *, criteria=None,
                           incomplete_only=False) -> bool:
    criteria = criteria or {}
    if filter_error(criteria):
        return False
    query = " ".join(search_text(query).split())
    searchable = ("title", "isbn", "sku", "author", "series")
    isbn_query = query.replace("-", "").replace(" ", "")
    isbn_match = isbn_query.isdigit() and isbn_query in str(product.get("isbn") or "").replace("-", "")
    if query and not isbn_match and not any(query in " ".join(search_text(product.get(field)).split()) for field in searchable):
        return False
    for field, value in (("publisher", publisher), ("work_type", work_type)):
        if value is not None and search_text(product.get(field)) != search_text(value):
            return False
    for field in TEXT_FILTERS:
        wanted = search_text(criteria.get(field))

        if field == "isbn":
            wanted = wanted.replace("-", "").replace(" ", "")

        if not wanted:
            continue

        actual = search_text(product.get(field))

        if field == "isbn":
            actual = actual.replace("-", "").replace(" ", "")

        if wanted not in actual:
            return False
    for field in CHOICE_FILTERS:
        value = criteria.get(field)
        if value is None:
            continue
        actual = product.get(field)
        if field == "demographic":
            if product.get("work_type") != "Manga":
                return False
            actual = canonical_demographic(actual)
        elif field == "yumekai_status":
            actual = stock_code(actual)
        if value == "":
            if not empty_data(actual):
                return False
        elif search_text(actual) != search_text(value):
            return False
    featured = criteria.get("is_featured")
    if featured is not None and (product.get("is_featured") in (1, "1", True)) != bool(featured):
        return False
    for field in ("description", "image_url"):
        present = criteria.get(field)
        if present is not None and (not empty_data(product.get(field))) != bool(present):
            return False
    for field in RANGE_FIELDS:
        lower, upper = criteria.get(field + "_min", ""), criteria.get(field + "_max", "")
        if lower == upper == "":
            continue
        raw = str(product.get(field) or "").strip()
        parts = raw.split("-", 1) if field == "volume" else [raw]
        start, end = _number(parts[0]), _number(parts[-1])
        if start is None or end is None:
            return False
        minimum, maximum = _number(lower), _number(upper)
        # A pack 1-3 is included when filtering for any volume within that range.
        if (minimum is not None and end < minimum) or (maximum is not None and start > maximum):
            return False
    quality = criteria.get("quality")
    if quality == "blocking" and (manually_complete(product) or not readiness_issues(product)):
        return False
    if quality == "manual_complete" and not manually_complete(product):
        return False
    if quality == "complete" and pending_data_issues(product):
        return False
    if incomplete_only and not pending_data_issues(product):
        return False
    return True
