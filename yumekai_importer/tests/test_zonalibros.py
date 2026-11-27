"""Exercise the observed Web Forms contract using synthetic, credential-free pages."""
from email.message import Message
from html import escape
import json
from types import SimpleNamespace
from unittest.mock import Mock
from urllib.error import HTTPError
from urllib.parse import parse_qs
from urllib.request import Request

from lxml import html
import pytest
from PySide6.QtWidgets import QApplication, QDialog, QLineEdit

from yumekai_importer.catalog.norma_review import norma_review_changes
from yumekai_importer.importers.norma import zonalibros as portal
from yumekai_importer.importers.norma.lookup import NormaEditionMismatch, NormaLookupResult
from yumekai_importer.storage import norma_credentials as storage
from yumekai_importer.ui.widgets.norma_access_dialog import NormaAccessDialog
from yumekai_importer.ui.windows.pending_review_window import PendingReviewWindow
from yumekai_importer.ui.workers import norma_recheck_worker as workers


ISBN = "9788467945850"
OTHER = "9788467968705"
URL = portal.BASE_URL + "/Clientes/FichaArticulo.aspx?Libro=MAN.00015557"
CREDS = portal.NormaCredentials("test-tax-id", "test-user", "test-password")
LOGIN = '''<html><meta charset="utf-8"><form method="post" action="./Login.aspx">
    <input type="hidden" name="__VIEWSTATE" value="synthetic-state">
    <input type="hidden" name="__EVENTVALIDATION" value="synthetic-validation">
    <input id="inpNIF" name="ctl00$inpNIF"><input id="inpuUser" name="ctl00$inpuUser">
    <input id="inpPassword" name="ctl00$inpPassword" type="password">
    <button id="btnLogin" type="submit" onclick="validaCamposLogin(event);">Entrar</button>
    </form></html>'''
def search_form(*, prefix="ctl00$", action="./Inicio.aspx", state="synthetic-search-state"):
    return f'''<form method="post" action="{escape(action)}">
    <input type="hidden" name="__VIEWSTATE" value="{state}">
    <input type="hidden" name="__EVENTVALIDATION" value="synthetic-validation">
    <input type="hidden" name="ctl00$MainContent$txtArticuloCesta" value="never-submit-cart">
    <input name="ctl00$MainContent$txtQty" value="1">
    <input id="txtBuscar" name="{prefix}txtBuscar">
    <select id="ddlBuscarPor" name="{prefix}ddlBuscarPor"><option value="T">Todos</option></select>
    <select name="{prefix}cmbIdioma"><option value="esp" selected>Castellano</option></select>
    <a id="lnkBuscar" href="javascript:__doPostBack('{prefix}lnkBuscar','')">Buscar</a></form>'''


HOME = '<html><a id="ctl00_lblNombreUsuario">Test shop</a>' + search_form() + '</html>'


def markup(*, isbn=ISBN, title="EJEMPLO 01", status="Stock: Sí", hint="Disponible para su envío",
           binding="RUSTICA CON SOLAPAS", pages="320", topic="VIDEOJUEGOS-N/D-N/D",
           description="Descubre este manhwa de aventuras."):
    return f'''<html><meta charset="utf-8"><a id="ctl00_lblNombreUsuario">Test shop</a>
    {search_form(action='./FichaArticulo.aspx?Libro=MAN.00015557', state='article-state-' + isbn)}
    <div id="ctl00_MainContent_panFicha"><span id="ctl00_MainContent_txtTitulo">{escape(title)}</span>
    <span id="ctl00_MainContent_txtAutor"><a>Autora A</a><a>Autor B</a></span>
    <span id="ctl00_MainContent_importe3PVP">14,95 €</span>
    <span id="ctl00_MainContent_lblDisponible"><span title="{escape(hint)}">{escape(status)}</span></span>
    <img id="ctl00_MainContent_imgLibro" src="https://imagenes.zonalibros.com/img/113/{isbn}.jpg">
    <table id="ctl00_MainContent_tblLibro">
    <tr><td>Colección:</td><td>EJEMPLO</td><td>Materia:</td><td>{escape(topic)}</td></tr>
    <tr><td>ISBN:</td><td>{isbn}</td><td>EAN:</td><td>{isbn}</td><td>Referencia:</td><td>MAN.00015557</td></tr>
    <tr><td>Idioma:</td><td>CASTELLANO</td><td>Formato:</td><td>{escape(binding)}</td></tr>
    <tr><td>Medidas:</td><td>14,8x21</td><td>Páginas:</td><td>{escape(pages)}</td><td>Peso:</td><td>649</td></tr>
    </table><div id="ctl00_MainContent_dvSinopsis"><h4>Sinopsis:</h4><div>{escape(description)}</div></div>
    <div id="ctl00_MainContent_divMimsmoAutor"><span>Recomendación de otra edición</span>
    <span>ISBN {OTHER}, formato CARTONE, 500 páginas, el manhua de otra persona.</span></div></div></html>'''


def parse(**kwargs):
    return portal.parse_zonalibros_details(html.fromstring(markup(**kwargs)), ISBN, URL)


def product(**kwargs):
    return {"isbn": ISBN, "title": "EJEMPLO 01", "publisher": "Norma",
            "retail_price": "14.95", "sale_price": "14.20", "yumekai_status": "instock",
            "review_status": "pending_review", "updated_at": "2026-11-26 12:00:00", **kwargs}


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


@pytest.mark.parametrize("status,hint,expected", [
    ("Stock: Sí", "Disponible para su envío", "yk_on_demand"),
    ("Disponible en fabricante", "Disponible", "outofstock"),
    ("Stock: No", "No disponible (DESCATALOGADO)", "outofstock"),
    ("Stock: No", "EN REIMPRESIÓN", None),
    ("Stock: No", "Disponible para su envío", None),
    ("", "", None),
])
def test_agreed_stock_values_override_excel_and_unknowns_require_review(status, hint, expected):
    details = parse(status=status, hint=hint)
    assert details.yumekai_status == expected
    result = NormaLookupResult(ISBN, "found", details, URL)
    changes, note = norma_review_changes(product(), result)
    assert changes["yumekai_status"] == expected
    assert "ZonaLibros" in note
    if expected is None:
        assert "Por comprobar" in note


def test_one_article_supplies_bibliography_stock_and_classification():
    details = parse()
    assert details.pages == 320 and details.book_format == "Rústica con solapas"
    assert details.author == "Autora A / Autor B" and details.retail_price == "14.95"
    assert details.work_type == "Manhwa" and details.demographic is None
    assert details.series == "EJEMPLO" and details.volume == "1"
    assert details.yumekai_status == "yk_on_demand"
    assert details.image_url.endswith(ISBN + ".jpg")
    assert "Recomendación" not in details.description and "Sinopsis:" not in details.description


@pytest.mark.parametrize("raw,expected", [
    ("RUS+SOBREC", "Rústica con sobrecubierta"),
    ("RUS+SOBREC.", "Rústica con sobrecubierta"),
    ("RUSTICA + SOBRECUB.", "Rústica con sobrecubierta"),
    ("RUSTICA CON SOBRECUB", "Rústica con sobrecubierta"),
    ("RUSTICA + 2 SOBRECUB", "Rústica con sobrecubierta"),
    ("RUSTICA CON SOLAPAS", "Rústica con solapas"),
    ("RUSTICA + SOLAPAS", "Rústica con solapas"),
    ("CARTONE", "Tapa dura"),
])
def test_all_agreed_formats_are_read_from_the_portal(raw, expected):
    assert parse(binding=raw).book_format == expected


@pytest.mark.parametrize("pages", ["0", "", "N/D", "320 letras", "-3", "4294967296"])
def test_missing_or_invalid_pages_are_not_imported(pages):
    details = parse(pages=pages)
    assert details.pages is None
    changes, _ = norma_review_changes(product(pages=99), NormaLookupResult(ISBN, "found", details, URL))
    assert "pages" not in changes


def test_unknown_format_stays_pending_with_its_original_label_in_the_report():
    details = parse(binding="OTRO FORMATO")
    assert details.book_format is None and "OTRO FORMATO" in details.format_note


def test_box_and_zero_page_case_does_not_become_a_single_paperback_volume():
    details = parse(title="THE LEGEND OF ZELDA PERFECT EDITION BOX", binding="RUS+SOBREC", pages="0")
    assert details.book_format == "Box set" and details.volume is None and details.pages is None


def test_other_edition_is_rejected_even_when_recommendations_include_the_requested_isbn():
    with pytest.raises(NormaEditionMismatch):
        parse(isbn=OTHER)


@pytest.mark.parametrize("topic,expected", [("SHONEN-N/D-N/D", "Shonen"),
    ("SEINEN-N/D-N/D", "Seinen"), ("SHOJO-N/D-N/D", "Shōjo"),
    ("BL-COSTUMBRISMO-N/D-N/D", "Yaoi / BL"), ("INFANTIL- HUMOR-N/D-N/D", None)])
def test_only_explicit_topic_labels_supply_demography(topic, expected):
    details = parse(topic=topic, description="Una historia de aventuras.")
    assert details.work_type is None and details.demographic == expected
    changes, _ = norma_review_changes(product(work_type="Manga"), NormaLookupResult(ISBN, "found", details, URL))
    assert changes.get("demographic") == expected


def test_filled_fields_are_compared_with_the_confirmed_edition():
    result = NormaLookupResult(ISBN, "found", parse(), URL)
    changes, _ = norma_review_changes(product(book_format="Box set", pages=99, author="Manual",
        description="Texto manual", series="Mi serie", volume="5", work_type="Manhua", image_url="https://yumekai.es/manual.jpg"), result)
    assert changes["yumekai_status"] == "yk_on_demand"
    for field in ("book_format", "pages", "author", "description", "series", "volume", "work_type", "image_url"):
        assert changes[field] == getattr(result.details, field)
    changes, _ = norma_review_changes(product(pages=0), result)
    assert changes["pages"] == 320


class Response:
    def __init__(self, text, url):
        self.body = text.encode()
        self.url = url
        self.headers = Message()
        self.headers["Content-Type"] = "text/html; charset=utf-8"
    def __enter__(self): return self
    def __exit__(self, *args): pass
    def read(self, size): return self.body[:size]
    def geturl(self): return self.url


def client_with_responses(*responses):
    client = portal.ZonaLibrosClient()
    client.opener = Mock()
    client.opener.open.side_effect = [Response(text, url) for text, url in responses]
    # Represents the authenticated home document retained after login.
    client._search_page = html.fromstring(HOME)
    client._search_url = portal.HOME_URL
    return client


def test_login_preserves_webforms_state_and_posts_the_observed_login_event():
    client = client_with_responses((LOGIN, portal.LOGIN_URL), (HOME, portal.HOME_URL))
    client.login(CREDS)
    assert client.authenticated
    request = client.opener.open.call_args.args[0]
    fields = parse_qs(request.data.decode(), keep_blank_values=True)
    assert request.get_method() == "POST" and request.full_url == portal.LOGIN_URL
    assert fields["__EVENTTARGET"] == ["btnLogin_Click"]
    assert fields["__VIEWSTATE"] == ["synthetic-state"]
    assert fields["__EVENTVALIDATION"] == ["synthetic-validation"]
    assert fields["ctl00$inpNIF"] == [CREDS.tax_id]
    assert fields["ctl00$inpuUser"] == [CREDS.username]
    assert fields["ctl00$inpPassword"] == [CREDS.password]
    assert CREDS.password not in request.full_url and CREDS.password not in repr(CREDS)
    client.close()
    assert not client.authenticated


def test_bad_login_is_reported_once_without_disclosing_credentials():
    client = client_with_responses((LOGIN, portal.LOGIN_URL), (LOGIN, portal.LOGIN_URL))
    with pytest.raises(portal.ZonaLibrosAuthError) as error:
        client.login(CREDS)
    assert client.opener.open.call_count == 2 and not client.authenticated
    assert CREDS.password not in str(error.value)


def test_credentials_never_post_to_a_form_on_another_domain():
    unsafe = LOGIN.replace('./Login.aspx', 'https://other.example/Login.aspx')
    client = client_with_responses((unsafe, portal.LOGIN_URL))
    with pytest.raises(portal.ZonaLibrosAuthError):
        client.login(CREDS)
    assert client.opener.open.call_count == 1


@pytest.mark.parametrize("target", ["http://norma.zonalibros.com/Login.aspx",
    "https://other.example/Login.aspx", "https://norma.zonalibros.com.evil.example/Login.aspx"])
def test_redirect_is_rejected_before_a_second_request(target):
    with pytest.raises(portal.ZonaLibrosError):
        portal._PortalRedirects().redirect_request(Request(portal.LOGIN_URL, data=b"private"),
                                                    None, 302, "Found", {}, target)


def test_expired_session_never_uses_the_public_login_catalogue_as_a_match():
    client = client_with_responses((LOGIN, portal.LOGIN_URL))
    client.authenticated = True
    with pytest.raises(portal.ZonaLibrosAuthError):
        client.lookup(ISBN)
    assert client.opener.open.call_count == 1 and not client.authenticated


def test_isbn_search_reads_one_detail_page_and_ignores_unrelated_links():
    results = f'''<html><a id="ctl00_lblNombreUsuario">Test shop</a><div id="panResultados">
        <a href="https://other.example/Clientes/FichaArticulo.aspx?Libro=bad">Other</a>
        <a href="/Clientes/Pedido.aspx">Order</a><a href="{URL}">Article</a>
        <a href="{URL}">Same article image</a></div></html>'''
    client = client_with_responses((results, portal.BASE_URL + "/Clientes/BuscaLibros.aspx"), (markup(), URL))
    client.authenticated = True
    result = client.lookup(ISBN)
    assert result.status == "found" and result.details.pages == 320
    assert client.opener.open.call_count == 2
    assert client.opener.open.call_args.args[0].full_url == URL


def test_single_result_direct_ficha_and_real_no_results_are_supported():
    client = client_with_responses((markup(), URL))
    client.authenticated = True
    assert client.lookup(ISBN).status == "found" and client.opener.open.call_count == 1
    empty = HOME.replace('</html>', '<p>No se han encontrado resultados</p></html>')
    client = client_with_responses((empty, portal.BASE_URL + "/Clientes/BuscaLibros.aspx"))
    client.authenticated = True
    assert client.lookup(ISBN).status == "not_found"


def test_unrecognized_search_response_is_an_error_not_an_absent_product():
    client = client_with_responses((HOME, portal.BASE_URL + "/Clientes/BuscaLibros.aspx"))
    client.authenticated = True
    with pytest.raises(portal.ZonaLibrosError):
        client.lookup(ISBN)


def test_isbn_search_posts_current_form_state_instead_of_an_unusable_direct_url():
    client = client_with_responses((LOGIN, portal.LOGIN_URL), (HOME, portal.HOME_URL),
                                   (markup(), URL), (markup(isbn=OTHER), URL))
    client.login(CREDS)
    assert client.lookup(ISBN).status == "found"
    assert client.lookup(OTHER).status == "found"
    requests = [entry.args[0] for entry in client.opener.open.call_args_list]
    first, second = requests[2:]
    assert first.get_method() == second.get_method() == "POST"
    assert first.full_url == portal.HOME_URL and second.full_url == URL
    fields = parse_qs(first.data.decode(), keep_blank_values=True)
    assert fields["__EVENTTARGET"] == ["ctl00$lnkBuscar"]
    assert fields["ctl00$txtBuscar"] == [ISBN]
    assert fields["ctl00$ddlBuscarPor"] == ["T"]
    assert fields["ctl00$cmbIdioma"] == ["esp"]
    assert fields["__VIEWSTATE"] == ["synthetic-search-state"]
    assert not any("txtQty" in name or "ArticuloCesta" in name or "inpPassword" in name for name in fields)
    second_fields = parse_qs(second.data.decode())
    assert second_fields["__VIEWSTATE"] == ["article-state-" + ISBN]
    assert second_fields["ctl00$txtBuscar"] == [OTHER]
    assert second.get_header("Referer") == URL


def test_results_controls_without_the_master_page_prefix_keep_the_session_valid():
    results = '<html><a id="lblNombreUsuario">Test shop</a>' + search_form(
        prefix="", action="./BuscaLibros.aspx?query=previous", state="results-state")
    results += '<div id="panResultados"><a href="' + URL + '">Article</a></div></html>'
    client = client_with_responses((results, portal.BASE_URL + "/Clientes/BuscaLibros.aspx"), (markup(), URL))
    client.authenticated = True
    result = client.lookup(ISBN)
    assert result.status == "found" and client.authenticated

    client = client_with_responses((markup(), URL))
    client.authenticated = True
    client._search_page = html.fromstring(results)
    client._search_url = portal.BASE_URL + "/Clientes/BuscaLibros.aspx"
    assert client.lookup(ISBN).status == "found"
    fields = parse_qs(client.opener.open.call_args.args[0].data.decode())
    assert fields["__EVENTTARGET"] == ["lnkBuscar"] and fields["txtBuscar"] == [ISBN]


def test_portal_error_page_is_reported_as_a_site_error_without_expiring_the_session():
    error_page = HOME.replace('</html>', '<p>Error HTTP 400: se ha producido un error general.</p></html>')
    client = client_with_responses((error_page, portal.BASE_URL + "/Clientes/Error.aspx?aspxerrorpath=/Clientes/BuscaLibros.aspx"))
    client.authenticated = True
    with pytest.raises(portal.ZonaLibrosError, match="página de error") as error:
        client.lookup(ISBN)
    assert not isinstance(error.value, portal.ZonaLibrosAuthError)
    assert client.authenticated


@pytest.mark.parametrize("action", ["https://other.example/search", "./Pedido.aspx"])
def test_search_state_is_not_posted_to_unrelated_or_order_forms(action):
    client = client_with_responses()
    client.authenticated = True
    client._search_page = html.fromstring('<html>' + search_form(action=action) + '</html>')
    with pytest.raises(portal.ZonaLibrosError, match="Destino"):
        client.lookup(ISBN)
    client.opener.open.assert_not_called()


def test_rate_limit_is_not_retried_in_a_loop():
    client = portal.ZonaLibrosClient()
    client.opener = Mock()
    client.opener.open.side_effect = HTTPError(URL, 429, "Slow down", {}, None)
    with pytest.raises(portal.ZonaLibrosError, match="HTTP 429"):
        client._fetch(URL)
    assert client.opener.open.call_count == 1


def test_worker_reuses_one_login_and_stops_the_batch_on_session_failure(app, monkeypatch):
    client = Mock()
    first = NormaLookupResult(ISBN, "found", parse(), URL)
    client.lookup.side_effect = [first, portal.ZonaLibrosAuthError("Sesión caducada")]
    factory = Mock(return_value=client)
    monkeypatch.setattr(workers, "ZonaLibrosClient", factory)
    remember = Mock()
    monkeypatch.setattr(workers, "save_norma_credentials", remember)
    products = {ISBN: product(), OTHER: product(isbn=OTHER), "third": product(isbn="9788467961119")}
    worker = workers.NormaRecheckWorker(products, credentials=CREDS)
    worker.run()
    factory.assert_called_once()
    client.login.assert_called_once_with(CREDS)
    assert client.lookup.call_count == 2 and worker.results[ISBN] == first
    assert worker.results[OTHER].status == worker.results["third"].status == "error"
    client.close.assert_called_once()
    assert worker.credentials is None
    remember.assert_not_called()


def test_worker_saves_only_after_successful_login_and_explicit_remember_choice(app, monkeypatch):
    client = Mock()
    client.lookup.return_value = NormaLookupResult(ISBN, "found", parse(), URL)
    calls = []
    client.login.side_effect = lambda c: calls.append("login")
    monkeypatch.setattr(workers, "ZonaLibrosClient", lambda stop: client)
    save = Mock(side_effect=lambda c: calls.append("save"))
    monkeypatch.setattr(workers, "save_norma_credentials", save)
    worker = workers.NormaRecheckWorker({ISBN: product()}, credentials=CREDS, remember_access=True)
    worker.run()
    assert calls == ["login", "save"]
    save.reset_mock()
    client.login.side_effect = portal.ZonaLibrosAuthError("Acceso no confirmado")
    worker = workers.NormaRecheckWorker({ISBN: product()}, credentials=CREDS, remember_access=True)
    worker.run()
    save.assert_not_called()
    assert worker.results[ISBN].status == "error"


def test_worker_stopping_retains_completed_results_and_clears_credentials(app, monkeypatch):
    client = Mock()
    monkeypatch.setattr(workers, "ZonaLibrosClient", lambda stop: client)
    worker = workers.NormaRecheckWorker({ISBN: product(), OTHER: product(isbn=OTHER)}, credentials=CREDS)
    def first(isbn):
        worker.stop_requested.set()
        return NormaLookupResult(isbn, "found", parse(), URL)
    client.lookup.side_effect = first
    worker.run()
    assert worker.results[ISBN].status == "found" and worker.results[OTHER].status == "cancelled"
    assert worker.credentials is None


def test_keyring_roundtrip_uses_a_separate_service(monkeypatch):
    payload = {}
    monkeypatch.setattr(storage.keyring, "set_password", lambda service, account, value: payload.update(
        service=service, account=account, value=value))
    monkeypatch.setattr(storage.keyring, "get_password", lambda service, account: payload["value"])
    storage.save_norma_credentials(CREDS)
    assert payload["service"] == "Yumekai Importador - Norma ZonaLibros"
    assert storage.load_norma_credentials() == CREDS
    assert json.loads(payload["value"])["password"] == CREDS.password


def test_access_dialog_requires_all_fields_and_does_not_remember_by_default(app):
    dialog = NormaAccessDialog()
    assert dialog.password.echoMode() == QLineEdit.EchoMode.Password
    assert not dialog.remember_check.isChecked()
    dialog.accept()
    assert dialog.result() != QDialog.DialogCode.Accepted and dialog.credentials is None
    dialog.tax_id.setText(CREDS.tax_id)
    dialog.username.setText(CREDS.username)
    dialog.password.setText(CREDS.password)
    dialog.accept()
    assert dialog.credentials == CREDS and not dialog.remember
    dialog.deleteLater()


def test_forget_skips_absent_credentials_and_reports_real_deletion_failures(monkeypatch):
    delete = Mock(side_effect=storage.keyring.errors.PasswordDeleteError("Cannot delete"))
    monkeypatch.setattr(storage.keyring, "delete_password", delete)
    monkeypatch.setattr(storage.keyring, "get_password", lambda *a: None)
    storage.forget_norma_credentials()
    delete.assert_not_called()
    monkeypatch.setattr(storage.keyring, "get_password", lambda *a: "stored-access")
    with pytest.raises(storage.keyring.errors.PasswordDeleteError):
        storage.forget_norma_credentials()


def test_cancel_access_does_not_start_a_query_or_clear_previous_results(app, monkeypatch):
    window = PendingReviewWindow()
    window._products["pending_review"] = {ISBN: product()}
    window._selected = {ISBN}
    window._sd_results = {"previous": {"supplier": "norma", "note": "Previous"}}
    monkeypatch.setattr("yumekai_importer.ui.windows.pending_review_window.load_norma_credentials", lambda: None)
    monkeypatch.setattr(window, "_configure_norma_access", lambda: False)
    factory = Mock()
    monkeypatch.setattr("yumekai_importer.ui.windows.pending_review_window.NormaRecheckWorker", factory)
    window._recheck_norma()
    factory.assert_not_called()
    assert window._sd_results["previous"]["note"] == "Previous"
    window.close()


def test_field_selection_can_save_only_portal_stock_and_pages(app, monkeypatch):
    window = PendingReviewWindow()
    original = product()
    window._products["pending_review"] = {ISBN: original}
    window._norma_worker = SimpleNamespace(products={ISBN: original},
        results={ISBN: NormaLookupResult(ISBN, "found", parse(), URL)}, error=None, deleteLater=Mock())
    selected = {ISBN: {"pages": 320, "yumekai_status": "yk_on_demand"}}
    monkeypatch.setattr("yumekai_importer.ui.windows.pending_review_window.review_changes", lambda *a, **k: selected)
    window._start_action = Mock()
    window._finish_norma_recheck()
    action, entries = window._start_action.call_args.args
    assert action == "save" and entries[0]["changes"] == selected[ISBN]
    assert "password" not in json.dumps(window._drafts)
    window._drafts.clear()
    window.close()
