import re
from decimal import Decimal, ROUND_HALF_UP
from yumekai_importer.catalog.classification import canonical_demographic


VOLUME_INPUT = r"[0-9]{1,10}(?:-[0-9]{1,10})?"
PAGES_INPUT = r"[0-9]{1,10}"
PRICE_INPUT = r"[0-9]{1,8}(?:[.,][0-9]{1,2})?"
ISBN_INPUT = r"[^\x00-\x1f\x7f]{0,128}"

BOOK_FORMATS = (
    "Rústica",
    "Rústica con sobrecubierta",
    "Tapa dura",
    "Box set",
    "Edición especial",
)


def normalize_review_identifier(text: str) -> str:
    code = str(text).strip()
    if not code:
        raise ValueError("Falta el ISBN o código del producto.")
    if len(code) > 128 or re.search(r"[\x00-\x1f\x7f]", code):
        raise ValueError("El código admite hasta 128 caracteres y no puede contener saltos de línea ni caracteres de control.")
    compact = re.sub(r"[\s-]+", "", code)
    return compact if re.fullmatch(r"[0-9]{13}", compact) else code


def normalize_review_isbn(text: str) -> str:
    isbn = re.sub(r"[\s-]+", "", text)
    if not re.fullmatch(r"97[89][0-9]{10}", isbn):
        raise ValueError("Introduce el ISBN-13 de esta edición. Debe tener 13 dígitos y empezar por 978 o 979.")
    checksum = sum(int(digit) * (3 if index % 2 else 1) for index, digit in enumerate(isbn))
    if checksum % 10:
        raise ValueError("El dígito de control del ISBN no coincide. Comprueba el código de esta edición.")
    return isbn


def normalize_volume(text: str) -> str | None:
    if not text:
        return None
    if not re.fullmatch(VOLUME_INPUT, text):
        raise ValueError("Escribe un número de tomo o un rango como 1-5.")
    first, separator, last = text.partition("-")
    if separator and int(first) > int(last):
        raise ValueError("El último tomo del rango debe ser igual o mayor que el primero.")
    return text


def normalize_pages(text: str) -> int | None:
    if not text:
        return None
    if not re.fullmatch(PAGES_INPUT, text) or not 1 <= int(text) <= 4_294_967_295:
        raise ValueError("Escribe un número entero positivo de páginas.")
    return int(text)


def normalize_price(text: str) -> str | None:
    if not text:
        return None
    if not re.fullmatch(PRICE_INPUT, text):
        raise ValueError("Escribe un PVP positivo o cero con hasta dos decimales, como 10,95.")
    return f"{Decimal(text.replace(',', '.')):.2f}"


def sale_price_preview(price: object) -> str | None:
    if price is None:
        return None
    discounted = Decimal(str(price)) * Decimal("0.95")
    return str(discounted.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


def review_categories(work_type: str | None, demographic: str | None) -> list[str]:
    work_type = (work_type or "").strip()
    demographic = canonical_demographic(demographic) or ""
    if not work_type:
        return []
    if work_type.casefold() == "manga" and demographic:
        return [work_type, f"{work_type} > {demographic}"]
    return [work_type]
