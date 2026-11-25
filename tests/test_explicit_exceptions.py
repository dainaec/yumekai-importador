"""Exceptions are opt-in, preserve source codes, and never replace mandatory identity/state."""
import csv
import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
from decimal import Decimal
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
import time
from unittest.mock import Mock, patch

from openpyxl import Workbook
from PySide6.QtCore import QCoreApplication, QEvent, Qt, QTimer
from PySide6.QtWidgets import QApplication, QDialog, QDialogButtonBox

from yumekai_importer.catalog.exception_rules import import_exception_issues, required_issues
from yumekai_importer.catalog.product import Product
from yumekai_importer.catalog.review_fields import normalize_review_identifier
from yumekai_importer.importers.sd.excel import read_sd_excel
from yumekai_importer.importers.sd import stock
from yumekai_importer.storage.catalog_api import CatalogApi
from yumekai_importer.storage.woocommerce_csv import load_wordpress_reference
from yumekai_importer.ui.widgets.exception_approval_dialog import ExceptionApprovalDialog
from yumekai_importer.ui.widgets.product_review_dialog import ProductReviewDialog
from yumekai_importer.ui.windows.import_window import ImportWindow
from yumekai_importer.ui.windows.pending_review_window import PendingReviewWindow, PRODUCT_COLUMNS, STOCK_LABELS
from tests.test_import_fixes import Response, page
from tests.test_review_workflow import product, FakeApi

CODE = '979137007773010003'
STANDARD = '9788419914163'
MODULE = 'yumekai_importer.ui.windows.'


class CodeAndWarningTests(unittest.TestCase):
    def test_nonstandard_codes_are_literal_and_standard_separator_normalization_still_works(self):
        for code in (CODE, '000123', 'PACK-ABC / 03', 'ñ-商品-001', '123', 'A' * 128):
            self.assertEqual(normalize_review_identifier(code), code)
        self.assertEqual(normalize_review_identifier(' 978-84-19914-16-3 '), STANDARD)
        for code in ('', '  ', 'X' * 129, 'ABC\nDEF', 'ABC\x00DEF'):
            with self.assertRaises(ValueError):
                normalize_review_identifier(code)

    def test_real_code_survives_excel_loading_with_blank_pvp_and_leading_zeros(self):
        with TemporaryDirectory() as directory:
            path = Path(directory) / 'sd.xlsx'
            book = Workbook()
            book.active.append(['ISBN', 'Titulo', 'PVP'])
            for code in (CODE, '000123', 'PACK-ABC/03'):
                book.active.append([code, 'Producto ' + code, None])
            book.save(path)
            book.close()
            result = read_sd_excel(path)
        self.assertEqual([p.isbn for p in result.products], [CODE, '000123', 'PACK-ABC/03'])
        self.assertTrue(all(p.retail_price is None and p.sale_price is None for p in result.products))
        self.assertEqual(len(result.products_by_row), 3)
        self.assertEqual(len(result.issues), 6)

    def test_import_warnings_cover_nonstandard_and_absent_prices_without_requiring_other_fields(self):
        self.assertEqual(import_exception_issues({'isbn': STANDARD, 'retail_price': '9.00'}), [])
        for price in (None, '', '0.00', 'abc', 'NaN'):
            self.assertTrue(import_exception_issues({'isbn': STANDARD, 'retail_price': price}))
        self.assertEqual(len(import_exception_issues({'isbn': CODE, 'retail_price': None})), 2)
        self.assertEqual(required_issues({'isbn': CODE, 'title': 'Edición'}, ready=False), [])
        self.assertEqual(required_issues({'isbn': CODE, 'title': 'Edición', 'yumekai_status': 'outofstock'}), [])
        self.assertEqual(len(required_issues({'isbn': '', 'title': '', 'yumekai_status': None})), 3)

    def test_api_sends_permission_only_for_explicitly_approved_codes(self):
        response = Mock(status_code=200, ok=True)
        response.json.return_value = {'created': 2, 'duplicates': 0}
        api = CatalogApi('https://example.com', 'test', 'test')
        with patch('yumekai_importer.storage.catalog_api.requests.post', return_value=response) as post:
            api.create_products([Product(CODE, 'Especial'), Product(STANDARD, 'Normal', Decimal('9'))],
                                approved_exceptions={CODE})
        rows = post.call_args.kwargs['json']['products']
        self.assertEqual(rows[0]['isbn'], CODE)
        self.assertIsNone(rows[0]['retail_price'])
        self.assertIs(rows[0]['exceptions_confirmed'], True)
        self.assertNotIn('exceptions_confirmed', rows[1])

    def test_sd_listing_retains_requested_arbitrary_codes_and_full_long_code(self):
        for requested, returned in ((CODE, CODE), ('PACK-AbC/03', 'PACK-ABC/03')):
            with self.subTest(requested=requested), patch.object(stock, 'build_opener') as opener:
                opener.return_value.open.return_value = Response(page(returned))
                self.assertEqual(stock.read_sd_stock({requested}), {requested: True})

    def test_wordpress_reference_links_full_nonstandard_code_despite_old_sku(self):
        with TemporaryDirectory() as directory:
            path = Path(directory) / 'wordpress.csv'
            with path.open('w', encoding='utf-8-sig', newline='') as stream:
                writer = csv.writer(stream)
                writer.writerow(['ID', 'SKU', 'Meta: _yk_isbn'])
                writer.writerow(['182', 'YMK-OLD-PACK', CODE])
            reference = load_wordpress_reference(path)
        self.assertEqual(set(reference), {CODE})
        self.assertEqual(reference[CODE].product_id, 182)


class ExceptionUiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.widgets = []
        self.rows = {'x': {'product': product(CODE), 'issues': ['Código no estándar', 'Falta PVP']}}

    def tearDown(self):
        for widget in self.widgets:
            if isinstance(widget, PendingReviewWindow):
                widget._drafts.clear()
            if isinstance(widget, ImportWindow):
                widget._save_worker = None
                widget._issues_exported = True
            widget.close()
            widget.deleteLater()
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        self.app.processEvents()

    def keep(self, widget):
        self.widgets.append(widget)
        return widget

    def test_first_step_is_unchecked_and_needs_explicit_selection(self):
        dialog = self.keep(ExceptionApprovalDialog(self.rows, purpose='Guardar'))
        self.assertEqual(dialog.selected_keys(), set())
        self.assertFalse(dialog.buttons.button(QDialogButtonBox.StandardButton.Ok).isEnabled())
        with patch.object(dialog, '_confirm_selected') as final:
            dialog.accept()
            final.assert_not_called()
        self.assertNotEqual(dialog.result(), QDialog.DialogCode.Accepted)

    def test_second_confirmation_cancel_keeps_choices_then_accept_succeeds(self):
        dialog = self.keep(ExceptionApprovalDialog(self.rows, purpose='Guardar'))
        dialog._mark_all(True)
        def choose(label):
            box = QApplication.activeModalWidget()
            next(button for button in box.buttons() if button.text() == label).click()
        QTimer.singleShot(0, lambda: choose('Volver a revisar'))
        dialog.accept()
        self.assertNotEqual(dialog.result(), QDialog.DialogCode.Accepted)
        self.assertEqual(dialog.selected_keys(), {'x'})
        QTimer.singleShot(0, lambda: choose('Confirmar y continuar'))
        dialog.accept()
        self.assertEqual(dialog.result(), QDialog.DialogCode.Accepted)
        self.assertEqual(dialog.approved_keys, {'x'})

    def test_normals_can_proceed_without_any_exception_authorized(self):
        dialog = self.keep(ExceptionApprovalDialog(self.rows, purpose='Guardar', normal_count=2))
        with patch.object(dialog, '_confirm_selected') as final:
            dialog.accept()
        final.assert_not_called()
        self.assertEqual(dialog.result(), QDialog.DialogCode.Accepted)
        self.assertEqual(dialog.approved_keys, set())

    def import_window(self):
        from yumekai_importer.importers.import_result import ImportResult
        window = self.keep(ImportWindow())
        window._result = ImportResult(products=[Product(STANDARD, 'Normal', Decimal('9')), Product(CODE, 'Especial')])
        return window

    def test_import_only_sends_normals_and_manually_approved_rows(self):
        for keys, codes in ((set(), [STANDARD]), ({'1'}, [STANDARD, CODE])):
            with self.subTest(approved=keys):
                window = self.import_window()
                with patch(MODULE + 'import_window.confirm_exceptions', return_value=keys) as confirm, \
                     patch(MODULE + 'import_window.load_credentials', return_value=('user', 'pass')), \
                     patch(MODULE + 'import_window.SaveImportWorker') as worker:
                    window._save_to_hostalia()
                self.assertEqual([p.isbn for p in worker.call_args.args[1]], codes)
                self.assertEqual(worker.call_args.kwargs['approved_exceptions'], {CODE} if keys else set())
                self.assertEqual(set(confirm.call_args.args[0]), {'1'})
                self.assertEqual(len(window._result.products), 2)

    def test_import_cancel_never_starts_saving(self):
        window = self.import_window()
        with patch(MODULE + 'import_window.confirm_exceptions', return_value=None), \
             patch(MODULE + 'import_window.SaveImportWorker') as worker:
            window._save_to_hostalia()
        worker.assert_not_called()
        self.assertEqual(window._result.products[-1].isbn, CODE)

    def review_window(self):
        window = self.keep(PendingReviewWindow())
        window._products['pending_review'] = {
            STANDARD: product(), CODE: product(CODE, retail_price=None),
            'bad': product('bad', yumekai_status=None),
        }
        return window

    def test_ready_preflight_isolates_hard_failures_and_unapproved_exceptions(self):
        window = self.review_window()
        entries = [window._entry(key) for key in window._products['pending_review']]
        with patch(MODULE + 'pending_review_window.confirm_exceptions', return_value=set()) as confirm:
            sending, failed = window._preflight_entries('ready', entries)
        self.assertEqual([e['original_isbn'] for e in sending], [STANDARD])
        self.assertEqual({f['original_isbn'] for f in failed}, {CODE, 'bad'})
        self.assertEqual(set(confirm.call_args.args[0]), {CODE})
        self.assertNotIn('exceptions_confirmed', sending[0])

    def test_ready_permission_is_per_request_and_only_three_fields_are_mandatory(self):
        window = self.review_window()
        window._products['pending_review'][CODE] = {'isbn': CODE, 'title': 'Edición',
            'yumekai_status': 'outofstock', 'review_status': 'pending_review'}
        entry = window._entry(CODE)
        with patch(MODULE + 'pending_review_window.confirm_exceptions', return_value={CODE}):
            sending, failed = window._preflight_entries('ready', [entry])
        self.assertFalse(failed)
        self.assertIs(sending[0]['exceptions_confirmed'], True)
        self.assertNotIn('exceptions_confirmed', entry)
        with patch(MODULE + 'pending_review_window.confirm_exceptions', return_value=set()):
            sending, failed = window._preflight_entries('ready', sending)
        self.assertFalse(sending)  # An old flag cannot authorize another attempt.

    def test_cancel_ready_save_preserves_draft_and_never_starts_network(self):
        window = self.review_window()
        window._drafts[CODE] = {'changes': {'author': 'Autora'}, 'ready_to_upload': True}
        with patch(MODULE + 'pending_review_window.confirm_exceptions', return_value=None), \
             patch(MODULE + 'pending_review_window.ReviewActionWorker') as worker:
            window._retry_drafts()
        worker.assert_not_called()
        self.assertEqual(window._drafts[CODE]['changes'], {'author': 'Autora'})

    def test_unapproved_ready_draft_does_not_block_an_independent_pending_save(self):
        window = self.review_window()
        api = FakeApi(list(window._products['pending_review'].values()))
        window._api_override = api
        window._drafts[STANDARD] = {'changes': {'author': 'Guardada'}, 'ready_to_upload': False}
        window._drafts[CODE] = {'changes': {'author': 'Pendiente'}, 'ready_to_upload': True}
        with patch(MODULE + 'pending_review_window.confirm_exceptions', return_value=set()):
            window._retry_drafts()
        until = time.monotonic() + 3
        while window._busy and time.monotonic() < until:
            self.app.processEvents()
            time.sleep(0.005)
        self.assertFalse(window._busy)
        self.assertEqual(api.rows[STANDARD]['author'], 'Guardada')
        self.assertNotIn(STANDARD, window._drafts)
        self.assertEqual(window._drafts[CODE]['changes'], {'author': 'Pendiente'})
        self.assertIn('sin autorizar', window._drafts[CODE]['save_error'])
        self.assertEqual([e['original_isbn'] for e in api.calls[0][1]], [STANDARD])

    def test_ready_checkbox_requires_state_while_optional_gaps_can_go_to_authorization(self):
        for state, accepted in ((None, False), ('outofstock', True)):
            p = product(CODE, yumekai_status=state, retail_price=None, publisher=None)
            dialog = self.keep(ProductReviewDialog(p, PRODUCT_COLUMNS, STOCK_LABELS))
            dialog._ready.setChecked(True)
            dialog.accept()
            self.assertEqual(dialog.result() == QDialog.DialogCode.Accepted, accepted)


if __name__ == '__main__':
    unittest.main()
