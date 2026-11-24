import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
import csv
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from lxml import html
from PySide6.QtCore import QCoreApplication, QEvent
from PySide6.QtWidgets import QApplication

from yumekai_importer.catalog.classification import ARTBOOK_CATEGORY, canonical_demographic, sd_classification
from yumekai_importer.catalog.product import Product
from yumekai_importer.catalog.review_fields import review_categories
from yumekai_importer.catalog.sd_review import sd_review_changes
from yumekai_importer.importers.sd.details import SdDetails, _parse_details, apply_sd_details
from yumekai_importer.importers.sd.lookup import SdLookupResult
from yumekai_importer.storage.catalog_api import _product_payload
from yumekai_importer.storage.woocommerce_csv import export_products
from yumekai_importer.ui.widgets.product_review_dialog import ProductReviewDialog
from yumekai_importer.ui.windows.pending_review_window import PRODUCT_COLUMNS, STOCK_LABELS
from tests.test_review_workflow import product

EQUIVALENCES = {
    "Teen's Love": 'Yaoi / BL', 'Yaoi': 'Yaoi / BL', 'Boys Love': 'Yaoi / BL',
    'Spokon': 'Shonen', 'Manga adulto': 'Seinen',
    'Novelas manga': ARTBOOK_CATEGORY, 'Artbooks': ARTBOOK_CATEGORY,
}


class ClassificationTests(unittest.TestCase):
    def test_all_requested_equivalences_are_exact(self):
        for label, expected in EQUIVALENCES.items():
            with self.subTest(label=label):
                self.assertEqual(canonical_demographic(label), expected)
                self.assertEqual(sd_classification(['MANGA', label]), ('Manga', expected))

    def test_typographic_quotes_accents_spaces_and_case_do_not_change_mapping(self):
        for label in [' TEEN’S   LOVE ', 'teen’s love', 'Teens Love', "TEEN'S LOVE"]:
            self.assertEqual(canonical_demographic(label), 'Yaoi / BL')
        self.assertEqual(canonical_demographic('Shōnen'), 'Shonen')
        self.assertEqual(canonical_demographic('ARTBOOKS, GUÍAS Y NOVELAS'), ARTBOOK_CATEGORY)
        self.assertEqual(canonical_demographic('Otra categoría'), 'Otra categoría')

    def test_equivalent_multiple_source_labels_are_deduplicated(self):
        self.assertEqual(sd_classification(['MANGA', 'Yaoi / Boys Love / BL']), ('Manga', 'Yaoi / BL'))
        self.assertEqual(sd_classification(['MANGA', 'SPOKON / SHONEN']), ('Manga', 'Shonen'))
        self.assertEqual(sd_classification(['MANGA', 'NOVELAS MANGA / ARTBOOKS']), ('Manga', ARTBOOK_CATEGORY))

    def test_specific_categories_take_precedence_over_broad_adult_heading(self):
        self.assertEqual(sd_classification(['MANGA', 'MANGA ADULTO', 'YAOI']), ('Manga', 'Yaoi / BL'))
        self.assertEqual(sd_classification(['MANGA', 'MANGA ADULTO', 'ARTBOOKS']), ('Manga', ARTBOOK_CATEGORY))
        self.assertEqual(sd_classification(['MANGA', 'SHONEN', 'SEINEN']), ('Manga', None))

    def test_sd_parser_uses_equivalences_in_any_of_its_topic_fields(self):
        for label, expected in EQUIVALENCES.items():
            with self.subTest(label=label):
                page = html.fromstring(f'''<html><span id="txtISBN">9788419914163</span>
                    <span id="txtTematicaTema">MANGA</span><span id="txtTematicaMateria">{label}</span>
                    <span id="txtTematicaSubMateria">{label}</span></html>''')
                self.assertEqual(_parse_details(page, '9788419914163').demographic, expected)

    def test_import_completion_and_creation_payload_use_store_labels(self):
        p = Product('9788419914163', 'Prueba', work_type='Manga')
        details = SdDetails('Manga', 'Yaoi / BL', 200, None, None, None)
        self.assertTrue(apply_sd_details(p, details))
        self.assertEqual(p.demographic, 'Yaoi / BL')
        p.demographic = "Teen's Love"
        payload = _product_payload(p)
        self.assertEqual(payload['demographic'], 'Yaoi / BL')
        self.assertIn('Manga > Yaoi / BL', payload['categories'])

    def test_recheck_completes_missing_demography_and_normalizes_legacy_aliases(self):
        details = SdDetails('Manga', 'Yaoi / BL', None, None, None, None)
        result = SdLookupResult('9788419914163', 'found', details=details)
        for value in (None, 'Yaoi', 'Boys Love', "Teen’s Love"):
            with self.subTest(value=value):
                changes, _ = sd_review_changes(product(demographic=value), result)
                self.assertEqual(changes['demographic'], 'Yaoi / BL')
        changes, note = sd_review_changes(product(demographic='Seinen'), result)
        self.assertNotIn('demographic', changes)
        self.assertIn('se conserva', note)

    def test_csv_escapes_comma_in_long_category_and_preserves_full_label(self):
        p = product(status='ready_to_upload', demographic='Novelas manga')
        self.assertEqual(review_categories('Manga', p['demographic']), ['Manga', 'Manga > ' + ARTBOOK_CATEGORY])
        with TemporaryDirectory() as directory:
            path = Path(directory) / 'products.csv'
            export_products(path, [p])
            with path.open(encoding='utf-8-sig', newline='') as stream:
                row = next(csv.DictReader(stream))
            self.assertEqual(row['Categorías'], 'Manga > Artbooks\\, guías y novelas, Manga')


class ClassificationDialogTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls): cls.app = QApplication.instance() or QApplication([])

    def tearDown(self):
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        self.app.processEvents()

    def test_dropdown_contains_full_store_labels_and_opens_legacy_value_canonically(self):
        d = ProductReviewDialog(product(demographic='Boys Love'), PRODUCT_COLUMNS, STOCK_LABELS)
        combo = d._editors['demographic']
        self.assertEqual(combo.currentData(), 'Yaoi / BL')
        self.assertGreaterEqual(combo.findData('Shonen'), 0)
        self.assertGreaterEqual(combo.findData(ARTBOOK_CATEGORY), 0)
        combo.setCurrentIndex(combo.findData(ARTBOOK_CATEGORY))
        d.accept()
        self.assertEqual(d.changes['demographic'], ARTBOOK_CATEGORY)
        d.deleteLater()


if __name__ == '__main__': unittest.main()
