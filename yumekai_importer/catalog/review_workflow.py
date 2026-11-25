"""Rules shared by the review table and the WooCommerce export."""

import unicodedata
from decimal import Decimal

from yumekai_importer.catalog.review_fields import (
    normalize_pages, normalize_price, normalize_review_isbn, normalize_volume,
)

STOCK_LABELS = {
    "onbackorder": "Se puede reservar",
    "instock": "Hay existencias",
    "yk_on_demand": "Bajo demanda",
    "outofstock": "Sin existencias",
}
WORK_TYPES = ("Manga", "Manhwa", "Manhua")


def search_text(value: object) -> str:
    text = unicodedata.normalize("NFKD", str(value or "").casefold())
    return "".join(char for char in text if not unicodedata.combining(char)).strip()


def stock_code(value: object) -> str:
    code = str(value or "")
    return {"preorder": "onbackorder", "in_stock": "instock"}.get(code, code)


def matches_filters(product: dict, title: str = "", publisher=None, work_type=None) -> bool:
    return (
        search_text(title) in search_text(product.get("title"))
        and (publisher is None or search_text(product.get("publisher")) == search_text(publisher))
        and (work_type is None or search_text(product.get("work_type")) == search_text(work_type))
    )


def readiness_issues(product: dict) -> list[str]:
    issues = []
    try:
        normalize_review_isbn(str(product.get("isbn") or ""))
    except ValueError:
        issues.append("Código fuera del estándar ISBN-13; requiere autorización")
    if not str(product.get("title") or "").strip():
        issues.append("Falta título")
    for field, normalize in (("volume", normalize_volume), ("pages", normalize_pages), ("retail_price", normalize_price)):
        value = product.get(field)
        try:
            normalized = normalize("" if value is None else str(value).strip())
            if field == "retail_price" and (normalized is None or Decimal(normalized) <= 0):
                issues.append("Falta un PVP mayor que cero")
        except ValueError:
            issues.append({"volume": "Tomo no válido", "pages": "Páginas no válidas", "retail_price": "PVP no válido"}[field])
    if not str(product.get("publisher") or "").strip():
        issues.append("Falta editorial")
    if product.get("work_type") not in WORK_TYPES:
        issues.append("Selecciona el tipo de obra")
    if stock_code(product.get("yumekai_status")) not in STOCK_LABELS:
        issues.append("Comprueba el estado Yumekai")
    return issues
