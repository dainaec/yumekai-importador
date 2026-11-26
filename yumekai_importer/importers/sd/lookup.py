"""Fresh, exact ISBN lookup. Never treats a recommendation as the requested book."""
from dataclasses import dataclass, replace
from threading import Event
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urljoin
from urllib.request import Request, urlopen

from lxml import html

from yumekai_importer.importers.sd.codes import normalize_sd_code, sd_codes_match, sd_code_variants
from yumekai_importer.importers.sd.availability import (
    SdStockInfo, consultation_day, prefer_stock_info, read_stock_info,
)
from yumekai_importer.importers.sd.details import (
    SdDetails, _is_sd_url, _is_legacy_detail_url, _main_article, _parse_details, _parse_public_details,
    _public_detail_url, _ssl_context, _text,
)
from yumekai_importer.importers.sd.stock import SD_CATALOG_URL


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
    stock_info: SdStockInfo | None = None


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
    return normalize_sd_code(_text(article, 'txtISBN')) or normalize_sd_code(_text(article, 'txtEan'))


def _detail_stock(page):
    return read_stock_info(page).available


def _read_public_detail(page, source_url, isbn, stop, *, checked_on=None):
    details = _parse_details(page, isbn, checked_on=checked_on)
    public_url = _public_detail_url(page, source_url)
    if public_url is None:
        if _is_legacy_detail_url(source_url):
            return page, source_url, replace(details, format_confirmed=False), (
                'Formato sin confirmar: no se pudo localizar la ficha pública de SD.')
        return page, source_url, details, ''
    try:
        public_page, final = _fetch_page(public_url, stop)
        public_details = _parse_public_details(public_page, final, isbn, checked_on=checked_on)
        return public_page, final, public_details, ''
    except SdLookupCancelled:
        message = 'Consulta detenida antes de confirmar el formato en la ficha pública de SD.'
    except Exception as error:
        message = f'Formato sin confirmar: no se pudo leer la ficha pública de SD. {error}'
    return page, source_url, replace(details, format_confirmed=False), message


def _lookup_sd_query(
    isbn: str,
    query: str,
    stop_requested: Event | None = None,
) -> SdLookupResult:
    stop = stop_requested if stop_requested is not None else Event()
    checked_on = consultation_day()
    normalized = normalize_sd_code(isbn)
    if normalized is None:
        raise ValueError('La ficha no tiene un código para buscar en SD.')
    url = SD_CATALOG_URL + '?' + urlencode({
        'query': query,
        'reset': 's',
    })
    page, final = _fetch_page(url, stop)
    if page.get_element_by_id('txtISBN', None) is not None or page.get_element_by_id('txtEan', None) is not None:
        article = _main_article(page)

        if not any(
            sd_codes_match(normalized, _text(article, field))
            for field in ("txtISBN", "txtEan")
        ):
            return SdLookupResult(
                normalized,
                "not_found",
                url=final,
                message="La ficha devuelta por SD tiene otro código.",
            )
        
        fallback = read_stock_info(page, checked_on=checked_on)
        page, final, details, message = _read_public_detail(page, final, normalized, stop, checked_on=checked_on)
        stock = prefer_stock_info(read_stock_info(page, checked_on=checked_on), fallback)
        return SdLookupResult(normalized, 'found', stock.available, details, final, message, stock)

    candidates = {}
    states = {}
    matched = False
    for card in page.find_class('fileproduct'):
        fields = card.find_class('dvISBN')
        actual = normalize_sd_code(fields[0].text_content()) if fields else None
        if not sd_codes_match(actual, normalized):
            continue
        matched = True
        labels = card.find_class('estado')
        if labels:
            info = SdStockInfo(' '.join(labels[0].text_content().split()), checked_on=checked_on)
            if info.kind:
                states[info.kind] = info
        for title in card.find_class('filetitle'):
            for href in title.xpath('.//a[@href]/@href'):
                detail_url = urljoin(final, href)
                if _is_sd_url(detail_url):
                    candidates[detail_url] = True
    fallback = next(iter(states.values())) if len(states) == 1 else SdStockInfo(checked_on=checked_on)
    if candidates:
        try:
            detail_page, detail_url = _fetch_page(next(iter(candidates)), stop)
            initial_stock = prefer_stock_info(read_stock_info(detail_page, checked_on=checked_on), fallback)
            detail_page, detail_url, details, message = _read_public_detail(
                detail_page, detail_url, normalized, stop, checked_on=checked_on)
            stock = prefer_stock_info(read_stock_info(detail_page, checked_on=checked_on), initial_stock)
            return SdLookupResult(normalized, 'found', stock.available, details, detail_url, message, stock)
        except SdLookupCancelled:
            if fallback.yumekai_status is None:
                raise
            return SdLookupResult(normalized, 'found', fallback.available, url=final,
                                  message='Consulta detenida antes de completar la ficha.', stock_info=fallback)
        except Exception as error:
            return SdLookupResult(normalized, 'found', fallback.available, url=final,
                                  message=f'Ficha sin completar: {error}', stock_info=fallback)
    if matched:
        return SdLookupResult(normalized, 'found', fallback.available, url=final,
                              message='Código localizado en el listado, pero sin enlace utilizable a su ficha.',
                              stock_info=fallback)
    if page.get_element_by_id('panNoResultados', None) is not None:
        return SdLookupResult(normalized, 'not_found', url=final,
                              message='SD no ha encontrado este código. No implica que esté agotado.')
    if page.find_class('fileproduct'):
        return SdLookupResult(normalized, 'not_found', url=final,
                              message='Los resultados de SD no coinciden exactamente con el código.')
    raise ValueError('SD devolvió una página sin una ficha ni resultados reconocibles. Vuelve a intentarlo.')

def lookup_sd_isbn(
    isbn: str,
    stop_requested: Event | None = None,
    *,
    title: str = "",
) -> SdLookupResult:
    stop = stop_requested if stop_requested is not None else Event()
    variants = sd_code_variants(isbn)

    if not variants:
        raise ValueError("La ficha no tiene un código para buscar en SD.")

    last = None
    tried = set()

    for query in variants:
        if stop.is_set():
            raise SdLookupCancelled()

        tried.add(query.casefold())
        last = _lookup_sd_query(isbn, query, stop)

        if last.status == "found":
            return last

    if title:
        query = " ".join(str(title).split())

        if query and query.casefold() not in tried:
            if stop.is_set():
                raise SdLookupCancelled()

            last = _lookup_sd_query(isbn, query, stop)

            if last.status == "found":
                return last

    assert last is not None
    return last
