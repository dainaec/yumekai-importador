from dataclasses import replace
import unittest

from yumekai_importer.catalog.book_formats import normalize_sd_format
from yumekai_importer.catalog.classification import ALIASES, DEMOGRAPHICS
from yumekai_importer.catalog.product import Product
from yumekai_importer.catalog.sd_review import sd_review_changes
from yumekai_importer.importers.sd.details import SdDetails, apply_sd_details
from yumekai_importer.importers.sd.lookup import SdLookupResult
from yumekai_importer.storage.catalog_api import _product_payload
from yumekai_importer.storage.woocommerce_csv import product_row
from tests.test_review_workflow import product


ISBN = '9788419914163'
DETAILS = SdDetails('Manga', 'Seinen', 200, None, 'Autor SD', 'Sinopsis SD')


class SdFormatTests(unittest.TestCase):
    def test_all_cartone_variants_become_tapa_dura(self):
        for value in ('CARTONE', 'Cartoné', 'cartoné cosido', ' CARTONÉ CON SOBRECUBIERTA ',
                      'Cartone plastificado', 'CARTONÉ / EDICIÓN ESPECIAL',
                      'Cartone\u0301 con lomo de tela', 'Cartonés ilustrados', 'SEINEN / CARTONE COSIDO'):
            with self.subTest(value=value):
                self.assertEqual(normalize_sd_format(value), 'Tapa dura')

    def test_other_formats_keep_the_exact_sd_text(self):
        for value in ('Rústica con solapas', 'RUSTICA CON SOBRECUBIERTA',
                      'Grapa', 'FLEXIBOOK', 'Formato  especial', 'Cartonera',
                      'Rústica para manga', 'Edición especial / Manga'):
            with self.subTest(value=value):
                self.assertEqual(normalize_sd_format('  ' + value + '  '), value)

    def test_empty_source_values_default_to_rustica(self):
        for value in (None, '', '  ', '-', '- -', 'N/D', ' n/d ', 'N/A', 'Por completar'):
            with self.subTest(value=value):
                self.assertEqual(normalize_sd_format(value), 'Rústica')

    def test_demographics_work_types_and_category_paths_default_to_rustica(self):
        values = (*ALIASES, *ALIASES.values(), *DEMOGRAPHICS, 'SEINEN', 'SHOJO', 'MANHWA',
                  'Manga', 'Manhua', 'COMIC / MANGA', 'Cómic/Manga', 'NOVELAS MANGA',
                  'SEINEN / DRAMA', 'Manhwa; Romance', 'Teen’s Love', 'TERROR', 'YURI',
                  'Artbooks, guías y novelas', 'Shounen', 'Shoujo')
        for value in values:
            with self.subTest(value=value):
                self.assertEqual(normalize_sd_format(value), 'Rústica')

    def test_import_and_recheck_apply_the_same_rule_to_existing_formats(self):
        for source, expected in (('CARTONE CON SOBRECUBIERTA', 'Tapa dura'),
                                 ('RÚSTICA CON SOLAPAS', 'RÚSTICA CON SOLAPAS'),
                                 ('RÚSTICA', 'Rústica'), ('RUSTICA', 'Rústica'),
                                 ('rustica', 'Rústica'), ('Rústica', 'Rústica'),
                                 ('RuStIcA', 'Rústica'), ('Ru\u0301stica', 'Rústica'),
                                 ('Grapa', 'Grapa'), ('SEINEN', 'Rústica'),
                                 ('MANHWA', 'Rústica'), ('COMIC / MANGA', 'Rústica'),
                                 ('NOVELAS MANGA', 'Rústica'), (None, 'Rústica')):
            with self.subTest(source=source):
                details = replace(DETAILS, sd_format=source)
                imported = Product(ISBN, 'Prueba', work_type='Manga', demographic='Seinen',
                                   pages=200, author='Autor revisado', description='Sinopsis revisada',
                                   book_format='Edición especial')
                self.assertTrue(apply_sd_details(imported, details))
                self.assertEqual(imported.book_format, expected)
                self.assertEqual(imported.author, 'Autor revisado')
                self.assertFalse(apply_sd_details(imported, details))
                self.assertEqual(_product_payload(imported)['book_format'], expected)

                current = product(status='ready_to_upload', book_format='Edición especial')
                changes, note = sd_review_changes(current, SdLookupResult(ISBN, 'found', details=details))
                self.assertEqual(changes, {'book_format': expected})
                self.assertEqual(current['book_format'], 'Edición especial')
                self.assertIn('formato', note)
                saved = current | changes
                self.assertEqual(product_row(saved)['Meta: _yk_format'], expected)
                repeated, _ = sd_review_changes(saved, SdLookupResult(ISBN, 'found', details=details))
                self.assertEqual(repeated, {})

    def test_missing_sd_format_applies_the_requested_default_in_both_flows(self):
        for source in (None, '', '-', 'N/D'):
            with self.subTest(source=source):
                details = replace(DETAILS, sd_format=source)
                imported = Product(ISBN, 'Prueba', book_format='Tapa dura')
                apply_sd_details(imported, details)
                self.assertEqual(imported.book_format, 'Rústica')
                changes, _ = sd_review_changes(product(book_format='Tapa dura'),
                                               SdLookupResult(ISBN, 'found', details=details))
                self.assertEqual(changes['book_format'], 'Rústica')

    def test_failed_or_incomplete_sd_lookups_do_not_act_like_an_empty_format(self):
        current = product(book_format='Tapa dura')
        for status in ('not_found', 'error', 'cancelled', 'found'):
            with self.subTest(status=status):
                changes, _ = sd_review_changes(current, SdLookupResult(ISBN, status))
                self.assertNotIn('book_format', changes)

    def test_existing_taxonomy_format_is_replaced_without_changing_demographic(self):
        details = replace(DETAILS, sd_format='SEINEN')
        current = product(book_format='SEINEN', demographic='Seinen')
        changes, _ = sd_review_changes(current, SdLookupResult(ISBN, 'found', details=details))
        self.assertEqual(changes, {'book_format': 'Rústica'})
        self.assertEqual(current['demographic'], 'Seinen')


if __name__ == '__main__': unittest.main()
