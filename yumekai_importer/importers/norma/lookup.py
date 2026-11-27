"""Public Norma lookup with a session and exact edition ISBN verification."""
from dataclasses import dataclass
from http.cookiejar import CookieJar
import json
import re
import ssl
from threading import Event
import unicodedata
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urljoin, urlsplit
from urllib.request import HTTPCookieProcessor, HTTPSHandler, Request, build_opener

from lxml import html
import truststore

from yumekai_importer.catalog.review_fields import normalize_review_identifier
from yumekai_importer.catalog.title_parser import analyze_title
from yumekai_importer.catalog.book_formats import normalize_yumekai_format


BASE_URL = "https://www.normaeditorial.com"
MAX_CANDIDATES = 6


class NormaLookupCancelled(Exception):
    pass


class NormaEditionMismatch(ValueError):
    pass


@dataclass(frozen=True)
class NormaDetails:
    title: str = ""
    author: str | None = None
    description: str | None = None
    series: str | None = None
    volume: str | None = None
    pages: int | None = None
    book_format: str | None = None
    retail_price: str | None = None
    image_url: str | None = None
    work_type: str | None = None
    demographic: str | None = None
    classification_note: str = ""
    availability: str | None = None
    yumekai_status: str | None = None
    format_note: str = ""


@dataclass(frozen=True)
class NormaLookupResult:
    isbn: str
    status: str
    details: NormaDetails | None = None
    url: str = ""
    message: str = ""


def _text(node):
    return " ".join(node.text_content().split()).strip()


def _key(value):
    text = unicodedata.normalize("NFKD", str(value or "")).casefold()
    return " ".join("".join(c for c in text if not unicodedata.combining(c)).split())


def _is_norma_url(url):
    parts = urlsplit(url)
    return (parts.scheme == "https" and parts.hostname == "www.normaeditorial.com"
            and parts.port in (None, 443) and not parts.username and not parts.password)


def _classification(title, description, labels):
    # The site's /manga breadcrumb includes Korean and Chinese comics too.
    text = _key(description)
    label_keys = {_key(value).lstrip("#") for value in labels}
    if re.search(r"\b(?:novela|novel|artbook|guia|ilustraciones)\b", _key(title)) or label_keys & {
        "novela", "novela ligera", "artbook", "guia",
    }:
        return None, None, "Novela o libro ilustrado: revisar el tipo de obra manualmente."

    confirmed = set()
    for word, value in (("manhwa", "Manhwa"), ("manhua", "Manhua")):
        if word in label_keys or re.search(
            rf"\b(?:el|este|un|famoso|aclamado|popular|exitoso)\s+"
            rf"(?:(?:nuevo|famoso|aclamado|popular|exitoso)\s+){{0,2}}{word}\b", text
        ):
            confirmed.add(value)
    work_type = next(iter(confirmed)) if len(confirmed) == 1 else None
    demographics = {
        "shonen": "Shonen", "shojo": "Shōjo", "seinen": "Seinen", "josei": "Josei",
        "kodomo": "Kodomo", "boys love": "Yaoi / BL", "yaoi": "Yaoi / BL", "yuri": "Yuri",
    }
    found = {demographics[key] for key in label_keys if key in demographics}
    demographic = next(iter(found)) if len(found) == 1 else None
    if work_type:
        note = f"Tipo confirmado en la descripción o etiqueta de esta ficha: {work_type}."
    else:
        note = "La sección Manga de Norma no distingue el origen: tipo de obra pendiente de confirmar."
    return work_type, demographic, note


def parse_norma_details(page, isbn, source_url):
    main = page.get_element_by_id("mid-col", None)
    if main is None or not main.xpath(".//h1"):
        raise ValueError("Norma no ha devuelto una ficha de producto reconocible.")
    values = {}
    for item in main.xpath('.//*[@id="features"]/*[label]'):
        labels = item.xpath("./label")
        label = _text(labels[0])
        value = _text(item)[len(label):].strip()
        values[_key(label)] = value
    actual = re.sub(r"[\s-]+", "", values.get("isbn", ""))
    if actual != isbn:
        raise NormaEditionMismatch("El ISBN de la ficha de Norma corresponde a otra edición.")

    title = _text(main.xpath(".//h1")[0])
    authors = main.xpath('.//*[contains(concat(" ",normalize-space(@class)," ")," authors-list ")]/a')
    author = " / ".join(dict.fromkeys(_text(node) for node in authors if _text(node))) or None
    paragraphs = main.xpath('.//*[@id="content"]/*[self::p or self::ul or self::ol]')
    description = "\n\n".join(_text(node) for node in paragraphs if _text(node)) or None
    labels = [_text(node) for node in main.xpath('.//a[contains(@class,"badge")]')]
    work_type, demographic, note = _classification(title, description, labels)
    pages_match = re.fullmatch(r"(\d+)\s*(?:B/?N|color|BN)?", values.get("paginas", ""), re.I)
    pages = int(pages_match.group(1)) if pages_match and int(pages_match.group(1)) > 0 else None
    price = re.fullmatch(r"([0-9]{1,8}(?:[.,][0-9]{1,2})?)\s*€?", values.get("pvp", ""))
    image = page.xpath('//meta[@property="og:image"]/@content')
    image_url = urljoin(source_url, image[0]) if image else None
    if image_url and not _is_norma_url(image_url):
        image_url = None
    inferred = analyze_title(title, isbn, known_series=(values["serie"],) if values.get("serie") else ())
    return NormaDetails(
        title=title, author=author, description=description,
        series=values.get("serie") or inferred.series, volume=inferred.volume,
        pages=pages, book_format=normalize_yumekai_format(
            "Tapa dura" if re.search(r"\bcartone\b", _key(values.get("formato")))
            else values.get("formato")),
        retail_price=price.group(1).replace(",", ".") if price else None,
        image_url=image_url, work_type=work_type, demographic=demographic,
        classification_note=note,
    )


class _NormaClient:
    def __init__(self, stop):
        self.stop = stop
        context = truststore.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
        self.opener = build_opener(HTTPSHandler(context=context), HTTPCookieProcessor(CookieJar()))

    def fetch(self, url, *, referer=None):
        if not _is_norma_url(url):
            raise ValueError("La dirección no pertenece al catálogo HTTPS de Norma Editorial.")
        for attempt in range(2):
            if self.stop.is_set():
                raise NormaLookupCancelled()
            try:
                headers = {"User-Agent": "YumekaiImporter/1.0", "Cache-Control": "no-cache"}
                if referer:
                    headers.update({"Referer": referer, "X-Requested-With": "XMLHttpRequest"})
                with self.opener.open(Request(url, headers=headers), timeout=20) as response:
                    final = response.geturl()
                    if not _is_norma_url(final):
                        raise ValueError("Norma ha redirigido fuera de su catálogo.")
                    data = response.read(3_000_001)
                    if len(data) > 3_000_000:
                        raise ValueError("La respuesta de Norma es demasiado grande.")
                    charset = response.headers.get_content_charset() or "utf-8"
                if self.stop.is_set():
                    raise NormaLookupCancelled()
                return data, final, charset
            except HTTPError as error:
                if attempt or error.code not in {408, 429, 500, 502, 503, 504}:
                    raise
            except (URLError, TimeoutError, OSError):
                if attempt:
                    raise
            if self.stop.wait(1):
                raise NormaLookupCancelled()
        raise RuntimeError("Norma no ha respondido.")

    def search(self, query):
        url = BASE_URL + "/buscador/" + quote(query, safe="")
        data, final, charset = self.fetch(url)
        page = html.fromstring(data, parser=html.HTMLParser(encoding=charset))
        inputs = page.xpath('//*[@id="buscadorInput"]/@data-token')
        if not inputs or not inputs[0]:
            raise ValueError("No se pudo abrir el buscador público de Norma.")
        api = BASE_URL + "/solr/" + quote(inputs[0], safe="") + "/" + quote(query, safe="")
        data, _, _ = self.fetch(api, referer=final)
        payload = json.loads(data)
        if not isinstance(payload, dict) or payload.get("error") or not isinstance(payload.get("album"), list):
            raise ValueError("El buscador de Norma no ha devuelto resultados válidos. Vuelve a intentarlo.")
        urls = []
        for entry in payload["album"]:
            if not isinstance(entry, dict) or not isinstance(entry.get("slug"), str):
                continue
            candidate = urljoin(BASE_URL, entry["slug"])
            if _is_norma_url(candidate) and urlsplit(candidate).path.startswith("/ficha/"):
                if candidate not in urls:
                    urls.append(candidate)
        return urls[:MAX_CANDIDATES]


def lookup_norma_isbn(isbn, stop_requested=None, *, title=""):
    stop = stop_requested if stop_requested is not None else Event()
    if stop.is_set():
        raise NormaLookupCancelled()
    normalized = normalize_review_identifier(str(isbn or ""))
    if not re.fullmatch(r"[0-9]{13}", normalized):
        return NormaLookupResult(normalized, "not_found", message="El código no permite confirmar un ISBN-13 en Norma.")
    client = _NormaClient(stop)
    queries = list(dict.fromkeys(query for query in (normalized, " ".join(str(title).split())) if query))
    visited = set()
    for query in queries:
        for url in client.search(query):
            if url in visited:
                continue
            visited.add(url)
            data, final, charset = client.fetch(url)
            page = html.fromstring(data, parser=html.HTMLParser(encoding=charset))
            try:
                details = parse_norma_details(page, normalized, final)
            except NormaEditionMismatch:
                continue
            return NormaLookupResult(normalized, "found", details, final,
                                     "ISBN de la edición confirmado en Norma Editorial.")
    return NormaLookupResult(normalized, "not_found", message=(
        "No se ha confirmado una ficha de Norma con el mismo ISBN. "
        "Se conservan los datos y la disponibilidad; otra edición no se aplica."
    ))
