"""Publisher routing shared by the review screens and supplier workers."""
import re
import unicodedata

SUPPLIERS = {
    "sd": "SD Distribuciones",
    "norma": "Norma Editorial",
    "milky_way": "Milky Way",
    "planeta": "Planeta",
}
PUBLISHERS = {
    "sd": ("Dolmen", "RBA", "Sekai", "Pika", "Kibook", "Panini", "Ivrea", "Arechi"),
    "norma": ("Norma",),
    "milky_way": ("Milky Way",),
    "planeta": ("Planeta",),
}


def _name(value):
    text = unicodedata.normalize("NFKD", str(value or "")).casefold()
    text = "".join(char for char in text if not unicodedata.combining(char))
    text = re.sub(r"[^a-z0-9]+", " ", text).strip()
    return re.sub(r"\s+(?:s a|s l|sa|sl|s a u|s l u)$", "", text)


_ALIASES = {
    "dolmen": ("dolmen", "dolmen editorial", "dolmen ediciones"),
    "rba": ("rba", "rba libros", "rba editorial"),
    "sekai": ("sekai", "sekai editorial", "editorial sekai"),
    "pika": ("pika", "pika ediciones", "pika edition", "pika editorial"),
    "kibook": ("kibook", "kibook ediciones", "kibook editorial"),
    "panini": ("panini", "panini comics", "panini manga", "panini espana", "panini comics espana"),
    "ivrea": ("ivrea", "editorial ivrea", "ivrea espana"),
    "arechi": ("arechi", "arechi manga", "arechi editorial", "arechi ediciones"),
    "norma": ("norma", "norma editorial", "editorial norma"),
    "milky way": ("milky way", "milkyway", "milky way ediciones", "milkyway ediciones"),
    "planeta": ("planeta", "planeta comic", "planeta comics", "planeta manga", "planeta deagostini", "editorial planeta"),
}
_ROUTING = {
    _name(alias): supplier
    for supplier, names in PUBLISHERS.items()
    for name in names
    for alias in _ALIASES[_name(name)]
}


def supplier_for_publisher(publisher):
    # Exact aliases: an unknown imprint must never silently go to SD.
    return _ROUTING.get(_name(publisher))


def blocked_products(products, supplier):
    return {key: product for key, product in products.items()
            if supplier_for_publisher(product.get("publisher")) != supplier}


def supplier_block_reason(products, supplier):
    if not products:
        return "Marca una o más fichas para consultar."
    blocked = blocked_products(products, supplier)
    if not blocked:
        return ""
    names = sorted({str(product.get("publisher") or "Sin editorial").strip() or "Sin editorial"
                    for product in blocked.values()})
    return (f"Consulta bloqueada: {SUPPLIERS[supplier]} no distribuye estas editoriales "
            f"o falta identificarlas: {', '.join(names)}. Desmarca esas fichas. "
            f"Editoriales admitidas: {', '.join(PUBLISHERS[supplier])}.")
