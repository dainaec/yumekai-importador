"""Mandatory identity fields and warnings that require deliberate approval."""
from decimal import Decimal, InvalidOperation

from yumekai_importer.catalog.review_fields import normalize_review_identifier, normalize_review_isbn
from yumekai_importer.catalog.review_quality import completeness_issues
from yumekai_importer.catalog.review_workflow import STOCK_LABELS, stock_code


def required_issues(product: dict, *, ready=True) -> list[str]:
    issues = []
    try:
        normalize_review_identifier(str(product.get("isbn") or ""))
    except ValueError as error:
        issues.append(str(error))
    if not str(product.get("title") or "").strip():
        issues.append("Falta el título.")
    if ready and stock_code(product.get("yumekai_status")) not in STOCK_LABELS:
        issues.append("Selecciona el estado Yumekai.")
    return issues


def import_exception_issues(product: dict) -> list[str]:
    issues = []
    try:
        normalize_review_isbn(str(product.get("isbn") or ""))
    except ValueError:
        issues.append("El código no cumple el estándar ISBN-13; se conservará completo.")
    try:
        value = product.get("retail_price")
        price = Decimal(str(value).replace(",", ".")) if value is not None else None
        if price is None or not price.is_finite() or price <= 0:
            issues.append("El PVP falta o no es mayor que cero.")
    except (InvalidOperation, ValueError):
        issues.append("El PVP no se puede interpretar; se guardará vacío.")
    return issues


def ready_exception_issues(product: dict) -> list[str]:
    return completeness_issues(product)
