"""Read Norma's authenticated catalogue; the session exists only during a batch."""
from dataclasses import dataclass, field
from http.cookiejar import CookieJar
import re
import ssl
from threading import Event
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urljoin, urlsplit
from urllib.request import (
    HTTPCookieProcessor, HTTPRedirectHandler, HTTPSHandler, Request, build_opener,
)

from lxml import html
import truststore

from yumekai_importer.catalog.book_formats import normalize_yumekai_format
from yumekai_importer.catalog.classification import classification_key
from yumekai_importer.catalog.review_fields import BOOK_FORMATS, normalize_review_identifier
from yumekai_importer.catalog.title_parser import analyze_title
from yumekai_importer.diagnostics import register_secret
from yumekai_importer.importers.norma.lookup import (
    NormaDetails, NormaEditionMismatch, NormaLookupCancelled, NormaLookupResult,
    _classification, _text,
)


BASE_URL = "https://norma.zonalibros.com"
LOGIN_URL = BASE_URL + "/Login.aspx"
HOME_URL = BASE_URL + "/Clientes/Inicio.aspx"
MAX_BYTES = 3_000_000
MAX_CANDIDATES = 6


@dataclass(frozen=True)
class NormaCredentials:
    tax_id: str = field(repr=False)
    username: str = field(repr=False)
    password: str = field(repr=False)


class ZonaLibrosError(ValueError):
    pass


class ZonaLibrosAuthError(ZonaLibrosError):
    pass


def _is_portal_url(url):
    try:
        parts = urlsplit(url)
        return (parts.scheme == "https" and parts.hostname == "norma.zonalibros.com"
                and parts.port in (None, 443) and not parts.username and not parts.password)
    except ValueError:
        return False


class _PortalRedirects(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        if not _is_portal_url(urljoin(req.full_url, newurl)):
            raise ZonaLibrosError("ZonaLibros ha redirigido fuera de su portal HTTPS. Consulta detenida.")
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def _element(page, suffix):
    # Restrict data to the main article, excluding recommendations and cart rows.
    return page.get_element_by_id("ctl00_MainContent_" + suffix, None)


def _value(page, suffix):
    node = _element(page, suffix)
    return _text(node) if node is not None else ""


def _table_values(table):
    values = {}
    for row in table.xpath("./tr|./tbody/tr"):
        cells = row.xpath("./td|./th")
        for index in range(0, len(cells) - 1, 2):
            values[classification_key(_text(cells[index]))] = _text(cells[index + 1])
    return values


def _known(value):
    return value if classification_key(value) not in {"", "n d", "n a", "sin datos"} else None


def _signed_in(page):
    # The results page has no master-page prefix on these controls.
    return any(page.get_element_by_id(identifier, None) is not None
               for identifier in ("ctl00_lblNombreUsuario", "lblNombreUsuario"))


def _availability(page):
    node = _element(page, "lblDisponible")
    if node is None:
        return "Estado no indicado en ZonaLibros", None
    text = _text(node)
    hints = " · ".join(dict.fromkeys(node.xpath(".//@title")))
    label = " · ".join(part for part in (text, hints) if part)
    key = classification_key(label)
    # The distributor's stock is availability on demand, not shop inventory.
    if "disponible en fabricante" in key:
        return label, "outofstock"
    if "descatalogado" in key and ("stock no" in key or "no disponible" in key):
        return label, "outofstock"
    if "stock no" in key or "no disponible" in key:
        return label, None
    if "stock si" in key or "disponible para su envio" in key:
        return label, "yk_on_demand"
    return label or "Estado no indicado en ZonaLibros", None


def _edition_values(page, isbn):
    table = _element(page, "tblLibro")
    title = _value(page, "txtTitulo")
    if table is None or not title:
        raise ZonaLibrosError("ZonaLibros no ha devuelto una ficha reconocible. Se conservan los datos anteriores.")
    values = _table_values(table)
    actual = re.sub(r"[\s\-\u2010-\u2015]+", "", values.get("isbn", ""))
    if actual != isbn:
        raise NormaEditionMismatch("El ISBN de ZonaLibros corresponde a otra edición.")
    return title, values


def parse_zonalibros_stock(page, isbn, source_url):
    title, _ = _edition_values(page, isbn)
    availability, status = _availability(page)
    return NormaDetails(title=title, availability=availability, yumekai_status=status)


def parse_zonalibros_details(page, isbn, source_url):
    title, values = _edition_values(page, isbn)

    author_node = _element(page, "txtAutor")
    authors = author_node.xpath(".//a") if author_node is not None else []
    author = " / ".join(dict.fromkeys(_text(node).rstrip(", ") for node in authors))
    if not author and author_node is not None:
        author = _text(author_node).rstrip(", ")
    synopsis = _element(page, "dvSinopsis")
    parts = synopsis.xpath("./*[not(self::h4)]") if synopsis is not None else []
    description = "\n\n".join(_text(node) for node in parts if _text(node)) or None
    topics = [part.strip() for part in re.split(r"[-/;]", values.get("materia", "")) if _known(part.strip())]
    # BL is an explicit label, unlike generic narrative genres or the broad BIC.
    topics = ["boys love" if classification_key(value) == "bl" else value for value in topics]
    work_type, demographic, classification_note = _classification(title, description, topics)

    raw_format = _known(values.get("formato", ""))
    book_format = normalize_yumekai_format(raw_format)
    format_note = ""
    if re.search(r"\b(?:pack|box(?:\s+set)?|cofre|estuche)\b", title, re.I):
        book_format = "Box set"
    elif book_format not in BOOK_FORMATS:
        book_format = None
        if raw_format:
            format_note = f"Formato de ZonaLibros sin equivalencia: {raw_format}. Revisar manualmente."
    page_text = values.get("paginas", "").strip()
    pages = int(page_text) if re.fullmatch(r"[0-9]{1,10}", page_text) else None
    if pages is not None and not 1 <= pages <= 4_294_967_295:
        pages = None
    price = _value(page, "importe3PVP").replace("\u00a0", " ").strip()
    price_match = re.fullmatch(r"([0-9]{1,8}(?:[.,][0-9]{1,2})?)\s*€?", price)
    image = _element(page, "imgLibro")
    image_url = urljoin(source_url, image.get("src", "")) if image is not None and image.get("src") else None
    if image_url:
        image_parts = urlsplit(image_url)
        if (image_parts.scheme != "https" or image_parts.hostname not in {
            "imagenes.zonalibros.com", "norma.zonalibros.com",
        } or image_parts.username or image_parts.password):
            image_url = None
    series = _known(values.get("coleccion", ""))
    inferred = analyze_title(title, isbn, known_series=(series,) if series else ())
    availability, status = _availability(page)
    return NormaDetails(
        title=title, author=author or None, description=description,
        series=series or inferred.series,
        volume=None if book_format == "Box set" else inferred.volume,
        pages=pages, book_format=book_format,
        retail_price=price_match.group(1).replace(",", ".") if price_match else None,
        image_url=image_url, work_type=work_type, demographic=demographic,
        classification_note=classification_note, availability=availability,
        yumekai_status=status, format_note=format_note,
    )


class ZonaLibrosClient:
    """One authenticated, sequential session per batch, with no cookie file."""
    def __init__(self, stop_requested=None):
        self.stop = stop_requested if stop_requested is not None else Event()
        self.cookies = CookieJar()
        context = truststore.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
        self.opener = build_opener(
            HTTPSHandler(context=context), _PortalRedirects(), HTTPCookieProcessor(self.cookies),
        )
        self.authenticated = False
        self._search_page = None
        self._search_url = None

    def close(self):
        self.cookies.clear()
        self.authenticated = False
        self._search_page = None
        self._search_url = None

    def _fetch(self, url, *, data=None, referer=None):
        if self.stop.is_set():
            raise NormaLookupCancelled()
        if not _is_portal_url(url):
            raise ZonaLibrosError("La dirección no pertenece al portal HTTPS de Norma ZonaLibros.")
        headers = {"User-Agent": "YumekaiImporter/1.0", "Cache-Control": "no-cache"}
        if data is not None:
            headers.update({"Content-Type": "application/x-www-form-urlencoded", "Referer": referer or LOGIN_URL})
        request = Request(url, data=data, headers=headers)
        try:
            with self.opener.open(request, timeout=20) as response:
                final = response.geturl()
                if not _is_portal_url(final):
                    raise ZonaLibrosError("Respuesta fuera del portal HTTPS de Norma.")
                body = response.read(MAX_BYTES + 1)
                charset = response.headers.get_content_charset() or "utf-8"
        except HTTPError as error:
            if error.code in {401, 403}:
                raise ZonaLibrosAuthError("ZonaLibros no permite el acceso. Revisa el acceso de Norma antes de reintentar.") from None
            raise ZonaLibrosError(f"ZonaLibros ha respondido HTTP {error.code}. Consulta detenida; puedes reintentar más tarde.") from None
        except (URLError, TimeoutError, OSError):
            raise ZonaLibrosError("No se pudo conectar con ZonaLibros. Comprueba la conexión y vuelve a intentarlo.") from None
        if self.stop.is_set():
            raise NormaLookupCancelled()
        if len(body) > MAX_BYTES:
            raise ZonaLibrosError("La respuesta de ZonaLibros es demasiado grande.")
        page = html.fromstring(body, parser=html.HTMLParser(encoding=charset))
        if page.xpath('//*[contains(@class,"g-recaptcha") or contains(@class,"h-captcha")]'):
            raise ZonaLibrosAuthError("ZonaLibros solicita una verificación manual. La consulta se ha detenido.")
        return page, final

    def login(self, credentials):
        if not credentials or not all((credentials.tax_id.strip(), credentials.username.strip(), credentials.password)):
            raise ZonaLibrosAuthError("Faltan NIF/CIF, usuario o contraseña de Norma ZonaLibros.")
        for secret in (credentials.tax_id, credentials.username, credentials.password):
            register_secret(secret)
        page, final = self._fetch(LOGIN_URL)
        forms = page.xpath('//form[.//input[@id="inpPassword"]]')
        if len(forms) != 1:
            raise ZonaLibrosAuthError("El formulario de acceso de ZonaLibros ha cambiado. Consulta detenida.")
        form = forms[0]
        target = urljoin(final, form.get("action") or final)
        if not _is_portal_url(target) or urlsplit(target).path.casefold() != "/login.aspx":
            raise ZonaLibrosAuthError("Destino de acceso de ZonaLibros no reconocido.")
        fields = {node.get("name"): node.get("value", "")
                  for node in form.xpath('.//input[@type="hidden"][@name]')}
        for identifier, value in (("inpNIF", credentials.tax_id.strip()),
                                  ("inpuUser", credentials.username.strip()),
                                  ("inpPassword", credentials.password)):
            nodes = form.xpath('.//input[@id=$identifier]', identifier=identifier)
            if len(nodes) != 1 or not nodes[0].get("name"):
                raise ZonaLibrosAuthError("El formulario de acceso de ZonaLibros ha cambiado.")
            fields[nodes[0].get("name")] = value
        # This is the event emitted by the portal's Login2.js validaCamposLogin.
        fields.update({"__EVENTTARGET": "btnLogin_Click", "__EVENTARGUMENT": ""})
        page, final = self._fetch(target, data=urlencode(fields).encode("utf-8"))
        if (urlsplit(final).path.casefold() == "/login.aspx"
                or not _signed_in(page)):
            raise ZonaLibrosAuthError("ZonaLibros no ha confirmado el acceso. Revisa NIF/CIF, usuario y contraseña en «Acceso ZonaLibros…».")
        self.authenticated = True
        self._search_page, self._search_url = page, final

    def _get_authenticated(self, url, *, data=None, referer=None):
        if not self.authenticated:
            raise ZonaLibrosAuthError("Inicia sesión en Norma ZonaLibros antes de consultar.")
        page, final = self._fetch(url, data=data, referer=referer)
        if (urlsplit(final).path.casefold() == "/login.aspx"
                or not _signed_in(page)):
            self.authenticated = False
            raise ZonaLibrosAuthError("La sesión de ZonaLibros ha caducado. Vuelve a iniciar la consulta con tu acceso de Norma.")
        if urlsplit(final).path.casefold() == "/clientes/error.aspx":
            raise ZonaLibrosError("ZonaLibros ha devuelto su página de error al consultar. No se ha modificado ninguna ficha.")
        self._search_page, self._search_url = page, final
        return page, final

    def _search_isbn(self, isbn):
        if self._search_page is None:
            self._get_authenticated(HOME_URL)
        page, current = self._search_page, self._search_url
        forms = page.xpath('//form[.//input[@id="txtBuscar"]]')
        if len(forms) != 1:
            raise ZonaLibrosError("No se reconoce el formulario de búsqueda de ZonaLibros.")
        form = forms[0]
        target = urljoin(current, form.get("action") or current)
        if (not _is_portal_url(target) or urlsplit(target).path.casefold() not in {
            "/clientes/inicio.aspx", "/clientes/fichaarticulo.aspx", "/clientes/buscalibros.aspx",
        }):
            raise ZonaLibrosError("Destino del formulario de búsqueda de ZonaLibros no reconocido.")
        inputs = form.xpath('.//input[@id="txtBuscar"][@name]')
        links = form.xpath('.//a[@id="lnkBuscar"]/@href')
        if len(inputs) != 1 or len(links) != 1:
            raise ZonaLibrosError("Los controles de búsqueda de ZonaLibros han cambiado.")
        event = re.search(r"(?:__doPostBack\(|WebForm_PostBackOptions\()\s*['\"]([^'\"]+)", links[0])
        if event is None or event.group(1) not in {"ctl00$lnkBuscar", "lnkBuscar"}:
            raise ZonaLibrosError("El evento de búsqueda de ZonaLibros no es reconocible.")
        # Post only Web Forms state, select values and the ISBN. Never submit cart quantities.
        fields = {node.get("name"): node.get("value", "") for node in
                  form.xpath('.//input[@type="hidden"][@name]') if node.get("name").startswith("__")}
        for select in form.xpath('.//select[@name][not(@disabled)]'):
            options = select.xpath('./option[@selected]|./optgroup/option[@selected]')
            if not options:
                options = select.xpath('./option|./optgroup/option')[:1]
            if options:
                fields[select.get("name")] = options[0].get("value", _text(options[0]))
        types = form.xpath('.//select[@id="ddlBuscarPor"][@name]')
        if types:
            fields[types[0].get("name")] = "T"
        fields[inputs[0].get("name")] = isbn
        fields.update({"__EVENTTARGET": event.group(1), "__EVENTARGUMENT": ""})
        return self._get_authenticated(target, data=urlencode(fields).encode("utf-8"), referer=current)

    def lookup(self, isbn, *, stock_only=False):
        normalized = normalize_review_identifier(str(isbn or ""))
        if not re.fullmatch(r"[0-9]{13}", normalized):
            return NormaLookupResult(normalized, "not_found", message="El código no permite confirmar un ISBN-13 en ZonaLibros.")
        # A direct BuscaLibros.aspx?query=ISBN GET returns the site's HTTP-400 error page.
        # Use the same form postback as its Buscar link, including the current view state.
        page, final = self._search_isbn(normalized)
        if _element(page, "tblLibro") is not None:
            candidates = [(page, final)]
        else:
            candidates = []
            seen = set()
            results = page.get_element_by_id("panResultados", None)
            for link in results.xpath('.//a[@href]') if results is not None else []:
                target = urljoin(final, link.get("href"))
                if (_is_portal_url(target) and urlsplit(target).path.casefold() == "/clientes/fichaarticulo.aspx"
                        and target not in seen):
                    seen.add(target)
                    candidates.append(target)
                    if len(candidates) == MAX_CANDIDATES:
                        break
            if not candidates and not re.search(r"no (?:se han encontrado|obtuvo).*(?:resultados|resultado)", _text(page), re.I):
                raise ZonaLibrosError("No se pudo leer el resultado de ZonaLibros. Se conservan los datos anteriores.")
        for candidate in candidates:
            detail, url = self._get_authenticated(candidate) if isinstance(candidate, str) else candidate
            try:
                parser = parse_zonalibros_stock if stock_only else parse_zonalibros_details
                details = parser(detail, normalized, url)
            except NormaEditionMismatch:
                continue
            return NormaLookupResult(normalized, "found", details, url, "ISBN de la edición confirmado en Norma ZonaLibros.")
        return NormaLookupResult(normalized, "not_found", message=(
            "No se ha confirmado una ficha de ZonaLibros con ese ISBN. Se conservan los datos anteriores."
        ))
