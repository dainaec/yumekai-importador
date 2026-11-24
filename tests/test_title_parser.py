import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
from pathlib import Path
from tempfile import TemporaryDirectory
import time
import unittest
from unittest.mock import patch

from openpyxl import Workbook
from PySide6.QtCore import QCoreApplication, QEvent, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QDialog

from yumekai_importer.catalog.title_parser import analyze_title, collection_context, infer_series_and_volume
from yumekai_importer.importers.sd.excel import read_sd_excel
from yumekai_importer.importers.norma.excel import read_norma_excel
from yumekai_importer.ui.widgets.title_review_dialog import TitleReviewDialog
from yumekai_importer.ui.windows.pending_review_window import PendingReviewWindow
from tests.test_review_workflow import FakeApi, product


class ParserTests(unittest.TestCase):
    def test_akasaka_markers_keep_time_in_collection_and_extract_the_right_volume(self):
        for suffix, expected in [('N.01', '1'), ('N.02', '2'), ('Nº 03', '3'), ('N°04', '4'),
                                 ('n. 05', '5'), ('núm. 06', '6'), ('número 07', '7'),
                                 ('VOL. 08', '8'), ('Volumen 09', '9'), ('TOMO 10', '10'), ('#11', '11')]:
            with self.subTest(suffix=suffix):
                result = analyze_title('A LAS 25:00 EN AKASAKA ' + suffix)
                self.assertEqual((result.series, result.volume), ('A LAS 25:00 EN AKASAKA', expected))
                self.assertTrue(result.reliable)

    def test_title_40_is_protected_and_verified_isbn_recovers_first_volume(self):
        title = '10 COSAS QUE QUIERO HACER ANTES DE LOS 40'
        self.assertEqual(infer_series_and_volume(title, '9788411508100'), (title, '1'))
        self.assertEqual(infer_series_and_volume(title), (title, None))
        self.assertEqual(infer_series_and_volume(title, '9788419914163'), (title, None))
        self.assertEqual(infer_series_and_volume(title + ' 02'), (title, '2'))
        self.assertEqual(infer_series_and_volume(title + ' N.02'), (title, '2'))

    def test_numbers_in_names_and_unmarked_single_titles_are_not_assumed_volumes(self):
        for title in ['FAHRENHEIT 451', '1984', '86', 'A LAS 25:00 EN AKASAKA',
                      '11 M: LA NOVELA GRAFICA', 'EL CLUB DE LOS 27', '20TH CENTURY BOYS',
                      'NARUTO 1', 'BIBLIOTECA 2024', 'MANGA SIN NUMERO']:
            with self.subTest(title=title):
                result = analyze_title(title)
                self.assertEqual(result.series, title)
                self.assertIsNone(result.volume)
                self.assertFalse(result.reliable)

    def test_related_volumes_supply_context_without_order_dependence(self):
        titles = ['NARUTO 100', 'NARUTO 1', 'NARUTO 2']
        for order in (titles, titles[::-1]):
            known = collection_context(order)
            self.assertEqual(analyze_title('NARUTO 100', known_series=known).volume, '100')
            self.assertEqual(analyze_title('NARUTO 1', known_series=known).series, 'NARUTO')
        self.assertIsNone(analyze_title('FAHRENHEIT 451', known_series=known).volume)
        self.assertIsNone(analyze_title('NARUTO 1', known_series=collection_context(['NARUTO 1', 'NARUTO 1'])).volume)

    def test_explicit_markers_and_padded_volumes_supply_series_context(self):
        known = collection_context(['MANGA Vol. 1', 'MANGA 2'])
        self.assertEqual(analyze_title('MANGA 2', known_series=known).volume, '2')
        self.assertEqual(infer_series_and_volume('20TH CENTURY BOYS 02'), ('20TH CENTURY BOYS', '2'))

    def test_packs_ranges_editions_and_subtitles(self):
        cases = {
            '2X1 CRIMSON GRIMOIRE. EL GRIMORIO CARMESI (Nº01 Y Nº02)': ('CRIMSON GRIMOIRE. EL GRIMORIO CARMESI', '1-2'),
            'MANGA VOL. 01 - EL INICIO': ('MANGA', '1'),
            'MANGA PACK 01 AL 05': ('MANGA', '1-5'),
            'MANGA BOX SET 1-3': ('MANGA', '1-3'),
            'MANGA VOL. 01 A 03': ('MANGA', '1-3'),
            'MANGA 05 (EDICIÓN ESPECIAL)': ('MANGA', '5'),
            'MANGA N.02 EDICIÓN LIMITADA': ('MANGA', '2'),
            'MANGA TOMO ÚNICO': ('MANGA', '1'),
        }
        for title, expected in cases.items():
            with self.subTest(title=title): self.assertEqual(infer_series_and_volume(title), expected)
        self.assertIsNone(analyze_title('MANGA (Nº01 Y Nº03)').volume)
        self.assertFalse(analyze_title('MANGA PACK 5-1').reliable)

    def test_both_importers_finalize_context_and_keep_original_titles(self):
        with TemporaryDirectory() as directory:
            for name, reader, headers in (
                ('sd', read_sd_excel, ['ISBN', 'Titulo', 'PVP', 'Autor']),
                ('norma', read_norma_excel, ['ISBN', 'TÍTULO', 'PVP', 'AUTORÍA']),
            ):
                with self.subTest(importer=name):
                    path = Path(directory) / (name + '.xlsx')
                    book = Workbook()
                    book.active.append(headers)
                    book.active.append(['9788411508100', '10 COSAS QUE QUIERO HACER ANTES DE LOS 40', 9, 'Mamita'])
                    book.active.append(['9788410516472', 'A LAS 25:00 EN AKASAKA N.02', 9, 'Autor'])
                    book.active.append(['9788419914163', 'MANGA 1', 9, 'Autor'])
                    book.active.append(['9791370138479', 'MANGA 2', 9, 'Autor'])
                    book.save(path)
                    result = reader(path)
                    self.assertEqual([p.volume for p in result.products], ['1', '2', '1', '2'])
                    self.assertEqual(result.products[1].title, 'A LAS 25:00 EN AKASAKA N.02')
                    self.assertEqual(result.products[1].series, 'A LAS 25:00 EN AKASAKA')


class RepairUiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls): cls.app = QApplication.instance() or QApplication([])

    def tearDown(self):
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        self.app.processEvents()

    def test_existing_inferred_values_have_a_preview_and_doubtful_rows_stay_unchecked(self):
        products = {
            'first': product(isbn='9788411508100', title='10 COSAS QUE QUIERO HACER ANTES DE LOS 40',
                             series='10 COSAS QUE QUIERO HACER ANTES DE LOS', volume='40'),
            'akasaka': product(title='A LAS 25:00 EN AKASAKA N.02', series='A LAS 25:00 EN AKASAKA N.02', volume='1'),
            'unknown': product(title='11 M: LA NOVELA GRAFICA', series='11 M: LA NOVELA GRAFICA', volume='1'),
        }
        d = TitleReviewDialog(products)
        self.assertEqual(d.table.item(0, 3).text(), '1')
        self.assertEqual(d.table.item(1, 3).text(), '2')
        self.assertEqual(d.table.item(2, 0).checkState(), Qt.CheckState.Unchecked)
        d.accept()
        self.assertEqual(d.changes['first']['volume'], '1')
        self.assertEqual(d.changes['akasaka']['volume'], '2')
        self.assertNotIn('unknown', d.changes)
        self.assertEqual(products['first']['volume'], '40')
        d.deleteLater()

    def test_preview_allows_manual_corrections_but_rejects_letters_in_volume(self):
        p = product(title='OBRA SIN NUMERO', series='OBRA SIN NUMERO')
        d = TitleReviewDialog({'p': p})
        self.assertEqual(d.table.item(0, 0).checkState(), Qt.CheckState.Unchecked)
        d.table.item(0, 3).setText('mal')
        d.accept()
        self.assertEqual(d.result(), QDialog.DialogCode.Rejected)
        self.assertTrue(d.error.text())
        d.table.item(0, 3).setText('2-4')
        d.accept()
        self.assertEqual(d.changes['p']['volume'], '2-4')
        d.deleteLater()

    def test_repair_only_selected_products_and_save_is_explicit(self):
        p = product(title='A LAS 25:00 EN AKASAKA N.02', series='A LAS 25:00 EN AKASAKA N.02', volume='1')
        api = FakeApi([p])
        w = PendingReviewWindow()
        w._api_override = api
        w._products['pending_review'][p['isbn']] = p
        w._update_filter_options(); w._fill_tables()
        self.assertFalse(w._title_button.isEnabled())
        w._toggle_visible()
        self.assertTrue(w._title_button.isEnabled())
        with patch('yumekai_importer.ui.windows.pending_review_window.TitleReviewDialog') as factory:
            factory.return_value.exec.return_value = QDialog.DialogCode.Accepted
            factory.return_value.changes = {p['isbn']: {'series': 'A LAS 25:00 EN AKASAKA', 'volume': '2'}}
            w._review_titles()
        self.assertEqual(api.calls, [])
        self.assertEqual(w._current_product(p['isbn'])['volume'], '2')
        self.assertEqual(p['volume'], '1')
        self.assertIn('Guardar cambios pendientes', w._feedback.text())
        w._retry_drafts()
        until = time.monotonic() + 3
        while w._busy and time.monotonic() < until:
            self.app.processEvents(); QTest.qWait(5)
        self.assertFalse(w._busy)
        self.assertEqual(api.rows[p['isbn']]['volume'], '2')
        self.assertEqual(api.rows[p['isbn']]['review_status'], 'pending_review')
        w.close(); w.deleteLater()

    def test_cancelled_preview_does_not_change_existing_data(self):
        p = product()
        w = PendingReviewWindow()
        w._products['pending_review'][p['isbn']] = p
        w._fill_tables(); w._toggle_visible()
        with patch('yumekai_importer.ui.windows.pending_review_window.TitleReviewDialog') as factory:
            factory.return_value.exec.return_value = QDialog.DialogCode.Rejected
            factory.return_value.changes = {p['isbn']: {'volume': '9'}}
            w._review_titles()
        self.assertEqual(w._drafts, {})
        self.assertEqual(w._current_product(p['isbn'])['volume'], p['volume'])
        w.close(); w.deleteLater()


if __name__ == '__main__': unittest.main()
