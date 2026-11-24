"""WooCommerce CSV using the headers and custom keys of Yumekai's export."""

import csv
import os
import re
from dataclasses import dataclass
from pathlib import Path
from tempfile import NamedTemporaryFile

from yumekai_importer.catalog.classification import ARTBOOK_CATEGORY, canonical_demographic
from yumekai_importer.catalog.review_fields import normalize_price, normalize_review_isbn, sale_price_preview
from yumekai_importer.catalog.review_workflow import readiness_issues, stock_code

HEADERS = (
    "ID", "Tipo", "SKU", "GTIN, UPC, EAN o ISBN", "Nombre", "Publicado", "¿Está destacado?",
    "Visibilidad en el catálogo", "Descripción corta", "Descripción",
    "Día en que empieza el precio rebajado", "Día en que termina el precio rebajado",
    "Estado del impuesto", "Clase de impuesto", "¿Existencias?", "Inventario",
    "Cantidad de bajo inventario", "¿Permitir reservas de productos agotados?", "¿Vendido individualmente?",
    "Peso (kg)", "Longitud (cm)", "Anchura (cm)", "Altura (cm)",
    "¿Permitir valoraciones de clientes?", "Nota de compra", "Precio rebajado", "Precio normal",
    "Categorías", "Etiquetas", "Clase de envío", "Imágenes", "Límite de descargas",
    "Días de caducidad de la descarga", "Superior", "Productos agrupados", "Ventas dirigidas",
    "Ventas cruzadas", "URL externa", "Texto del botón", "Posición",
    "Código de mercancía (código HS)", "País de origen", "Descripción de aduanas",
    "Estado Yumekai", "Marcas", "Datos personalizados de Blocksy",
    "Meta: _yk_item_kind", "Meta: _yk_brand", "Meta: _yk_franchise", "Meta: _yk_author",
    "Meta: _yk_volume", "Meta: _yk_format", "Meta: _yk_language", "Meta: _yk_pages", "Meta: _yk_isbn",
    "Meta: _yk_character", "Meta: _yk_manufacturer", "Meta: _yk_scale", "Meta: _yk_height",
    "Meta: _yk_material", "Meta: _yk_merch_type", "Meta: _yk_size", "Meta: _uag_css_file_name",
)


@dataclass(frozen=True)
class WordPressReference:
    product_id: int
    css_file_name: str = ""


def _wordpress_id(value) -> int | None:
    if value is None or str(value).strip() in {"", "0"}:
        return None
    if isinstance(value, bool) or not re.fullmatch(r"[0-9]+", str(value).strip()):
        raise ValueError("El ID de WordPress debe ser un número entero positivo o quedar vacío para un producto nuevo.")
    return int(str(value).strip()) or None


def _css_file_name(value, product_id: int) -> str:
    name = str(value or "").strip()
    if name and not re.fullmatch(rf"uag-css-{product_id}(?:-[0-9]+)?\.css", name):
        raise ValueError(f"El nombre del CSS no corresponde al ID {product_id}. Revisa la exportación de WordPress.")
    return name


def load_wordpress_reference(path: str | Path) -> dict[str, WordPressReference]:
    """Link existing WordPress IDs and CSS metadata by ISBN; never guess new IDs."""
    references = {}
    ids = {}
    try:
        with Path(path).open(encoding="utf-8-sig", newline="") as stream:
            reader = csv.DictReader(stream)
            columns = {re.sub(r"\s+", "", name.casefold()): name for name in reader.fieldnames or ()}
            required = {"id", "meta:_yk_isbn"}
            if not required <= columns.keys():
                raise ValueError("Selecciona un CSV exportado desde WordPress con ID y todos los metadatos personalizados.")
            for line, row in enumerate(reader, 2):
                def field(name):
                    return str(row.get(columns.get(name, "")) or "").strip()
                candidates = set()
                sku = field("sku")
                for value in (field("meta:_yk_isbn"), field("gtin,upc,eanoisbn"),
                              sku[4:] if sku.startswith("YMK-") else ""):
                    try:
                        candidates.add(normalize_review_isbn(value))
                    except ValueError:
                        pass
                if not candidates:
                    continue  # Other products without a usable ISBN do not participate.
                if len(candidates) != 1:
                    raise ValueError(f"Fila {line}: los campos de ISBN del CSV de WordPress no coinciden.")
                isbn = next(iter(candidates))
                product_id = _wordpress_id(field("id"))
                if product_id is None:
                    continue
                reference = WordPressReference(product_id, _css_file_name(field("meta:_uag_css_file_name"), product_id))
                if isbn in references and references[isbn] != reference:
                    raise ValueError(f"El ISBN {isbn} aparece con distintos ID o CSS en el CSV de WordPress.")
                if product_id in ids and ids[product_id] != isbn:
                    raise ValueError(f"El ID {product_id} aparece con distintos ISBN en el CSV de WordPress.")
                references[isbn] = reference
                ids[product_id] = isbn
    except (OSError, UnicodeError, csv.Error) as error:
        raise ValueError(f"No se pudo leer la referencia de WordPress. {error}") from error
    if not references:
        raise ValueError("El CSV de WordPress no contiene productos con ID e ISBN válidos para vincular.")
    return references


def woocommerce_categories(work_type: str, demographic: str | None) -> list[str]:
    if work_type not in {"Manga", "Manhwa", "Manhua"}:
        return []
    if work_type == "Manhwa":
        return ["Manwha/Manhua > Manwha", "Manwha/Manhua"]
    if work_type == "Manhua":
        return ["Manwha/Manhua > Manhua", "Manwha/Manhua"]
    demographic = canonical_demographic(demographic)
    if demographic == ARTBOOK_CATEGORY:
        return [f"Manga > {demographic}", "Manga"]
    return ["Manga", f"Manga > {demographic}"] if demographic else ["Manga"]


def product_row(product: dict, published: int = 1, tax_class: str = "tasa-reducida", *,
                wordpress_reference: dict[str, WordPressReference] | None = None,
                allow_incomplete: bool = False) -> dict:
    if published not in (-1, 0, 1):
        raise ValueError("Elige Publicado (1), Borrador (-1) o Privado (0).")
    issues = readiness_issues(product)
    if product.get("review_status") != "ready_to_upload":
        issues.append("La ficha sigue pendiente de revisión")
    if product.get("review_status") != "ready_to_upload" or (issues and not allow_incomplete):
        raise ValueError(f"{product.get('title') or product.get('isbn')}: " + "; ".join(issues))
    isbn = str(product.get("isbn") or "")
    status = stock_code(product.get("yumekai_status"))
    categories = woocommerce_categories(product.get("work_type"), product.get("demographic"))
    # A literal comma in a taxonomy name must be escaped for WooCommerce.
    category_text = ", ".join(value.replace(",", "\\,") for value in categories)
    product_id = _wordpress_id(product.get("woocommerce_id"))
    reference = (wordpress_reference or {}).get(isbn)
    css_name = ""
    if reference is not None:
        if product_id is not None and product_id != reference.product_id:
            raise ValueError(f"El ID de WordPress de {isbn} no coincide con el CSV de referencia.")
        product_id = reference.product_id
        css_name = _css_file_name(reference.css_file_name, product_id)
    elif product_id is not None:
        css_name = _css_file_name(product.get("uag_css_file_name"), product_id)
    try:
        raw_price = product.get("retail_price")
        price = normalize_price("" if raw_price is None else str(raw_price).strip())
    except ValueError:
        if not allow_incomplete:
            raise
        price = None
    row = dict.fromkeys(HEADERS, "")
    row.update({
        "ID": str(product_id) if product_id is not None else "", "Tipo": "simple",
        "SKU": f"YMK-{isbn}" if isbn else str(product.get("sku") or ""),
        "Nombre": product.get("title") or "", "Publicado": str(published),
        "¿Está destacado?": "1" if product.get("is_featured") in (1, "1", True) else "0",
        "Visibilidad en el catálogo": "visible", "Descripción": product.get("description") or "",
        "Estado del impuesto": "taxable", "Clase de impuesto": tax_class.strip(),
        "¿Existencias?": {"instock": "1", "onbackorder": "backorder", "outofstock": "0", "yk_on_demand": "0"}.get(status, ""),
        "¿Permitir reservas de productos agotados?": "0", "¿Vendido individualmente?": "0",
        "¿Permitir valoraciones de clientes?": "0", "Posición": "0",
        "Precio rebajado": sale_price_preview(price).replace(".", ",") if price is not None else "",
        "Precio normal": price.replace(".", ",") if price is not None else "", "Categorías": category_text,
        "Imágenes": product.get("image_url") or "", "Estado Yumekai": status,
        "Meta: _yk_item_kind": str(product.get("work_type") or "").lower(), "Meta: _yk_brand": product.get("publisher"),
        "Meta: _yk_franchise": product.get("series"), "Meta: _yk_author": product.get("author"),
        "Meta: _yk_volume": product.get("volume"), "Meta: _yk_format": product.get("book_format"),
        "Meta: _yk_language": "Castellano", "Meta: _yk_pages": product.get("pages"),
        "Meta: _yk_isbn": isbn, "Meta: _uag_css_file_name": css_name,
    })
    return {key: "" if value is None else str(value) for key, value in row.items()}


def export_products(path: str | Path, products: list[dict], *, published: int = 1,
                    tax_class: str = "tasa-reducida",
                    wordpress_reference: dict[str, WordPressReference] | None = None,
                    allow_incomplete: bool = False) -> int:
    if not products:
        raise ValueError("Selecciona al menos una ficha lista para subir.")
    rows = [product_row(product, published, tax_class, wordpress_reference=wordpress_reference,
                        allow_incomplete=allow_incomplete) for product in products]
    skus = [row["SKU"] for row in rows if row["SKU"]]
    if len(skus) != len(set(skus)):
        raise ValueError("Hay SKU repetidos en la selección.")
    ids = [row["ID"] for row in rows if row["ID"]]
    if len(ids) != len(set(ids)):
        raise ValueError("Hay ID de WordPress repetidos en la selección.")
    target = Path(path)
    temporary = None
    try:
        with NamedTemporaryFile(mode="w", encoding="utf-8-sig", newline="", dir=target.parent,
                                prefix=".yumekai-", suffix=".csv", delete=False) as output:
            temporary = Path(output.name)
            writer = csv.DictWriter(output, fieldnames=HEADERS)
            writer.writeheader()
            writer.writerows(rows)
        os.replace(temporary, target)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
    return len(rows)
