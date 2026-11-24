import csv
import json
import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from PySide6.QtCore import QCoreApplication, QEvent
from PySide6.QtWidgets import QApplication, QDialog

from yumekai_importer.storage.woocommerce_csv import (
    HEADERS, WordPressReference, export_products, load_wordpress_reference, product_row,
)
from yumekai_importer.ui.widgets.csv_export_dialog import CsvExportDialog
from yumekai_importer.ui.windows.pending_review_window import PendingReviewWindow
from tests.test_review_workflow import product


FIXTURES = Path(__file__).parent / 'fixtures'
ISBN = '9788419914163'


class WooCommerceCsvContractTests(unittest.TestCase):
    def test_all_63_headers_match_the_users_wordpress_export_in_order(self):
        expected = json.loads((FIXTURES / 'yumekai-wordpress-headers.json').read_text(encoding='utf-8'))
        self.assertEqual(len(HEADERS), 63)
        self.assertEqual(list(HEADERS), expected)
        self.assertEqual(list(product_row(product(status='ready_to_upload'))), expected)

    def test_requested_constants_and_blank_columns_are_present(self):
        row = product_row(product(status='ready_to_upload', language='Catalán', sku='ANTIGUO'))
        self.assertEqual(row['Tipo'], 'simple')
        self.assertEqual(row['SKU'], 'YMK-' + ISBN)
        self.assertEqual(row['GTIN, UPC, EAN o ISBN'], '')
        self.assertEqual(row['Visibilidad en el catálogo'], 'visible')
        self.assertEqual(row['Estado del impuesto'], 'taxable')
        self.assertEqual(row['Clase de impuesto'], 'tasa-reducida')
        self.assertEqual(row['Meta: _yk_language'], 'Castellano')
        for key in ('¿Vendido individualmente?', '¿Permitir valoraciones de clientes?', 'Posición',
                    '¿Permitir reservas de productos agotados?'):
            self.assertEqual(row[key], '0')
        blanks = ('ID', 'Descripción corta', 'Día en que empieza el precio rebajado',
                  'Día en que termina el precio rebajado', 'Inventario', 'Cantidad de bajo inventario',
                  'Peso (kg)', 'Longitud (cm)', 'Anchura (cm)', 'Altura (cm)', 'Nota de compra',
                  'Etiquetas', 'Clase de envío', 'Límite de descargas', 'Días de caducidad de la descarga',
                  'Superior', 'Productos agrupados', 'Ventas dirigidas', 'Ventas cruzadas', 'URL externa',
                  'Texto del botón', 'Código de mercancía (código HS)', 'País de origen',
                  'Descripción de aduanas', 'Marcas', 'Datos personalizados de Blocksy',
                  'Meta: _yk_character', 'Meta: _yk_manufacturer', 'Meta: _yk_scale', 'Meta: _yk_height',
                  'Meta: _yk_material', 'Meta: _yk_merch_type', 'Meta: _yk_size', 'Meta: _uag_css_file_name')
        self.assertTrue(all(row[field] == '' for field in blanks))

    def test_all_four_category_paths_match_the_actual_store_spelling_and_escaping(self):
        cases = (
            ('Manga', 'Seinen', 'Manga, Manga > Seinen'),
            ('Manga', 'Novelas manga', 'Manga > Artbooks\\, guías y novelas, Manga'),
            ('Manhwa', None, 'Manwha/Manhua > Manwha, Manwha/Manhua'),
            ('Manhua', None, 'Manwha/Manhua > Manhua, Manwha/Manhua'),
            ('Manga', 'Yuri', 'Manga, Manga > Yuri'),
        )
        for work_type, demographic, expected in cases:
            with self.subTest(work_type=work_type, demographic=demographic):
                row = product_row(product(status='ready_to_upload', work_type=work_type, demographic=demographic))
                self.assertEqual(row['Categorías'], expected)
                self.assertEqual(row['Meta: _yk_item_kind'], work_type.lower())

    def test_prices_recalculate_five_percent_with_decimal_rounding_and_spanish_decimals(self):
        for price, regular, sale in (('8.95', '8,95', '8,50'), ('9,00', '9,00', '8,55'),
                                     ('29.99', '29,99', '28,49')):
            with self.subTest(price=price):
                row = product_row(product(status='ready_to_upload', retail_price=price, sale_price='0'))
                self.assertEqual(row['Precio normal'], regular)
                self.assertEqual(row['Precio rebajado'], sale)

    def test_publication_stock_and_featured_values_are_explicit(self):
        for published in (-1, 0, 1):
            row = product_row(product(status='ready_to_upload', is_featured=1), published=published)
            self.assertEqual(row['Publicado'], str(published))
            self.assertEqual(row['¿Está destacado?'], '1')
        for status, stock in (('outofstock', '0'), ('yk_on_demand', '0'), ('instock', '1'), ('onbackorder', 'backorder')):
            row = product_row(product(status='ready_to_upload', yumekai_status=status))
            self.assertEqual(row['Estado Yumekai'], status)
            self.assertEqual(row['¿Existencias?'], stock)
            self.assertEqual(row['¿Permitir reservas de productos agotados?'], '0')
        with self.assertRaises(ValueError):
            product_row(product(status='ready_to_upload'), published=5)

    def test_reference_recovers_real_ids_and_css_by_custom_isbn_despite_old_skus(self):
        refs = load_wordpress_reference(FIXTURES / 'yumekai-wordpress-reference.csv')
        self.assertEqual(len(refs), 3)
        self.assertEqual(refs[ISBN], WordPressReference(182, 'uag-css-182.css'))
        row = product_row(product(status='ready_to_upload'), wordpress_reference=refs)
        self.assertEqual(row['ID'], '182')
        self.assertEqual(row['Meta: _uag_css_file_name'], 'uag-css-182.css')
        self.assertEqual(row['SKU'], 'YMK-' + ISBN)
        self.assertEqual(row['Meta: _yk_isbn'], ISBN)
        new = product_row(product('9791399163087', status='ready_to_upload'), wordpress_reference=refs)
        self.assertEqual(new['ID'], '')
        self.assertEqual(new['Meta: _uag_css_file_name'], '')

    def test_known_wordpress_id_without_css_does_not_invent_an_asset(self):
        row = product_row(product(status='ready_to_upload', woocommerce_id=182))
        self.assertEqual(row['ID'], '182')
        self.assertEqual(row['Meta: _uag_css_file_name'], '')
        with TemporaryDirectory() as directory:
            path = Path(directory) / 'shared-styles.csv'
            path.write_text('ID,Meta: _yk_isbn\n182,' + ISBN + '\n', encoding='utf-8')
            refs = load_wordpress_reference(path)
            self.assertEqual(refs[ISBN], WordPressReference(182, ''))
        with self.assertRaisesRegex(ValueError, 'no coincide'):
            product_row(product(status='ready_to_upload', woocommerce_id=185),
                        wordpress_reference={ISBN: WordPressReference(182, 'uag-css-182.css')})

    def test_ambiguous_reference_is_rejected_before_export(self):
        with TemporaryDirectory() as directory:
            path = Path(directory) / 'reference.csv'
            with path.open('w', encoding='utf-8-sig', newline='') as stream:
                writer = csv.DictWriter(stream, fieldnames=['ID', 'Meta: _yk_isbn', 'Meta: _uag_css_file_name'])
                writer.writeheader()
                writer.writerows([{'ID':'182', 'Meta: _yk_isbn':ISBN}, {'ID':'185', 'Meta: _yk_isbn':ISBN}])
            with self.assertRaisesRegex(ValueError, 'distintos ID'):
                load_wordpress_reference(path)
            path.write_text('ID,Nombre\n182,Prueba\n', encoding='utf-8')
            with self.assertRaisesRegex(ValueError, 'metadatos'):
                load_wordpress_reference(path)

    def test_export_round_trip_preserves_text_and_full_escaped_category(self):
        with TemporaryDirectory() as directory:
            path = Path(directory) / 'products.csv'
            p = product(status='ready_to_upload', title='¡Guía, tomo "único"! 日本語',
                        demographic='Artbooks', description='Primera línea\nSegunda, con "comillas"')
            export_products(path, [p], published=0)
            self.assertTrue(path.read_bytes().startswith(b'\xef\xbb\xbf'))
            with path.open(encoding='utf-8-sig', newline='') as stream:
                reader = csv.DictReader(stream)
                row = next(reader)
                self.assertEqual(reader.fieldnames, list(HEADERS))
                self.assertNotIn(None, row)
            self.assertEqual(row['Nombre'], p['title'])
            self.assertEqual(row['Descripción'], p['description'])
            self.assertEqual(row['Categorías'], 'Manga > Artbooks\\, guías y novelas, Manga')
            self.assertEqual(row['Publicado'], '0')

    def test_id_collision_and_bad_reference_never_replace_an_existing_output(self):
        with TemporaryDirectory() as directory:
            path = Path(directory) / 'products.csv'
            path.write_text('Anterior', encoding='utf-8')
            rows = [product(status='ready_to_upload', woocommerce_id=182),
                    product('9791399163087', status='ready_to_upload', woocommerce_id=182)]
            with self.assertRaisesRegex(ValueError, 'ID de WordPress repetidos'):
                export_products(path, rows)
            self.assertEqual(path.read_text(encoding='utf-8'), 'Anterior')
            with self.assertRaisesRegex(ValueError, 'CSS'):
                export_products(path, [rows[0]], wordpress_reference={ISBN: WordPressReference(182, 'uag-css-185.css')})
            self.assertEqual(path.read_text(encoding='utf-8'), 'Anterior')


class CsvExportDialogTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls): cls.app = QApplication.instance() or QApplication([])

    def tearDown(self):
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        self.app.processEvents()

    def test_reference_selection_and_clear_keep_publication_labels_correct(self):
        dialog = CsvExportDialog(3, True)
        try:
            self.assertEqual([(dialog.publication.itemText(i), dialog.publication.itemData(i)) for i in range(3)],
                             [('Publicado (1)', 1), ('Borrador (-1)', -1), ('Privado (0)', 0)])
            self.assertTrue(dialog.set_reference(FIXTURES / 'yumekai-wordpress-reference.csv'))
            self.assertEqual(len(dialog.wordpress_reference), 3)
            self.assertFalse(dialog.set_reference(FIXTURES / 'missing.csv'))
            self.assertFalse(dialog._generate_button.isEnabled())
            dialog._clear_reference()
            self.assertTrue(dialog._generate_button.isEnabled())
            self.assertEqual(dialog.wordpress_reference, {})
        finally:
            dialog.deleteLater()

    def test_window_exports_only_selected_ready_rows_with_the_reference(self):
        window = PendingReviewWindow()
        p = product(status='ready_to_upload')
        window._products['ready_to_upload'][ISBN] = p
        window._products['pending_review']['9791399163087'] = product('9791399163087')
        window._tabs.setCurrentIndex(1)
        window._selected = {ISBN}
        window._fill_tables()
        try:
            with TemporaryDirectory() as directory:
                path = Path(directory) / 'products.csv'
                with patch('yumekai_importer.ui.windows.pending_review_window.CsvExportDialog') as factory, \
                     patch('yumekai_importer.ui.windows.pending_review_window.QFileDialog.getSaveFileName',
                           return_value=(str(path), 'CSV (*.csv)')):
                    dialog = factory.return_value
                    dialog.exec.return_value = QDialog.DialogCode.Accepted
                    dialog.publication.currentData.return_value = -1
                    dialog.tax_class.text.return_value = 'tasa-reducida'
                    dialog.wordpress_reference = {ISBN: WordPressReference(182, 'uag-css-182.css')}
                    window._export_csv()
                with path.open(encoding='utf-8-sig', newline='') as stream:
                    rows = list(csv.DictReader(stream))
                self.assertEqual(len(rows), 1)
                self.assertEqual(rows[0]['ID'], '182')
                self.assertEqual(rows[0]['Publicado'], '-1')
                self.assertEqual(rows[0]['Meta: _uag_css_file_name'], 'uag-css-182.css')
                self.assertEqual(p['review_status'], 'ready_to_upload')
        finally:
            window.close()
            window.deleteLater()


if __name__ == '__main__': unittest.main()
