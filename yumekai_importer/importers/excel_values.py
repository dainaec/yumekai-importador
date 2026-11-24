from decimal import Decimal, InvalidOperation


def normalize_isbn(value: object) -> str | None:
    if isinstance(value, float) and value.is_integer():
        value = int(value)

    isbn = "".join(str(value or "").replace("-", "").split())
    if len(isbn) == 13 and isbn.isascii() and isbn.isdigit():
        return isbn
    return None


def parse_price(value: object, row_number: int) -> Decimal | None:
    text = "" if value is None else str(value).strip()
    if not text:
        return None

    try:
        price = Decimal(text.replace(",", "."))
    except InvalidOperation as error:
        raise ValueError(f"PVP incorrecto en la fila {row_number}.") from error

    if not price.is_finite():
        raise ValueError(f"PVP incorrecto en la fila {row_number}.")
    return price