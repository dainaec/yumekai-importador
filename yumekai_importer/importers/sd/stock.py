import re
import ssl
from collections.abc import Callable
from http.cookiejar import CookieJar
from threading import Event
from time import sleep
from urllib.parse import urlencode, urlsplit, urljoin
from urllib.request import HTTPCookieProcessor, HTTPSHandler, Request, build_opener
from itertools import count

import truststore
from lxml import html

from yumekai_importer.importers.sd.codes import normalize_sd_code
from yumekai_importer.importers.sd.availability import SdStockInfo


SD_CATALOG_URL = "https://www.sddistribuciones.com/AvanzadaPlus.aspx"
KIBOOK_CATALOG_URL = f"{SD_CATALOG_URL}?codEditorial=KBK&t=ed"
PAGE_DELAY_SECONDS = 0.25

def _availability(label: str) -> bool | None:
    return SdStockInfo(label).available


def _next_page_data(page: html.HtmlElement) -> bytes | None:
    link = page.get_element_by_id("lnkSiguienteInf", None)
    if link is None:
        return None

    event = re.search(r"__doPostBack\('([^']+)'", link.get("href", ""))
    if event is None:
        return None

    fields = {
        field.get("name"): field.get("value", "")
        for field in page.xpath('//input[@type="hidden"][@name]')
        if field.get("name").startswith("__VIEWSTATE")
        or field.get("name") == "__EVENTVALIDATION"
    }
    fields["__EVENTTARGET"] = event.group(1)
    fields["__EVENTARGUMENT"] = ""
    return urlencode(fields).encode("ascii")


def read_sd_stock(
    isbns: set[str],
    catalog_url: str = KIBOOK_CATALOG_URL,
    *,
    max_pages: int | None = None,
    detail_urls: dict[str, str] | None = None,
    stop_requested: Event | None = None,
    progress: Callable[[int, int], None] | None = None,
    stock_results: dict[str, bool] | None = None,
) -> dict[str, bool]:
    if not isbns:
        return {}
    # SD's comparison key is separate from the literal code saved in the catalog.
    originals = {}
    for requested in isbns:
        originals.setdefault(normalize_sd_code(requested), set()).add(requested)

    context = truststore.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    client = build_opener(HTTPCookieProcessor(CookieJar()), HTTPSHandler(context=context))

    results: dict[str, set[bool]] = {}
    seen_pages: set[frozenset[str]] = set()
    found_isbns: set[str] = set()
    partial = stock_results if stock_results is not None else {}
    next_page_data = None

    pages = count() if max_pages is None else range(max_pages)
    for page_number in pages:
        if stop_requested is not None and stop_requested.is_set():
            break
        if page_number:
            if stop_requested is not None:
                if stop_requested.wait(PAGE_DELAY_SECONDS):
                    break
            else:
                sleep(PAGE_DELAY_SECONDS)

        request = Request(
            catalog_url,
            data=next_page_data,
            headers={"User-Agent": "YumekaiImporter/1.0"},
        )
        with client.open(request, timeout=20) as response:
            final_url = urlsplit(response.url)
            if final_url.scheme != "https" or final_url.hostname != "www.sddistribuciones.com":
                raise ValueError("La respuesta no viene del catálogo HTTPS de SD.")
            content = response.read(3_000_001)
            if len(content) > 3_000_000:
                raise ValueError("El catálogo de SD ha devuelto una página demasiado grande.")
            parser = html.HTMLParser(encoding=response.headers.get_content_charset())
            page = html.fromstring(content, parser=parser)

        page_isbns = set()
        for card in page.find_class("fileproduct"):
            isbn_fields = card.find_class("dvISBN")
            code = normalize_sd_code(isbn_fields[0].text_content()) if isbn_fields else ""
            if not code:
                continue

            page_isbns.add(code)
            if code not in originals:
                continue

            if detail_urls is not None:
                titles = card.find_class("filetitle")
                hrefs = titles[0].xpath(".//a[@href]/@href") if titles else []
                if hrefs:
                    article_url = urljoin(catalog_url, hrefs[0])
                    parts = urlsplit(article_url)
                    if parts.scheme == "https" and parts.hostname == "www.sddistribuciones.com":
                        for isbn in originals[code]:
                            detail_urls.setdefault(isbn, article_url)

            status_fields = card.find_class("estado")
            if status_fields:
                available = _availability(status_fields[0].text_content())
                if available is not None:
                    for isbn in originals[code]:
                        results.setdefault(isbn, set()).add(available)

        signature = frozenset(page_isbns)
        if not signature:
            raise ValueError("SD no ha devuelto un listado con ISBN reconocibles.")
        if signature in seen_pages:
            raise ValueError("SD ha repetido la misma página del listado.")
        seen_pages.add(signature)

        for code in page_isbns & originals.keys():
            found_isbns.update(originals[code])
        for isbn, values in results.items():
            if len(values) == 1:
                partial[isbn] = next(iter(values))
            else:
                partial.pop(isbn, None)
        if progress is not None:
            progress(page_number + 1, len(found_isbns))
        # WebForms pagination stays sequential, but only visit needed pages.
        if isbns <= found_isbns:
            break

        next_page_data = _next_page_data(page)
        if next_page_data is None:
            break
    else:
        raise ValueError(f"El listado de SD supera el límite de {max_pages} páginas.")

    return {
        isbn: next(iter(values))
        for isbn, values in results.items()
        if len(values) == 1
    }

def read_sd_stock_batches(
    references: dict[str, str],
    *,
    detail_urls: dict[str, str] | None = None,
    stop_requested: Event | None = None,
    progress: Callable[[str, int, int, int], None] | None = None,
) -> tuple[dict[str, bool], list[str]]:
    batches: dict[str, set[str]] = {}
    invalid = 0
    for isbn, reference in references.items():
        code, separator, item = reference.strip().partition(".")
        code = code.upper()
        if separator and item.strip() and re.fullmatch(r"[A-Z0-9]+", code):
            batches.setdefault(code, set()).add(isbn)
        else:
            invalid += 1

    stock: dict[str, bool] = {}
    errors: list[str] = ([f"{invalid} referencias SD no reconocibles. Recomprueba esas fichas por ISBN en Revisar pendientes."]
                         if invalid else [])
    for code, isbns in batches.items():
        if stop_requested is not None and stop_requested.is_set():
            break
        query = urlencode({"codEditorial": code, "t": "ed"})
        catalog_stock: dict[str, bool] = {}
        def page_progress(page: int, found: int) -> None:
            if progress is not None:
                progress(code, page, found, len(isbns))
        try:
            read_sd_stock(
                isbns,
                catalog_url=f"{SD_CATALOG_URL}?{query}",
                detail_urls=detail_urls,
                stop_requested=stop_requested,
                progress=page_progress,
                stock_results=catalog_stock,
            )
        except Exception as error:
            errors.append(f"{code}: {error}")
        # A later network error must not discard earlier pages.
        stock.update(catalog_stock)

    return stock, errors
