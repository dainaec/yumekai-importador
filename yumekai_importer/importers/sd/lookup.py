"""Fresh, exact ISBN lookup. Never treats a recommendation as the requested book."""
from dataclasses import dataclass, replace
from threading import Event
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urljoin
from urllib.request import Request, urlopen

from lxml import html

from yumekai_importer.catalog.review_fields import normalize_review_isbn
from yumekai_importer.importers.excel_values import normalize_isbn
from yumekai_importer.importers.sd.details import (
    SdDetails, _is_sd_url, _is_legacy_detail_url, _main_article, _parse_details, _parse_public_details,
    _public_detail_url, _ssl_context, _text,
)
from yumekai_importer.importers.sd.stock import SD_CATALOG_URL, _availability


class SdLookupCancelled(Exception):
    pass


@dataclass(frozen=True)
class SdLookupResult:
    isbn: str
    status: str
    available: bool | None = None
    details: SdDetails | None = None
    url: str = ''
    message: str = ''


def _fetch_page(url: str, stop_requested: Event) -> tuple[html.HtmlElement, str]:
    if not _is_sd_url(url):
        raise ValueError('La dirección no pertenece al catálogo HTTPS de SD.')
    for attempt in range(2):
        if stop_requested.is_set():
            raise SdLookupCancelled()
        try:
            request = Request(url, headers={'User-Agent': 'YumekaiImporter/1.0',
                                           'Cache-Control': 'no-cache', 'Pragma': 'no-cache'})
            with urlopen(request, timeout=20, context=_ssl_context()) as response:
                final = response.geturl()
                if not _is_sd_url(final):
                    raise ValueError('SD ha redirigido fuera de su catálogo.')
                data = response.read(3_000_001)
                if len(data) > 3_000_000:
                    raise ValueError('SD ha devuelto una página demasiado grande.')
                parser = html.HTMLParser(encoding=response.headers.get_content_charset())
                return html.fromstring(data, parser=parser), final
        except HTTPError as error:
            retry = error.code in {408, 429, 500, 502, 503, 504}
            if not retry or attempt:
                raise
        except (URLError, TimeoutError, OSError):
            if attempt:
                raise
        if stop_requested.wait(1.0):
            raise SdLookupCancelled()
    raise RuntimeError('SD no ha respondido.')


def _detail_isbn(page):
    article = _main_article(page)
    return normalize_isbn(_text(article, 'txtISBN')) or normalize_isbn(_text(article, 'txtEan'))


def _detail_stock(page):
    # The document also contains stock for suggested books; scope to the main item.
    label = _text(page, 'dvContainerEstadoFichaArticulo') or ''
    if not label:
        element = page.get_element_by_id('HiddenEstadoArticulo', None)
        if element is not None:
            label = html.fromstring('<div>' + element.get('value', '') + '</div>').text_content()
    return _availability(label)


def _read_public_detail(page, source_url, isbn, stop):
    details = _parse_details(page, isbn)
    public_url = _public_detail_url(page, source_url)
    if public_url is None:
        if _is_legacy_detail_url(source_url):
            return page, source_url, replace(details, format_confirmed=False), (
                'Formato sin confirmar: no se pudo localizar la ficha pública de SD.')
        return page, source_url, details, ''
    try:
        public_page, final = _fetch_page(public_url, stop)
        public_details = _parse_public_details(public_page, final, isbn)
        return public_page, final, public_details, ''
    except SdLookupCancelled:
        message = 'Consulta detenida antes de confirmar el formato en la ficha pública de SD.'
    except Exception as error:
        message = f'Formato sin confirmar: no se pudo leer la ficha pública de SD. {error}'
    return page, source_url, replace(details, format_confirmed=False), message


def lookup_sd_isbn(isbn: str, stop_requested: Event | None = None) -> SdLookupResult:
    stop = stop_requested if stop_requested is not None else Event()
    normalized = normalize_review_isbn(isbn)
    url = SD_CATALOG_URL + '?' + urlencode({'query': normalized, 'reset': 's'})
    page, final = _fetch_page(url, stop)
    if page.get_element_by_id('txtISBN', None) is not None or page.get_element_by_id('txtEan', None) is not None:
        # A unique search result redirects straight to FichaArticulo.aspx.
        # Its related-product cards must not be used as search results.
        available = _detail_stock(page)
        page, final, details, message = _read_public_detail(page, final, normalized, stop)
        public_stock = _detail_stock(page)
        if public_stock is not None:
            available = public_stock
        return SdLookupResult(normalized, 'found', available, details, final, message)

    candidates = {}
    values = set()
    matched = False
    for card in page.find_class('fileproduct'):
        fields = card.find_class('dvISBN')
        actual = normalize_isbn(fields[0].text_content().strip()) if fields else None
        if actual != normalized:
            continue
        matched = True
        states = card.find_class('estado')
        available = _availability(states[0].text_content()) if states else None
        if available is not None:
            values.add(available)
        for title in card.find_class('filetitle'):
            for href in title.xpath('.//a[@href]/@href'):
                detail_url = urljoin(final, href)
                if _is_sd_url(detail_url):
                    candidates[detail_url] = True
    available = next(iter(values)) if len(values) == 1 else None
    if candidates:
        try:
            detail_page, detail_url = _fetch_page(next(iter(candidates)), stop)
            detail_page, detail_url, details, message = _read_public_detail(detail_page, detail_url, normalized, stop)
            detail_available = _detail_stock(detail_page)
            if detail_available is not None:
                available = detail_available
            return SdLookupResult(normalized, 'found', available, details, detail_url, message)
        except SdLookupCancelled:
            if available is None:
                raise
            return SdLookupResult(normalized, 'found', available, url=final,
                                  message='Consulta detenida antes de completar la ficha.')
        except Exception as error:
            # Keep an exact stock result when the detail page fails or mismatches.
            return SdLookupResult(normalized, 'found', available, url=final,
                                  message=f'Ficha sin completar: {error}')
    if matched:
        return SdLookupResult(normalized, 'found', available, url=final,
                              message='ISBN localizado en el listado, pero sin enlace utilizable a su ficha.')
    if page.get_element_by_id('panNoResultados', None) is not None:
        return SdLookupResult(normalized, 'not_found', url=final,
                              message='SD no ha encontrado este ISBN. No implica que esté agotado.')
    if page.find_class('fileproduct'):
        return SdLookupResult(normalized, 'not_found', url=final,
                              message='Los resultados de SD no coinciden exactamente con el ISBN.')
    raise ValueError('SD devolvió una página sin una ficha ni resultados reconocibles. Vuelve a intentarlo.')
