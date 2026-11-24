"""Match SD's product codes without imposing the ISBN standard on EANs/packs."""


def normalize_sd_code(value: object) -> str | None:
    code = "".join(str(value or "").replace("-", "").split()).casefold()
    return code or None
