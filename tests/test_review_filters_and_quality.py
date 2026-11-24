import csv
import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
from pathlib import Path
from tempfile import TemporaryDirectory
from time import monotonic
import unittest
from unittest.mock import patch

from PySide6.QtCore import QCoreApplication, QEvent
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QDialog

from yumekai_importer.catalog.review_filters import filter_error, matches_review_filters
from yumekai_importer.catalog.review_quality import completeness_issues, export_review, recommended_issues
from yumekai_importer.ui.widgets.export_review_dialog import ExportReviewDialog
from yumekai_importer.ui.windows.pending_review_window import PendingReviewWindow
from tests.test_review_workflow import FakeApi, product

FIRST = '9788419914163'
SECOND = '9791370138479'
THIRD = '9788412930627'
FOURTH = '9791399163087'


class ReviewQualityTests(unittest.TestCase):
    def test_complete_products_and_non_manga_without_demographics_are_complete(self):
        self.assertEqual(completeness_issues(product()), [])
        for work_type in ('Manhwa', 'Manhua'):
            self.assertEqual(completeness_issues(product(work_type=work_type, demographic=None)), [])

    def test_missing_recommended_data_is_separate_from_export_blockers(self):
        p = product(author=None, series='', volume=None, language='N/D', book_format=None,
                    pages=None, description='', image_url=None, demographic=None)
        review = export_review({FIRST: p})[FIRST]
        self.assertEqual(review['blocking'], [])
        self.assertEqual(len(review['recommended']), 9)
        self.assertIn('Falta demografía', review['recommended'])

    def test_required_errors_and_recommended_gaps_are_reported_for_each_product(self):
        rows = {FIRST: product(retail_price=None), SECOND: product(SECOND, image_url=None),
                THIRD: product(THIRD)}
        review = export_review(rows)
        self.assertEqual(set(review), {FIRST, SECOND})
        self.assertIn('PVP', ' '.join(review[FIRST]['blocking']))
        self.assertEqual(review[SECOND]['recommended'], ['Falta portada'])


class ReviewFilterRulesTests(unittest.TestCase):
    def test_global_search_supports_titles_isbns_authors_collections_and_skus(self):
        p = product(title='Árboles del mar', author='Autora distinta', series='Colección secreta', sku='YMK-'+FIRST)
        for query in ('ARBOLES', '978-84-19914-16-3', 'distinta', 'coleccion secreta', 'YMK-97884'):
            with self.subTest(query=query):
                self.assertTrue(matches_review_filters(p, query))
        self.assertFalse(matches_review_filters(p, 'No coincide'))

    def test_text_enumeration_and_numeric_filters_combine_with_and(self):
        p = product(author='Ángela', series='Mi colección', demographic='Boys Love',
                    book_format='RÚSTICA', volume='2', is_featured=1)
        criteria = {'author':'angela', 'series':'coleccion', 'isbn':'978-84-19914',
                    'demographic':'Yaoi / BL', 'book_format':'Rústica', 'language':'Castellano',
                    'yumekai_status':'instock', 'is_featured':1, 'description':1, 'image_url':1,
                    'retail_price_min':'8,50', 'retail_price_max':'9', 'pages_min':'170', 'pages_max':'180',
                    'volume_min':'2', 'volume_max':'2'}
        self.assertTrue(matches_review_filters(p, publisher='Milky Way', work_type='Manga', criteria=criteria))
        self.assertFalse(matches_review_filters(p, criteria=criteria | {'is_featured':0}))
        self.assertFalse(matches_review_filters(p, criteria=criteria | {'pages_min':'177'}))

    def test_presence_and_missing_values_work_without_requiring_manhwa_demography(self):
        self.assertTrue(matches_review_filters(product(image_url=None), criteria={'image_url':0}))
        self.assertFalse(matches_review_filters(product(), criteria={'description':0}))
        self.assertTrue(matches_review_filters(product(demographic=None), criteria={'demographic':''}))
        self.assertFalse(matches_review_filters(product(work_type='Manhwa', demographic=None), criteria={'demographic':''}))
        self.assertTrue(matches_review_filters(product(book_format='N/D'), criteria={'book_format':''}))

    def test_volume_ranges_include_packs_overlapping_the_selected_interval(self):
        p = product(volume='1-3')
        self.assertTrue(matches_review_filters(p, criteria={'volume_min':'2', 'volume_max':'2'}))
        self.assertFalse(matches_review_filters(p, criteria={'volume_min':'4'}))
        self.assertFalse(matches_review_filters(product(volume=None), criteria={'volume_max':'3'}))

    def test_bad_ranges_are_rejected_and_quality_filters_are_consistent(self):
        self.assertIn('mínimo', filter_error({'retail_price_min':'10', 'retail_price_max':'5'}))
        self.assertTrue(filter_error({'pages_min':'NaN'}))
        self.assertFalse(matches_review_filters(product(), criteria={'pages_min':'300', 'pages_max':'100'}))
        self.assertFalse(matches_review_filters(product(), incomplete_only=True))
        self.assertTrue(matches_review_filters(product(author=None), incomplete_only=True))
        self.assertTrue(matches_review_filters(product(retail_price=None), criteria={'quality':'blocking'}))
        self.assertFalse(matches_review_filters(product(author=None), criteria={'quality':'complete'}))


class ReviewLayoutAndExportTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls): cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.api = FakeApi([
            product(FIRST),
            product(SECOND, 'Otra historia', work_type='Manhwa', demographic=None, image_url=None),
            product(THIRD, 'Historia pendiente', demographic=None, description=None),
            product(FOURTH, 'Historia preparada', status='ready_to_upload'),
        ])
        self.window = PendingReviewWindow()
        self.window._api_override = self.api
        self.window._load_pending()
        until = monotonic() + 3
        while self.window._busy and monotonic() < until:
            self.app.processEvents()
            QTest.qWait(5)
        self.assertFalse(self.window._busy)

    def tearDown(self):
        self.window._drafts.clear()
        self.window.close()
        self.window.deleteLater()
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        self.app.processEvents()

    def test_secondary_actions_and_distributors_are_grouped_into_menus(self):
        self.assertIn(self.window._duplicates_button, self.window._tools_button.menu().actions())
        self.assertIn(self.window._title_button, self.window._tools_button.menu().actions())
        self.assertEqual(set(self.window._supplier_menus), {'sd','norma','milky_way','dirac'})
        self.assertTrue(self.window._supplier_menus['sd'].menuAction().isEnabled())
        self.assertTrue(all(not menu.menuAction().isEnabled() for key, menu in self.window._supplier_menus.items() if key != 'sd'))
        self.assertIn(self.window._sd_button, self.window._supplier_menus['sd'].actions())
        self.assertIn(self.window._delete_button, self.window._selection_tools.menu().actions())
        self.assertFalse(self.window._advanced_filters.isVisible())

    def test_missing_data_button_and_advanced_filters_combine_and_clear_checks(self):
        self.window._toggle_visible()
        self.assertEqual(len(self.window._selected), 3)
        self.window._incomplete_button.setChecked(True)
        self.assertEqual(set(self.window._visible_keys()), {SECOND,THIRD})
        self.assertEqual(self.window._selected, set())
        panel = self.window._advanced_filters
        combo = panel._choices['image_url']
        combo.setCurrentIndex(combo.findData(0))
        self.assertEqual(self.window._visible_keys(), [SECOND])
        self.assertIn('(1)', self.window._more_filters.text())
        self.window._reset_filters()
        self.assertFalse(self.window._incomplete_button.isChecked())
        self.assertEqual(panel.active_count(), 0)
        self.assertEqual(len(self.window._visible_keys()), 3)

    def test_filters_read_unsaved_edits_and_exact_numeric_bounds(self):
        self.window._drafts[FIRST] = {'changes':{'author':'Autora editada'}, 'ready_to_upload':False}
        panel = self.window._advanced_filters
        panel._edits['author'].setText('editada')
        self.assertEqual(self.window._visible_keys(), [FIRST])
        panel._edits['retail_price_min'].setText('10')
        self.assertEqual(self.window._visible_keys(), [])
        panel._edits['retail_price_max'].setText('5')
        self.assertIn('mínimo', panel.error.text())
        self.window._reset_filters()

    def prepare_ready_with_gap(self, **changes):
        self.window._products['ready_to_upload'][FOURTH].update(changes)
        self.window._tabs.setCurrentIndex(1)
        self.window._selected = {FOURTH}
        self.window._fill_tables()

    def test_warning_is_shown_before_the_csv_dialog_or_file_picker(self):
        self.prepare_ready_with_gap(description=None)
        with patch('yumekai_importer.ui.windows.pending_review_window.ExportReviewDialog') as check_factory, \
             patch('yumekai_importer.ui.windows.pending_review_window.CsvExportDialog') as csv_factory, \
             patch('yumekai_importer.ui.windows.pending_review_window.QFileDialog.getSaveFileName') as save:
            check_factory.return_value.exec.return_value = QDialog.DialogCode.Rejected
            check_factory.return_value.return_to_review = False
            self.window._export_csv()
            self.assertIn('Falta sinopsis', check_factory.call_args.args[0][FOURTH]['recommended'])
            csv_factory.assert_not_called()
            save.assert_not_called()

    def test_price_warnings_can_be_acknowledged_before_export(self):
        self.prepare_ready_with_gap(retail_price=None)
        with patch('yumekai_importer.ui.windows.pending_review_window.ExportReviewDialog') as check_factory, \
             patch('yumekai_importer.ui.windows.pending_review_window.CsvExportDialog') as csv_factory:
            check_factory.return_value.exec.return_value = QDialog.DialogCode.Accepted
            check_factory.return_value.return_to_review = False
            csv_factory.return_value.exec.return_value = QDialog.DialogCode.Rejected
            self.window._export_csv()
            self.assertTrue(check_factory.call_args.args[0][FOURTH]['blocking'])
            csv_factory.assert_called_once()

    def test_recommended_gaps_can_be_acknowledged_and_the_csv_is_generated(self):
        self.prepare_ready_with_gap(description=None)
        with TemporaryDirectory() as directory:
            path = Path(directory) / 'products.csv'
            with patch('yumekai_importer.ui.windows.pending_review_window.ExportReviewDialog') as check_factory, \
                 patch('yumekai_importer.ui.windows.pending_review_window.CsvExportDialog') as csv_factory, \
                 patch('yumekai_importer.ui.windows.pending_review_window.QFileDialog.getSaveFileName', return_value=(str(path),'')):
                check_factory.return_value.exec.return_value = QDialog.DialogCode.Accepted
                check_factory.return_value.return_to_review = False
                dialog = csv_factory.return_value
                dialog.exec.return_value = QDialog.DialogCode.Accepted
                dialog.publication.currentData.return_value = -1
                dialog.tax_class.text.return_value = 'tasa-reducida'
                dialog.wordpress_reference = {}
                self.window._export_csv()
            with path.open(encoding='utf-8-sig', newline='') as stream:
                rows = list(csv.DictReader(stream))
            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0]['Descripción'], '')
            self.assertEqual(rows[0]['Publicado'], '-1')

    def test_export_review_returns_affected_products_to_pending(self):
        self.prepare_ready_with_gap(image_url=None)
        complete = product(FIRST, status='ready_to_upload')
        self.window._products['pending_review'].pop(FIRST)
        self.window._products['ready_to_upload'][FIRST] = complete
        self.api.rows[FIRST] = complete.copy()
        self.window._selected.clear()
        self.window._fill_tables()
        with patch('yumekai_importer.ui.windows.pending_review_window.ExportReviewDialog') as factory:
            factory.return_value.exec.return_value = QDialog.DialogCode.Rejected
            factory.return_value.return_to_review = True
            self.window._export_csv()
        until = monotonic() + 3
        while self.window._busy and monotonic() < until:
            self.app.processEvents()
            QTest.qWait(5)
        self.assertFalse(self.window._busy)
        self.assertIn(FOURTH, self.window._products['pending_review'])
        self.assertNotIn(FOURTH, self.window._products['ready_to_upload'])
        self.assertIn(FIRST, self.window._products['ready_to_upload'])
        self.assertEqual(self.api.calls[-1][0], 'pending')

    def test_only_the_exported_selection_is_validated(self):
        bad = product(THIRD, status='ready_to_upload', description=None)
        self.window._products['ready_to_upload'][THIRD] = bad
        self.window._products['pending_review'].pop(THIRD)
        self.window._tabs.setCurrentIndex(1)
        self.window._selected = {FOURTH}
        with patch('yumekai_importer.ui.windows.pending_review_window.ExportReviewDialog') as check_factory, \
             patch('yumekai_importer.ui.windows.pending_review_window.CsvExportDialog') as csv_factory:
            csv_factory.return_value.exec.return_value = QDialog.DialogCode.Rejected
            self.window._export_csv()
            check_factory.assert_not_called()

    def test_export_report_distinguishes_warnings_and_blockers(self):
        for changes, can_continue in (({'description':None}, True), ({'retail_price':None}, True)):
            p = product(**changes)
            dialog = ExportReviewDialog(export_review({FIRST:p}), 1)
            try:
                self.assertEqual(dialog._continue_button.isEnabled(), can_continue)
                dialog.accept()
                self.assertEqual(dialog.result(), QDialog.DialogCode.Accepted if can_continue else QDialog.DialogCode.Rejected)
            finally:
                dialog.deleteLater()


if __name__ == '__main__': unittest.main()
