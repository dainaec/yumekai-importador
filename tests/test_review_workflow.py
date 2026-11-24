import copy
import csv
import os
from pathlib import Path
from tempfile import TemporaryDirectory
import time
import unittest
from unittest.mock import patch

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import QApplication, QDialog, QMessageBox
from PySide6.QtTest import QTest

from yumekai_importer.catalog.review_workflow import STOCK_LABELS, matches_filters, readiness_issues
from yumekai_importer.storage.catalog_api import CatalogApi
from yumekai_importer.storage.woocommerce_csv import export_products
from yumekai_importer.ui.widgets.product_review_dialog import ProductReviewDialog
from yumekai_importer.ui.windows.pending_review_window import PendingReviewWindow, PRODUCT_COLUMNS


def product(isbn='9788419914163', title='Hirayasumi, Vol. 3', status='pending_review', **changes):
    return dict(isbn=isbn, title=title, series=title, publisher='Milky Way', work_type='Manga',
                retail_price='9.00', sale_price='8.55', yumekai_status='instock',
                review_status=status, sku=f'YMK-{isbn}' if status == 'ready_to_upload' else None,
                description='Una "historia", con\nsaltos y español 日本語', author='Keigo Shinzo',
                image_url='https://example.com/portada.jpg', categories=['Manga'],
                demographic='Seinen', volume='3', pages=176, language='Castellano',
                book_format='Rústica', is_featured=0, updated_at='2026-11-23 18:30:00',
                _revision='a' * 64) | changes


class FakeApi:
    def __init__(self, rows):
        self.rows = {p['isbn']: copy.deepcopy(p) for p in rows}
        self.calls = []
        self.fail = False

    def list_products(self, status):
        return [copy.deepcopy(p) for p in self.rows.values() if p['review_status'] == status]

    def review_products(self, action, entries):
        self.calls.append((action, copy.deepcopy(entries)))
        if self.fail:
            raise ValueError('Sin conexión')
        saved = []
        for entry in entries:
            p = self.rows.pop(entry['original_isbn'])
            if action == 'delete':
                continue
            p.update(entry.get('changes', {}))
            ready = action == 'ready' or (action == 'save' and entry['ready_to_upload'])
            p['review_status'] = 'ready_to_upload' if ready else 'pending_review'
            p['sku'] = 'YMK-' + p['isbn'] if ready else None
            self.rows[p['isbn']] = p
            saved.append({'original_isbn': entry['original_isbn'], 'product': copy.deepcopy(p)})
        return {'deleted': [p['original_isbn'] for p in entries]} if action == 'delete' else {'saved': saved}


class RulesAndCsvTests(unittest.TestCase):
    def test_filters_combine_and_ignore_case_and_accents(self):
        p = product(title='¡Árboles de Japón!', publisher='Norma Editorial', work_type='Manhwa')
        self.assertTrue(matches_filters(p, 'ARBOLES', 'norma editorial', 'Manhwa'))
        self.assertFalse(matches_filters(p, 'ARBOLES', 'Milky Way', 'Manhwa'))
        self.assertFalse(matches_filters(p, 'ARBOLES', None, 'Manga'))
        self.assertTrue(matches_filters(p | {'publisher': None}, publisher=''))

    def test_readiness_blocks_missing_data_and_allows_optional_data(self):
        self.assertEqual(readiness_issues(product()), [])
        p = product(retail_price=None, isbn='123', publisher=None, work_type=None, yumekai_status=None)
        self.assertEqual(len(readiness_issues(p)), 5)
        self.assertTrue(readiness_issues(product(retail_price='0.00')))
        self.assertTrue(readiness_issues(product(volume='abc')))
        self.assertEqual(readiness_issues(product(description=None, image_url=None)), [])

    def test_csv_uses_store_fields_unicode_quotes_newlines_and_prices(self):
        with TemporaryDirectory() as directory:
            path = Path(directory) / 'catalogo.csv'
            p = product(status='ready_to_upload')
            self.assertEqual(export_products(path, [p], published=-1), 1)
            self.assertTrue(path.read_bytes().startswith(b'\xef\xbb\xbf'))
            with path.open(encoding='utf-8-sig', newline='') as stream:
                rows = list(csv.DictReader(stream))
            row = rows[0]
            self.assertEqual(row['Nombre'], p['title'])
            self.assertEqual(row['Descripción'], p['description'])
            self.assertEqual(row['Publicado'], '-1')
            self.assertEqual(row['Precio rebajado'], '8,55')
            self.assertEqual(row['Meta: _yk_isbn'], p['isbn'])
            self.assertEqual(row['Meta: _yk_brand'], p['publisher'])
            self.assertEqual(row['Clase de impuesto'], 'tasa-reducida')
            self.assertEqual(row['Categorías'], 'Manga, Manga > Seinen')
            self.assertEqual(row['Estado Yumekai'], 'instock')

    def test_four_stock_states_keep_the_custom_state(self):
        from yumekai_importer.storage.woocommerce_csv import product_row
        expected = {'instock': '1', 'outofstock': '0', 'onbackorder': 'backorder', 'yk_on_demand': '0'}
        for status, standard in expected.items():
            row = product_row(product(status='ready_to_upload', yumekai_status=status))
            self.assertEqual(row['Estado Yumekai'], status)
            self.assertEqual(row['¿Existencias?'], standard)
        self.assertEqual(product_row(product(status='ready_to_upload', yumekai_status='preorder'))['Estado Yumekai'], 'onbackorder')

    def test_failed_export_does_not_replace_existing_file_or_change_products(self):
        with TemporaryDirectory() as directory:
            path = Path(directory) / 'catalogo.csv'
            path.write_text('anterior', encoding='utf-8')
            p = product(status='ready_to_upload')
            original = copy.deepcopy(p)
            with self.assertRaises(ValueError):
                export_products(path, [p, product(isbn='invalid', status='ready_to_upload')])
            self.assertEqual(path.read_text(encoding='utf-8'), 'anterior')
            with patch('yumekai_importer.storage.woocommerce_csv.os.replace', side_effect=OSError('locked')):
                with self.assertRaises(OSError):
                    export_products(path, [p])
            self.assertEqual(path.read_text(encoding='utf-8'), 'anterior')
            self.assertEqual(p, original)
            self.assertEqual(list(Path(directory).iterdir()), [path])


class ReviewUiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.p = product()
        self.other = product('9791370138479', 'Árboles, Vol. 8', publisher='Panini Manga', work_type='Manhwa')
        self.api = FakeApi([self.p, self.other])
        self.window = PendingReviewWindow()
        self.window._api_override = self.api
        self.window._load_pending()
        self.wait_finished()

    def tearDown(self):
        self.window._drafts.clear()
        self.window.close()
        self.window.deleteLater()
        self.app.processEvents()

    def wait_finished(self):
        until = time.monotonic() + 3
        while self.window._busy and time.monotonic() < until:
            self.app.processEvents()
            QTest.qWait(5)
        self.assertFalse(self.window._busy)

    def test_selection_only_targets_visible_results_and_is_cleared_on_filter_change(self):
        self.window._search.setText('arboles')
        self.window._toggle_visible()
        self.assertEqual(self.window._selected, {self.other['isbn']})
        self.window._search.setText('Hirayasumi')
        self.assertEqual(self.window._selected, set())
        self.window._toggle_visible()
        self.assertEqual(self.window._selected, {self.p['isbn']})
        self.window._publisher_filter.setCurrentIndex(self.window._publisher_filter.findData('Panini Manga'))
        self.assertEqual(self.window._visible_keys(), [])
        self.assertEqual(self.window._selected, set())

    def test_checkbox_bulk_ready_then_return_and_tab_counts(self):
        table = self.window._tables['pending_review']
        table.item(0, 0).setCheckState(Qt.CheckState.Checked)
        self.assertEqual(len(self.window._selected), 1)
        self.window._toggle_visible()
        self.window._mark_ready()
        self.wait_finished()
        self.assertEqual(len(self.window._products['pending_review']), 0)
        self.assertEqual(len(self.window._products['ready_to_upload']), 2)
        self.window._tabs.setCurrentIndex(1)
        self.window._toggle_visible()
        self.window._return_pending()
        self.wait_finished()
        self.assertEqual(len(self.window._products['pending_review']), 2)
        self.assertEqual(self.api.calls[-1][0], 'pending')

    def test_every_column_opens_dialog_with_the_correct_product(self):
        table = self.window._tables['pending_review']
        for column in range(table.columnCount()):
            with patch('yumekai_importer.ui.windows.pending_review_window.ProductReviewDialog') as factory:
                factory.return_value.exec.return_value = QDialog.DialogCode.Rejected
                factory.return_value.changes = {}
                factory.return_value.ready_to_upload = False
                self.window._open_product(table.model().index(0, column))
                self.assertEqual(factory.call_args.args[0]['isbn'], table.item(0, 0).data(Qt.ItemDataRole.UserRole))

    def test_dialog_saves_unmarked_edits_and_keeps_pending_status(self):
        table = self.window._tables['pending_review']
        key = table.item(0, 0).data(Qt.ItemDataRole.UserRole)
        with patch('yumekai_importer.ui.windows.pending_review_window.ProductReviewDialog') as factory:
            dialog = factory.return_value
            dialog.exec.return_value = QDialog.DialogCode.Accepted
            dialog.changes = {'title': 'Título corregido'}
            dialog.ready_to_upload = False
            self.window._open_product(table.model().index(0, 3))
        self.wait_finished()
        self.assertEqual(self.window._products['pending_review'][key]['title'], 'Título corregido')
        self.assertEqual(self.window._drafts, {})
        self.assertEqual(self.api.calls[-1][0], 'save')

    def test_failed_save_retains_draft_and_retry_saves_it(self):
        self.api.fail = True
        key = self.p['isbn']
        self.window._drafts[key] = {'changes': {'author': 'Autora corregida'}, 'ready_to_upload': False}
        self.window._retry_drafts()
        self.wait_finished()
        self.assertEqual(self.window._current_product(key)['author'], 'Autora corregida')
        self.assertIn(key, self.window._drafts)
        self.assertIn('Sin conexión', self.window._feedback.text())
        self.api.fail = False
        self.window._retry_drafts()
        self.wait_finished()
        self.assertEqual(self.window._drafts, {})
        self.assertEqual(self.api.rows[key]['author'], 'Autora corregida')

    def test_dialog_keeps_numeric_inputs_and_allows_zero_price_ready(self):
        dialog = ProductReviewDialog(self.p, PRODUCT_COLUMNS, STOCK_LABELS, self.window,
                                     suggestions={'publisher': ['Milky Way']}, reviewed=False)
        self.assertTrue(dialog._isbn.editor.isReadOnly())
        dialog._isbn.unlock.setChecked(True)
        self.assertFalse(dialog._isbn.editor.isReadOnly())
        for field in ('retail_price', 'pages', 'volume'):
            self.assertIsNotNone(dialog._editors[field].validator())
        dialog._editors['retail_price'].setText('0')
        dialog._ready.setChecked(True)
        dialog.accept()
        self.assertEqual(dialog.result(), QDialog.DialogCode.Accepted)
        self.assertEqual(dialog.changes['retail_price'], '0.00')
        dialog.deleteLater()

    def test_bulk_ready_allows_incomplete_products(self):
        self.window._products['pending_review'][self.p['isbn']]['retail_price'] = None
        self.window._toggle_visible()
        self.window._mark_ready()
        self.wait_finished()
        self.assertEqual(self.api.calls[0][0], 'ready')
        self.assertEqual(len(self.window._products['ready_to_upload']), 2)

    def test_delete_requires_confirmation_and_does_not_touch_ready_rows(self):
        self.window._search.setText('Hirayasumi')
        self.window._toggle_visible()
        def choose(label):
            box = QApplication.activeModalWidget()
            for button in box.buttons():
                if button.text() == label:
                    button.click()
                    return
            raise AssertionError(label)
        QTimer.singleShot(0, lambda: choose('Cancelar'))
        self.window._delete_selected()
        self.assertEqual(self.api.calls, [])
        QTimer.singleShot(0, lambda: choose('Borrar fichas'))
        self.window._delete_selected()
        self.wait_finished()
        self.assertNotIn(self.p['isbn'], self.api.rows)
        self.assertIn(self.other['isbn'], self.api.rows)
        self.assertEqual(self.api.calls[-1][0], 'delete')

    def test_reload_cancel_preserves_unsaved_edits(self):
        self.window._drafts[self.p['isbn']] = {'changes': {'title': 'Sin guardar'}, 'ready_to_upload': False}
        with patch.object(QMessageBox, 'question', return_value=QMessageBox.StandardButton.Cancel):
            self.window._load_pending()
            self.assertFalse(self.window.can_leave())
        self.assertEqual(self.window._current_product(self.p['isbn'])['title'], 'Sin guardar')


class ApiResponseTests(unittest.TestCase):
    def setUp(self):
        self.api = CatalogApi('https://example.com/api', 'user', 'pass')
        self.request = {'original_isbn': '9788419914163', 'changes': {}, 'ready_to_upload': False}

    def response(self, body, status=200):
        from unittest.mock import Mock
        r = Mock(status_code=status, ok=status < 400)
        r.json.return_value = body
        return r

    def test_save_pending_and_ready_have_different_expected_status(self):
        for action, target in (('save', 'pending_review'), ('ready', 'ready_to_upload')):
            body = {'saved': [{'original_isbn': self.request['original_isbn'], 'product': product(status=target)}]}
            with patch('yumekai_importer.storage.catalog_api.requests.post', return_value=self.response(body)):
                self.assertEqual(self.api.review_products(action, [self.request]), body)

    def test_incomplete_or_wrong_receipts_are_rejected(self):
        bodies = ({'saved': []}, {'saved': [{'original_isbn': self.request['original_isbn'], 'product': product(status='ready_to_upload')}]})
        for body in bodies:
            with patch('yumekai_importer.storage.catalog_api.requests.post', return_value=self.response(body)):
                with self.assertRaises(ValueError):
                    self.api.review_products('save', [self.request])
        with patch('yumekai_importer.storage.catalog_api.requests.post', return_value=self.response({'deleted': []})):
            with self.assertRaises(ValueError):
                self.api.review_products('delete', [self.request])

    def test_server_conflict_and_network_failure_are_understandable(self):
        import requests
        with patch('yumekai_importer.storage.catalog_api.requests.post', return_value=self.response({'message': 'Recarga la ficha'}, 409)):
            with self.assertRaisesRegex(ValueError, 'Recarga la ficha'):
                self.api.review_products('save', [self.request])
        with patch('yumekai_importer.storage.catalog_api.requests.post', side_effect=requests.Timeout()):
            with self.assertRaisesRegex(ValueError, 'Recarga'):
                self.api.review_products('save', [self.request])


if __name__ == '__main__':
    unittest.main()
