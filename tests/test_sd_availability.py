from dataclasses import replace
from datetime import date
from decimal import Decimal
import unittest
from unittest.mock import patch

from lxml import html

from yumekai_importer.catalog.product import Product, YumekaiStatus
from yumekai_importer.catalog.sd_review import sd_review_changes
from yumekai_importer.importers.sd.availability import SdStockInfo, publication_date, read_stock_info
from yumekai_importer.importers.sd.details import apply_sd_details
from yumekai_importer.importers.sd import details, lookup, stock
from yumekai_importer.ui.workers import sd_stock_worker

DAY = date(2026, 11, 24)
ISBN = '9791370582289'
URL = 'https://www.sddistribuciones.com/berserk-master-edition-03-id-pacsbelu003'


def page(label='Consultar disponibilidad', released='03/12/2026', isbn=ISBN, related=False):
    pub = f'<span id="txtPublicacion">{released}</span>' if released is not None else ''
    related_html = ('<div class="fileproduct"><span id="txtPublicacion">01/01/2030</span>'
                    '<span id="dvContainerEstadoFichaArticulo">Stock: Sí</span></div>') if related else ''
    return html.fromstring(f'''<html><div id="dvFichaArticuloFA">
        <span id="txtISBN">{isbn}</span><span id="txtTitulo">BERSERK MASTER EDITION 03</span>
        <span id="txtFormatoTapa">CARTONÉ</span><span id="txtNumPag2">672</span>
        <div id="dvContainerEstadoFichaArticulo">{label}</div></div>
        <div id="datos-del-articulo">{pub}<span id="fechaActLyE">01/01/2035</span></div>
        {related_html}</html>''')


def product(isbn=ISBN, **changes):
    return {'isbn': isbn, 'title': 'Berserk Master Edition 03', 'yumekai_status': 'instock', **changes}


class AvailabilityRuleTests(unittest.TestCase):
    def test_rules_use_the_query_day_and_no_stock_takes_precedence_over_release_date(self):
        cases = [('SIN stock', date(2026, 12, 3), 'outofstock'),
                 ('Stock: No', None, 'outofstock'),
                 ('Consultar disponibilidad', date(2026, 12, 3), 'onbackorder'),
                 ('Consultar disponibilidad', date(2026, 11, 23), 'outofstock'),
                 ('Consultar disponibilidad', DAY, 'outofstock'),
                 ('Consultar disponibilidad', None, None),
                 ('Stock: Sí', None, 'yk_on_demand')]
        for label, released, expected in cases:
            with self.subTest(label=label, released=released):
                self.assertEqual(SdStockInfo(label, released, DAY).yumekai_status, expected)

    def test_same_product_changes_when_queried_after_its_publication(self):
        future = SdStockInfo('Consultar disponibilidad', date(2026, 12, 3), DAY)
        self.assertEqual(future.yumekai_status, 'onbackorder')
        self.assertEqual(replace(future, checked_on=date(2026, 12, 4)).yumekai_status, 'outofstock')

    def test_dates_are_calendar_dates_and_invalid_values_stay_unknown(self):
        for text in ('03/12/2026', '3/12/2026', '2026-12-03'):
            self.assertEqual(publication_date(text), date(2026, 12, 3))
        for text in ('31/02/2026', 'N/D', '', None):
            self.assertIsNone(publication_date(text))

    def test_sin_stock_is_recognized_in_catalog_lists(self):
        for label in ('SIN stock', 'SIN STOCK', ' sin   stock ', 'Stock: NO'):
            self.assertIs(stock._availability(label), False)
        self.assertIsNone(stock._availability('Consultar disponibilidad'))

    def test_last_update_and_related_products_cannot_supply_publication_or_stock(self):
        info = read_stock_info(page(released=None, related=True), checked_on=DAY)
        self.assertEqual(info.kind, 'consult')
        self.assertIsNone(info.publication_date)
        self.assertIsNone(info.yumekai_status)
        self.assertIn('fecha de publicación válida', info.explanation)


class SdLookupAvailabilityTests(unittest.TestCase):
    def test_user_examples_and_past_publications_are_resolved_from_real_page_fields(self):
        for label, released, expected in [('SIN stock', '17/11/2006', 'outofstock'),
                                          ('Consultar disponibilidad', '03/12/2026', 'onbackorder'),
                                          ('Consultar disponibilidad', '01/11/2026', 'outofstock')]:
            with self.subTest(label=label, released=released):
                with patch.object(lookup, 'consultation_day', return_value=DAY), \
                     patch.object(lookup, '_fetch_page', return_value=(page(label, released), URL)):
                    result = lookup.lookup_sd_isbn(ISBN)
                self.assertEqual(result.stock_info.yumekai_status, expected)
                self.assertEqual(result.stock_info.checked_on, DAY)
                for previous in ('instock', 'onbackorder', 'outofstock', 'yk_on_demand'):
                    changes, note = sd_review_changes(product(ISBN, yumekai_status=previous), result)
                    self.assertEqual(changes.get('yumekai_status', previous), expected)
                    self.assertIn(label, note)

    def test_consult_without_release_date_preserves_current_state_and_explains_why(self):
        with patch.object(lookup, '_fetch_page', return_value=(page(released=None), URL)):
            result = lookup.lookup_sd_isbn(ISBN)
        changes, note = sd_review_changes(product(ISBN, yumekai_status='instock'), result)
        self.assertNotIn('yumekai_status', changes)
        self.assertIn('fecha de publicación válida', note)

    def test_detail_consult_state_overrides_a_stale_list_stock_value(self):
        listing = html.fromstring(f'''<html><div class="fileproduct"><span class="dvISBN">{ISBN}</span>
            <span class="estado">Stock: Sí</span><div class="filetitle"><a href="{URL}">Ficha</a></div>
            </div></html>''')
        with patch.object(lookup, 'consultation_day', return_value=DAY), \
             patch.object(lookup, '_fetch_page', side_effect=[(listing, URL), (page(), URL)]):
            result = lookup.lookup_sd_isbn(ISBN)
        self.assertIsNone(result.available)
        self.assertEqual(result.stock_info.yumekai_status, 'onbackorder')

    def test_repeated_import_reads_are_fresh_and_apply_to_an_existing_stock_state(self):
        with patch.object(details, 'consultation_day', return_value=DAY), \
             patch.object(details, '_read_details_page', side_effect=[(page(), URL), (page('SIN stock'), URL)]) as read:
            first = details.read_sd_details(URL, ISBN)
            second = details.read_sd_details(URL, ISBN)
        self.assertEqual(read.call_count, 2)
        p = Product(ISBN, 'Berserk', retail_price=Decimal('50.00'), yumekai_status=YumekaiStatus.IN_STOCK)
        apply_sd_details(p, first)
        self.assertEqual(p.yumekai_status, YumekaiStatus.ON_BACKORDER)
        apply_sd_details(p, second)
        self.assertEqual(p.yumekai_status, YumekaiStatus.OUT_OF_STOCK)


class ImportStockWorkerTests(unittest.TestCase):
    def test_consulting_stock_fetches_the_date_even_when_other_product_data_is_complete(self):
        parsed = details._parse_details(page(), ISBN, checked_on=DAY)
        for listing_stock in ({}, {ISBN: False}):
            with self.subTest(listing_stock=listing_stock):
                worker = sd_stock_worker.SdStockWorker({ISBN: 'PAC.SBELU003'}, detail_isbns=set())
                def batches(*_, detail_urls, **kwargs):
                    detail_urls[ISBN] = URL
                    return listing_stock.copy(), []
                with patch.object(sd_stock_worker, 'read_sd_stock_batches', batches), \
                     patch.object(sd_stock_worker, 'read_sd_details', return_value=parsed) as read:
                    worker.run()
                read.assert_called_once_with(URL, ISBN)
                self.assertEqual(worker.statuses[ISBN], 'onbackorder')
                self.assertIsNone(worker.error)
