import ssl
import re
import unicodedata
from dataclasses import dataclass
from functools import lru_cache
from urllib.parse import urlsplit
from urllib.request import Request, urlopen

import truststore
from lxml import html

from yumekai_importer.importers.excel_values import normalize_isbn
from yumekai_importer.catalog.product import Product
from yumekai_importer.catalog.classification import canonical_demographic, sd_classification
from yumekai_importer.catalog.book_formats import normalize_sd_format
from yumekai_importer.catalog.descriptions import can_complete_description, description_may_be_shortened

@dataclass(frozen=True)
class SdDetails:
    work_type: str | None
    demographic: str | None
    pages: int | None
    sd_format: str | None
    author: str | None
    description: str | None
    publisher: str | None = None
    retail_price: str | None = None
    image_url: str | None = None
    language: str | None = None
    format_confirmed: bool = True


def _text(page: html.HtmlElement, element_id: str) -> str | None:
    element = page.get_element_by_id(element_id, None)
    value = element.text_content().strip() if element is not None else ""
    return None if value.upper() in {"", "-", "- -", "N/D"} else value


def _main_article(page: html.HtmlElement) -> html.HtmlElement:
    article = page.get_element_by_id("dvFichaArticuloFA", None)
    return article if article is not None else page


def _is_legacy_detail_url(url: str) -> bool:
    return urlsplit(url).path.casefold().endswith("/fichaarticulo.aspx")


def _public_detail_url(page: html.HtmlElement, source_url: str) -> str | None:
    if not _is_legacy_detail_url(source_url):
        return None
    article = _main_article(page)
    title = _text(article, "txtTitulo")
    reference = _text(article, "txtReferenciaInterna")
    if not title or not reference or not re.fullmatch(r"[a-zA-Z0-9]+\.[a-zA-Z0-9]+", reference):
        return None
    folded = unicodedata.normalize("NFKD", title).casefold()
    folded = "".join(char for char in folded if not unicodedata.combining(char))
    slug = re.sub(r"[^a-z0-9]+", "-", folded).strip("-") or "articulo"
    code = reference.replace(".", "").casefold()
    return f"https://www.sddistribuciones.com/{slug}-id-{code}"


def _parse_public_details(page: html.HtmlElement, url: str, isbn: str) -> SdDetails:
    if _is_legacy_detail_url(url) or page.get_element_by_id("dvFichaArticuloFA", None) is None:
        raise ValueError("SD no ha devuelto la ficha pública para confirmar el formato.")
    return _parse_details(page, isbn)


def _parse_details(page: html.HtmlElement, isbn: str) -> SdDetails:
    expected = normalize_isbn(isbn)
    article = _main_article(page)
    actual = normalize_isbn(_text(article, "txtISBN")) or normalize_isbn(_text(article, "txtEan"))
    if expected is None or actual != expected:
        raise ValueError("El ISBN de la ficha de SD no coincide.")

    work_type, demographic = sd_classification([
        _text(page, element_id) for element_id in
        ("txtTematicaTema", "txtTematicaMateria", "txtTematicaSubMateria")
    ])

    raw_pages = _text(page, "txtNumPag2") or ""
    pages = (int(raw_pages) or None) if raw_pages.isdecimal() else None

    raw_price = _text(page, "importe1PVP") or ""
    price = re.fullmatch(r"\s*([0-9]{1,8}(?:[.,][0-9]{1,2})?)\s*€?\s*", raw_price)
    image_nodes = page.xpath('//*[@id="containerPortada"]//img[@src]/@src')
    image_url = image_nodes[0] if image_nodes else None
    if image_url and not image_url.startswith("https://"):
        image_url = None
    if image_url and "noimage" in image_url.casefold():
        image_url = None

    return SdDetails(
        work_type=work_type,
        demographic=demographic,
        pages=pages,
        sd_format=_text(article, "txtFormatoTapa"),
        author=_text(page, "txtAutorFA"),
        description=_text(page, "txtSinpsis"),
        publisher=_text(page, "txtFamilia") or _text(page, "txtEditorial"),
        retail_price=price.group(1).replace(",", ".") if price else None,
        image_url=image_url,
        language=_text(page, "txtIdiomaFA") or _text(page, "txtIdioma"),
    )


def _is_sd_url(url: str) -> bool:
    parts = urlsplit(url)
    return parts.scheme == "https" and parts.hostname == "www.sddistribuciones.com"


@lru_cache(maxsize=1)
def _ssl_context() -> ssl.SSLContext:
    return truststore.SSLContext(ssl.PROTOCOL_TLS_CLIENT)


def _read_details_page(url: str) -> tuple[html.HtmlElement, str]:
    if not _is_sd_url(url):
        raise ValueError("Usa una URL HTTPS de SD Distribuciones.")

    context = _ssl_context()
    request = Request(url, headers={"User-Agent": "YumekaiImporter/1.0"})
    with urlopen(request, timeout=20, context=context) as response:
        if not _is_sd_url(response.geturl()):
            raise ValueError("La ficha ha redirigido fuera de SD.")

        content = response.read(3_000_001)
        if len(content) > 3_000_000:
            raise ValueError("La ficha de SD es demasiado grande.")

        parser = html.HTMLParser(encoding=response.headers.get_content_charset())
        return html.fromstring(content, parser=parser), response.geturl()


@lru_cache(maxsize=2048)
def read_sd_details(url: str, isbn: str) -> SdDetails:
    page, final = _read_details_page(url)
    details = _parse_details(page, isbn)
    public_url = _public_detail_url(page, final)
    if public_url is not None:
        page, final = _read_details_page(public_url)
        details = _parse_public_details(page, final, isbn)
    elif _is_legacy_detail_url(final):
        raise ValueError("No se pudo localizar la ficha pública de SD para confirmar el formato.")
    return details

def needs_sd_details(product: Product) -> bool:
    return description_may_be_shortened(product.description) or not all((
        product.work_type,
        product.pages,
        product.book_format,
        (product.author or "").strip(),
        (product.description or "").strip(),
    )) or (
        (product.work_type or "").casefold() == "manga"
        and not product.demographic
    )


def apply_sd_details(product: Product, details: SdDetails) -> bool:
    values = {
        "work_type": details.work_type,
        "pages": details.pages,
        "author": details.author,
        "description": details.description,
    }

    work_type = product.work_type or details.work_type
    if (work_type or "").casefold() == "manga":
        values["demographic"] = details.demographic

    added = False
    if details.format_confirmed:
        book_format = normalize_sd_format(details.sd_format)
        if book_format != product.book_format:
            product.book_format = book_format
            added = True
    current_demographic = canonical_demographic(product.demographic)
    if current_demographic is not None and current_demographic != product.demographic:
        product.demographic = current_demographic
        added = True
    for field, value in values.items():
        current = getattr(product, field)
        if value is not None and (not str(current or "").strip()
                                  or (field == "description" and can_complete_description(current, value))):
            setattr(product, field, value)
            added = True

    return added
