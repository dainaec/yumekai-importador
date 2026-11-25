import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
from dataclasses import replace
from email.message import Message
from threading import Event, Lock
from time import sleep, monotonic
import unittest
from unittest.mock import patch

from lxml import html
from PySide6.QtCore import QCoreApplication, QEvent
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from yumekai_importer.catalog.sd_review import sd_review_changes
from yumekai_importer.importers.sd.details import SdDetails, _parse_details
from yumekai_importer.importers.sd import lookup, stock
from yumekai_importer.importers.sd.lookup import SdLookupResult
from yumekai_importer.ui.workers import sd_recheck_worker
from yumekai_importer.ui.windows.pending_review_window import PendingReviewWindow
from tests.test_review_workflow import FakeApi, product

ISBN = '9788412930627'
OTHER = '9791399163087'
URL = 'https://www.sddistribuciones.com/ficha-id-kbkbiblio01'
DETAILS = SdDetails('Manga', 'Seinen', 200, 'RÚSTICA', 'Autor SD', 'Sinopsis SD',
                    publisher='Editorial SD', retail_price='10.95',
                    image_url='https://example.com/portada.jpg', language='Castellano')


def detail_page(isbn=ISBN, state='Stock: Sí'):
    return html.fromstring(f'''<html><span id="txtISBN">{isbn}</span>
        <span id="txtTematicaTema">MANGA</span><span id="txtTematicaMateria">SEINEN / DRAMA</span>
        <span id="txtNumPag2">200</span><span id="txtFormatoTapa">RÚSTICA</span>
        <span id="txtAutorFA">Autor SD</span><span id="txtSinpsis">Texto de prueba</span>
        <span id="importe1PVP">10,95 €</span><span id="txtFamilia">Editorial SD</span>
        <span id="txtIdiomaFA">Castellano</span>
        <div id="dvContainerEstadoFichaArticulo">{state}</div>
        <div id="containerPortada"><img src="https://example.com/portada.jpg"/></div>
        <div class="fileproduct"><span class="dvISBN">{OTHER}</span>
        <span class="estado">Stock: Sí</span><div class="filetitle"><a href="/otro">Otra obra</a></div></div></html>''')


def list_page(isbn=ISBN, state='Stock: Sí'):
    return html.fromstring(f'''<html><div class="fileproduct"><span class="dvISBN">{isbn}</span>
        <span class="estado">{state}</span><div class="filetitle"><a href="{URL}">Ficha</a></div></div></html>''')


class SdLookupTests(unittest.TestCase):
    def test_direct_redirect_uses_main_item_not_related_product_stock(self):
        with patch.object(lookup, '_fetch_page', return_value=(detail_page(state='Consultar disponibilidad'), URL)):
            result = lookup.lookup_sd_isbn(ISBN)
        self.assertEqual(result.status, 'found')
        self.assertIsNone(result.available)
        self.assertEqual(result.details.author, 'Autor SD')
        self.assertEqual(result.details.pages, 200)
        self.assertEqual(result.details.demographic, 'Seinen')

    def test_each_manual_check_is_fresh_instead_of_reusing_cached_details(self):
        with patch.object(lookup, '_fetch_page', side_effect=[(detail_page(state='Stock: Sí'), URL),
                                                           (detail_page(state='Stock: No'), URL)]) as fetch:
            self.assertTrue(lookup.lookup_sd_isbn(ISBN).available)
            self.assertFalse(lookup.lookup_sd_isbn(ISBN).available)
            self.assertEqual(fetch.call_count, 2)

    def test_exact_list_result_and_detail_are_verified_by_isbn(self):
        with patch.object(lookup, '_fetch_page', side_effect=[(list_page(), URL), (detail_page(), URL)]):
            result = lookup.lookup_sd_isbn(ISBN)
        self.assertEqual(result.details.work_type, 'Manga')
        self.assertTrue(result.available)
        with patch.object(lookup, '_fetch_page', side_effect=[(list_page(), URL), (detail_page(OTHER), URL)]):
            result = lookup.lookup_sd_isbn(ISBN)
        self.assertIsNone(result.details)
        self.assertTrue(result.available)
        self.assertIn('no coincide', result.message)

    def test_no_match_is_distinct_from_out_of_stock_or_bad_response(self):
        empty = html.fromstring('<html><div id="panNoResultados">Sin resultados</div></html>')
        with patch.object(lookup, '_fetch_page', return_value=(empty, URL)):
            result = lookup.lookup_sd_isbn(ISBN)
        self.assertEqual(result.status, 'not_found')
        self.assertIsNone(result.available)
        with patch.object(lookup, '_fetch_page', return_value=(list_page(OTHER), URL)):
            self.assertEqual(lookup.lookup_sd_isbn(ISBN).status, 'not_found')
        with patch.object(lookup, '_fetch_page', return_value=(html.fromstring('<html>Bloqueo temporal</html>'), URL)):
            with self.assertRaisesRegex(ValueError, 'sin una ficha'):
                lookup.lookup_sd_isbn(ISBN)

    def test_pack_eans_and_codes_without_isbn_checksum_are_queried(self):
        for code in ('8424248928490', '1234567890123', '12345678'):
            with self.subTest(code=code):
                with patch.object(lookup, '_fetch_page', return_value=(detail_page(isbn=code), URL)) as fetch:
                    result = lookup.lookup_sd_isbn(code)
                fetch.assert_called_once()
                self.assertEqual(result.status, 'found')
                self.assertEqual(result.isbn, code)
                self.assertEqual(result.details.pages, 200)

    def test_empty_code_does_not_search_the_whole_catalog(self):
        with patch.object(lookup, '_fetch_page') as fetch:
            with self.assertRaisesRegex(ValueError, 'no tiene un código'):
                lookup.lookup_sd_isbn('')
            fetch.assert_not_called()

    def test_stock_is_kept_when_exact_card_has_no_detail_link(self):
        page = list_page()
        for node in page.xpath('//a'):
            node.drop_tree()
        with patch.object(lookup, '_fetch_page', return_value=(page, URL)):
            result = lookup.lookup_sd_isbn(ISBN)
        self.assertEqual(result.status, 'found')
        self.assertTrue(result.available)
        self.assertIsNone(result.details)
        self.assertIn('sin enlace', result.message)

    def test_transient_http_error_is_retried_and_cancellation_stops_retry(self):
        class Response:
            headers = Message()
            def __enter__(self): return self
            def __exit__(self, *_): pass
            def geturl(self): return URL
            def read(self, _): return b'<html><span id="txtISBN">9788412930627</span></html>'
        stop = Event()
        with patch.object(stop, 'wait', return_value=False), \
             patch.object(lookup, 'urlopen', side_effect=[lookup.HTTPError(URL, 503, 'Busy', {}, None), Response()]) as opened:
            lookup._fetch_page(URL, stop)
            self.assertEqual(opened.call_count, 2)
        stop.set()
        with patch.object(lookup, 'urlopen') as opened:
            with self.assertRaises(lookup.SdLookupCancelled): lookup._fetch_page(URL, stop)
            opened.assert_not_called()

    def test_unknown_availability_is_never_out_of_stock(self):
        self.assertIsNone(stock._availability('Consultar disponibilidad'))
        self.assertIsNone(stock._availability('PRÓXIMA PUBLICACIÓN'))
        self.assertFalse(stock._availability('Stock: No'))
        self.assertTrue(stock._availability('Stock: Sí'))

    def test_invalid_sd_reference_is_reported_instead_of_silently_ignored(self):
        with patch.object(stock, 'read_sd_stock') as read:
            values, errors = stock.read_sd_stock_batches({ISBN: 'referencia sin prefijo'})
        read.assert_not_called()
        self.assertEqual(values, {})
        self.assertIn('no reconocibles', errors[0])


class MergeTests(unittest.TestCase):
    def test_fills_missing_metadata_and_applies_sd_stock_even_to_store_stock(self):
        p = product(author='Mi autora', retail_price='9.00', pages=None, book_format=None,
                    description='', yumekai_status='instock')
        changes, note = sd_review_changes(p, SdLookupResult(ISBN, 'found', False, DETAILS))
        self.assertNotIn('author', changes)
        self.assertNotIn('retail_price', changes)
        self.assertEqual(changes['yumekai_status'], 'outofstock')
        self.assertEqual(changes['description'], 'Sinopsis SD')
        self.assertEqual(changes['book_format'], 'Rústica')
        self.assertEqual(changes['pages'], 200)
        self.assertNotIn('Estado de tienda conservado', note)

    def test_known_wholesaler_stock_updates_demand_but_unknown_does_not(self):
        p = product(yumekai_status='outofstock')
        changes, _ = sd_review_changes(p, SdLookupResult(ISBN, 'found', True, DETAILS))
        self.assertEqual(changes['yumekai_status'], 'yk_on_demand')
        changes, note = sd_review_changes(p, SdLookupResult(ISBN, 'found', None, DETAILS))
        self.assertNotIn('yumekai_status', changes)
        self.assertIn('sin confirmar', note)

    def test_missing_price_and_publisher_are_completed_and_taxonomy_format_defaults_to_rustica(self):
        p = product(retail_price=None, publisher=None, book_format=None)
        changes, note = sd_review_changes(p, SdLookupResult(ISBN, 'found', None, replace(DETAILS, sd_format='MANHWA')))
        self.assertEqual(changes['retail_price'], '10.95')
        self.assertEqual(changes['publisher'], 'Editorial SD')
        self.assertEqual(changes['book_format'], 'Rústica')
        self.assertNotIn('Formato sin equivalencia', note)
        changes, _ = sd_review_changes(p, SdLookupResult(ISBN, 'not_found', message='No encontrado'))
        self.assertEqual(changes, {})


class WorkerTests(unittest.TestCase):
    def test_failures_are_per_product_and_concurrency_is_bounded(self):
        products = {str(i): {'isbn': str(i)} for i in range(12)}
        worker = sd_recheck_worker.SdRecheckWorker(products)
        lock = Lock()
        active = peak = 0
        def read(isbn, stop):
            nonlocal active, peak
            with lock: active += 1; peak = max(peak, active)
            sleep(0.02)
            with lock: active -= 1
            if isbn == '1': raise TimeoutError('Tiempo agotado')
            return SdLookupResult(isbn, 'found', True, DETAILS)
        with patch.object(sd_recheck_worker, 'lookup_sd_isbn', read): worker.run()
        self.assertLessEqual(peak, worker.MAX_WORKERS)
        self.assertEqual(len(worker.results), 12)
        self.assertEqual(worker.results['1'].status, 'error')
        self.assertEqual(sum(r.status == 'found' for r in worker.results.values()), 11)

    def test_stop_keeps_completed_results_and_labels_remaining_products(self):
        worker = sd_recheck_worker.SdRecheckWorker({str(i): {'isbn': str(i)} for i in range(12)})
        lock = Lock()
        called = 0
        def read(isbn, stop):
            nonlocal called
            with lock:
                called += 1
                if called == 4: stop.set()
            sleep(0.02)
            return SdLookupResult(isbn, 'found', True, DETAILS)
        with patch.object(sd_recheck_worker, 'lookup_sd_isbn', read): worker.run()
        self.assertEqual(called, 4)
        self.assertEqual(sum(r.status == 'found' for r in worker.results.values()), 4)
        self.assertEqual(sum(r.status == 'cancelled' for r in worker.results.values()), 8)


class RecheckUiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls): cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.p = product(isbn=ISBN, pages=None, description='')
        self.api = FakeApi([self.p])
        self.window = PendingReviewWindow()
        self.window._api_override = self.api
        self.window._load_pending()
        self.wait_finished()

    def wait_finished(self):
        until = monotonic() + 3
        while self.window._busy and monotonic() < until:
            self.app.processEvents(); QTest.qWait(5)
        self.assertFalse(self.window._busy)

    def tearDown(self):
        self.window._drafts.clear()
        self.window.close(); self.window.deleteLater()
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)

    def test_selection_recheck_proposes_changes_and_only_save_persists_them(self):
        self.assertFalse(self.window._sd_button.isEnabled())
        self.window._toggle_visible()
        self.assertTrue(self.window._sd_button.isEnabled())
        with patch.object(sd_recheck_worker, 'lookup_sd_isbn', return_value=SdLookupResult(ISBN,'found',True,DETAILS)):
            self.window._recheck_sd(); self.wait_finished()
        self.assertEqual(self.api.calls, [])
        self.assertEqual(self.window._current_product(ISBN)['pages'], 200)
        self.assertIn(ISBN, self.window._drafts)
        self.assertIn('Guardar cambios pendientes', self.window._feedback.text())
        with patch('yumekai_importer.ui.windows.pending_review_window.review_changes',
                   side_effect=lambda rows, **kwargs: {key: row['changes'] for key, row in rows.items()}):
            self.window._retry_drafts()
        self.wait_finished()
        self.assertEqual(self.api.rows[ISBN]['pages'], 200)
        self.assertTrue(self.window._sd_results[ISBN]['saved'])
        self.assertEqual(self.api.rows[ISBN]['review_status'], 'pending_review')

    def test_recheck_error_is_visible_and_does_not_create_a_draft(self):
        self.window._toggle_visible()
        with patch.object(sd_recheck_worker, 'lookup_sd_isbn', side_effect=TimeoutError('SD no responde')):
            self.window._recheck_sd(); self.wait_finished()
        self.assertEqual(self.window._drafts, {})
        self.assertIn('SD no responde', self.window._sd_results[ISBN]['note'])
        self.assertEqual(self.window._sd_results[ISBN]['result'], 'Error')
        self.assertEqual(self.api.calls, [])

    def test_stop_button_remains_available_and_prevents_navigation_while_running(self):
        self.window._toggle_visible()
        def read(isbn, stop):
            stop.wait(2)
            raise lookup.SdLookupCancelled()
        with patch.object(sd_recheck_worker, 'lookup_sd_isbn', read):
            self.window._recheck_sd()
            self.assertTrue(self.window._sd_button.isEnabled())
            self.assertFalse(self.window.can_leave())
            self.window._recheck_sd()
            self.wait_finished()
        self.assertEqual(self.window._sd_results[ISBN]['result'], 'Sin consultar / detenida')
        self.assertEqual(self.window._drafts, {})


if __name__ == '__main__': unittest.main()
