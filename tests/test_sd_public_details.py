from dataclasses import replace
from threading import Event
import unittest
from unittest.mock import patch

from lxml import html

from yumekai_importer.catalog.product import Product
from yumekai_importer.catalog.sd_review import sd_review_changes
from yumekai_importer.importers.sd import details, lookup
from tests.test_review_workflow import product


ISBN = '9791370130336'
OTHER = '9791387822040'
LEGACY = 'https://www.sddistribuciones.com/FichaArticulo.aspx?Libro=PAC.SPLAN1IY'
PUBLIC = 'https://www.sddistribuciones.com/planetes-integral-id-pacsplan1iy'


def planetes_page(book_format='CARTONÉ', *, isbn=ISBN, title='PLANETES INTEGRAL', reference='PAC.SPLAN1IY'):
    # Reduced structure of the two real SD responses for the same ISBN.
    format_node = f'<span id="txtFormatoTapa">{book_format}</span>' if book_format is not None else ''
    return html.fromstring(f'''<html><div id="dvFichaArticuloFA">
        <span id="txtTitulo">{title}</span><span id="txtReferenciaInterna">{reference}</span>
        <span id="txtISBN">{isbn}</span><span id="txtEan">{isbn}</span>
        <div id="dvTapaLista">{format_node}</div>
        <span id="txtAutorFA">MAKOTO YUKIMURA</span><span id="txtFamilia">PANINI COMICS</span>
        <div id="dvContainerEstadoFichaArticulo">Stock: Sí</div></div>
        <span id="txtTematicaTema">MANGA</span><span id="txtTematicaMateria">SEINEN</span>
        <span id="txtNumPag2">1032</span>
        <div class="fileproduct"><span id="txtISBN">{OTHER}</span>
        <span id="txtFormatoTapa">RÚSTICA</span></div></html>''')


class PublicSdLookupTests(unittest.TestCase):
    def test_user_planetes_case_reads_the_public_page_before_converting_its_format(self):
        with patch.object(lookup, '_fetch_page', side_effect=[(planetes_page('SEINEN'), LEGACY),
                                                           (planetes_page('CARTONÉ'), PUBLIC)]) as fetch:
            result = lookup.lookup_sd_isbn(ISBN)
        self.assertEqual(fetch.call_count, 2)
        self.assertEqual(fetch.call_args_list[1].args[0], PUBLIC)
        self.assertEqual(result.details.sd_format, 'CARTONÉ')
        self.assertTrue(result.details.format_confirmed)
        self.assertEqual(result.url, PUBLIC)
        self.assertTrue(result.available)
        changes, note = sd_review_changes(product(isbn=ISBN, book_format='Rústica'), result)
        self.assertEqual(changes['book_format'], 'Tapa dura')
        self.assertIn('Formato SD: CARTONÉ → Tapa dura', note)

    def test_same_rule_resolves_another_title_without_hardcoding_the_user_isbn(self):
        page = planetes_page('SHOJO', isbn=OTHER, title='AISHITE KNIGHT: BESAME LICIA 01', reference='ACH.AISHIT01')
        public = 'https://www.sddistribuciones.com/aishite-knight-besame-licia-01-id-achaishit01'
        self.assertEqual(details._public_detail_url(page, 'https://www.sddistribuciones.com/FichaArticulo.aspx?Libro=ACH.AISHIT01'), public)

    def test_already_public_detail_does_not_trigger_an_extra_request(self):
        with patch.object(lookup, '_fetch_page', return_value=(planetes_page(), PUBLIC)) as fetch:
            result = lookup.lookup_sd_isbn(ISBN)
        self.assertEqual(fetch.call_count, 1)
        self.assertEqual(result.details.sd_format, 'CARTONÉ')

    def test_isbn_mismatch_or_homepage_cannot_supply_the_public_format(self):
        homepage = html.fromstring(f'<html><div class="fileproduct"><span id="txtISBN">{ISBN}</span>'
                                   '<span id="txtFormatoTapa">CARTONÉ</span></div></html>')
        for wrong_page in (planetes_page('CARTONÉ', isbn=OTHER), homepage):
            with self.subTest(page=html.tostring(wrong_page)[:70]):
                with patch.object(lookup, '_fetch_page', side_effect=[(planetes_page('SEINEN'), LEGACY),
                                                                   (wrong_page, PUBLIC)]):
                    result = lookup.lookup_sd_isbn(ISBN)
                self.assertFalse(result.details.format_confirmed)
                self.assertTrue(result.available)
                changes, note = sd_review_changes(product(isbn=ISBN, book_format='Tapa dura'), result)
                self.assertNotIn('book_format', changes)
                self.assertIn('Formato anterior conservado', note)
                self.assertIn('Formato sin confirmar', result.message)

    def test_public_network_failure_keeps_current_format_and_can_be_retried_fresh(self):
        responses = [(planetes_page('SEINEN'), LEGACY), TimeoutError('Tiempo agotado'),
                     (planetes_page('SEINEN'), LEGACY), (planetes_page('CARTONÉ'), PUBLIC)]
        with patch.object(lookup, '_fetch_page', side_effect=responses) as fetch:
            failed = lookup.lookup_sd_isbn(ISBN)
            changes, _ = sd_review_changes(product(isbn=ISBN, book_format='Tapa dura'), failed)
            self.assertNotIn('book_format', changes)
            self.assertFalse(failed.details.format_confirmed)
            succeeded = lookup.lookup_sd_isbn(ISBN)
        self.assertEqual(fetch.call_count, 4)
        self.assertTrue(succeeded.details.format_confirmed)
        self.assertEqual(succeeded.details.sd_format, 'CARTONÉ')

    def test_cancellation_keeps_data_already_found_and_does_not_invent_a_binding(self):
        with patch.object(lookup, '_fetch_page', side_effect=[(planetes_page('SEINEN'), LEGACY),
                                                           lookup.SdLookupCancelled()]):
            result = lookup.lookup_sd_isbn(ISBN, Event())
        self.assertEqual(result.status, 'found')
        self.assertTrue(result.available)
        self.assertFalse(result.details.format_confirmed)
        self.assertIn('detenida', result.message)

    def test_related_formats_do_not_fill_a_missing_main_format(self):
        parsed = details._parse_details(planetes_page(None), ISBN)
        self.assertIsNone(parsed.sd_format)
        result = lookup.SdLookupResult(ISBN, 'found', details=parsed)
        changes, _ = sd_review_changes(product(isbn=ISBN, book_format=None), result)
        self.assertEqual(changes['book_format'], 'Rústica')

    def test_legacy_page_without_a_public_address_keeps_format_unconfirmed(self):
        page = planetes_page('SEINEN', reference='')
        with patch.object(lookup, '_fetch_page', return_value=(page, LEGACY)) as fetch:
            result = lookup.lookup_sd_isbn(ISBN)
        self.assertEqual(fetch.call_count, 1)
        self.assertFalse(result.details.format_confirmed)
        self.assertIn('no se pudo localizar', result.message)

    def test_list_detail_link_uses_the_same_public_resolution(self):
        listing = html.fromstring(f'''<html><div class="fileproduct"><span class="dvISBN">{ISBN}</span>
            <span class="estado">Stock: Sí</span><div class="filetitle"><a href="{LEGACY}">Planetes</a>
            </div></div></html>''')
        with patch.object(lookup, '_fetch_page', side_effect=[(listing, 'https://www.sddistribuciones.com/AvanzadaPlus.aspx'),
                                                           (planetes_page('SEINEN'), LEGACY),
                                                           (planetes_page('CARTONÉ'), PUBLIC)]):
            result = lookup.lookup_sd_isbn(ISBN)
        self.assertEqual(result.url, PUBLIC)
        self.assertEqual(result.details.sd_format, 'CARTONÉ')


class PublicSdImportTests(unittest.TestCase):
    def tearDown(self):
        details.read_sd_details.cache_clear()

    def test_excel_enrichment_uses_the_public_binding_too(self):
        with patch.object(details, '_read_details_page', side_effect=[(planetes_page('SEINEN'), LEGACY),
                                                                   (planetes_page('CARTONÉ'), PUBLIC)]):
            result = details.read_sd_details(LEGACY, ISBN)
        imported = Product(ISBN, 'PLANETES INTEGRAL', book_format='Rústica')
        details.apply_sd_details(imported, result)
        self.assertEqual(imported.book_format, 'Tapa dura')

    def test_failed_public_read_is_not_cached_or_treated_as_an_empty_format(self):
        with patch.object(details, '_read_details_page', side_effect=[(planetes_page('SEINEN'), LEGACY),
                                                                   TimeoutError('Tiempo agotado')]):
            with self.assertRaises(TimeoutError):
                details.read_sd_details(LEGACY, ISBN)
        self.assertEqual(details.read_sd_details.cache_info().currsize, 0)

    def test_partial_unconfirmed_details_do_not_overwrite_an_imported_format(self):
        parsed = details._parse_details(planetes_page('SEINEN'), ISBN)
        imported = Product(ISBN, 'PLANETES INTEGRAL', book_format='Tapa dura')
        details.apply_sd_details(imported, replace(parsed, format_confirmed=False))
        self.assertEqual(imported.book_format, 'Tapa dura')


if __name__ == '__main__': unittest.main()
