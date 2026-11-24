"""Data completeness and the checks shown before exporting reviewed products."""
from yumekai_importer.catalog.review_workflow import readiness_issues
from yumekai_importer.catalog.descriptions import description_may_be_shortened


RECOMMENDED_FIELDS = (
    ("author", "autoría"), ("series", "colección"), ("volume", "número de tomo, si corresponde"),
    ("language", "idioma"), ("book_format", "formato"), ("pages", "páginas"),
    ("description", "sinopsis"), ("image_url", "portada"),
)


def empty_data(value) -> bool:
    return value is None or str(value).strip().casefold() in {"", "-", "- -", "n/d", "por completar", "sin datos"}


def recommended_issues(product: dict) -> list[str]:
    issues = ["Falta " + caption for field, caption in RECOMMENDED_FIELDS if empty_data(product.get(field))]
    if description_may_be_shortened(product.get("description")):
        issues.append("Sinopsis posiblemente recortada: recomprobar en SD")
    if str(product.get("work_type") or "").casefold() == "manga" and empty_data(product.get("demographic")):
        issues.append("Falta demografía")
    return issues


def completeness_issues(product: dict) -> list[str]:
    return list(dict.fromkeys([*readiness_issues(product), *recommended_issues(product)]))


def export_review(products: dict) -> dict:
    review = {}
    for key, product in products.items():
        blocking, recommended = readiness_issues(product), recommended_issues(product)
        if blocking or recommended:
            review[key] = {"product": product, "blocking": blocking, "recommended": recommended}
    return review
