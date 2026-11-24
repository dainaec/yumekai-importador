import csv
from dataclasses import replace
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from yumekai_importer.catalog.descriptions import can_complete_description, description_may_be_shortened
from yumekai_importer.catalog.product import Product
from yumekai_importer.catalog.review_quality import export_review
from yumekai_importer.catalog.sd_review import sd_review_changes
from yumekai_importer.importers.sd.details import apply_sd_details, needs_sd_details
from yumekai_importer.importers.sd.lookup import SdLookupResult
from yumekai_importer.storage.woocommerce_csv import export_products, product_row
from tests.test_review_workflow import product
from tests.test_sd_recheck import DETAILS, ISBN, URL


class FlexibleCsvTests(unittest.TestCase):
    def test_missing_fields_and_invalid_isbn_are_warned_but_exported_after_acknowledgement(self):
        p = product(isbn='1234567890123', status='ready_to_upload', title=None, publisher=None,
                    work_type=None, retail_price=None, yumekai_status=None)
        self.assertTrue(export_review({'original': p}))
        with TemporaryDirectory() as directory:
            path = Path(directory) / 'productos.csv'
            self.assertEqual(export_products(path, [p], allow_incomplete=True), 1)
            with path.open(encoding='utf-8-sig', newline='') as stream:
                row = next(csv.DictReader(stream))
        self.assertEqual(row['Meta: _yk_isbn'], '1234567890123')
        self.assertEqual(row['SKU'], 'YMK-1234567890123')
        for name in ('Precio normal', 'Precio rebajado', 'Nombre', 'Categorías', 'Meta: _yk_brand', '¿Existencias?'):
            self.assertEqual(row[name], '')

    def test_invalid_prices_are_blank_and_zero_is_preserved_without_inventing_a_price(self):
        for price in (None, '', 'abc', '-9.00', 'NaN'):
            with self.subTest(price=price):
                row = product_row(product(status='ready_to_upload', retail_price=price), allow_incomplete=True)
                self.assertEqual(row['Precio normal'], '')
                self.assertEqual(row['Precio rebajado'], '')
        for price in (0, '0.00'):
            row = product_row(product(status='ready_to_upload', retail_price=price), allow_incomplete=True)
            self.assertEqual(row['Precio normal'], '0,00')
            self.assertEqual(row['Precio rebajado'], '0,00')


class SynopsisRecoveryTests(unittest.TestCase):
    def setUp(self):
        self.full = 'Una historia con tildes, aventuras y amistad. ' * 35
        self.short = self.full[:254]
        self.details = replace(DETAILS, description=self.full)

    def test_existing_truncated_text_is_completed_in_import_and_review(self):
        p = Product(ISBN, 'Historia', description=self.short)
        self.assertTrue(needs_sd_details(p))
        self.assertTrue(apply_sd_details(p, self.details))
        self.assertEqual(p.description, self.full)
        result = SdLookupResult(isbn=ISBN, status='found', url=URL, available=True, details=self.details)
        changes, note = sd_review_changes(product(ISBN, description=self.short), result)
        self.assertEqual(changes['description'], self.full)
        self.assertIn('Sinopsis abreviada completada', note)

    def test_reviewed_descriptions_and_unrelated_sd_text_are_preserved(self):
        for current in ('Mi sinopsis revisada.', 'Otra historia ' * 20):
            self.assertFalse(can_complete_description(current, self.full))
        self.assertFalse(can_complete_description(self.short, 'Texto distinto ' * 40))
        self.assertFalse(can_complete_description(self.short, self.short))
        self.assertTrue(description_may_be_shortened(self.short))
        self.assertTrue(can_complete_description(self.short, self.full))

    def test_full_synopsis_survives_the_csv_without_truncation(self):
        with TemporaryDirectory() as directory:
            path = Path(directory) / 'sinopsis.csv'
            export_products(path, [product(status='ready_to_upload', description=self.full)])
            with path.open(encoding='utf-8-sig', newline='') as stream:
                self.assertEqual(next(csv.DictReader(stream))['Descripción'], self.full)
