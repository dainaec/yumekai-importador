import os
import unittest

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
from PySide6.QtGui import QColor, QPalette
from PySide6.QtCore import QCoreApplication, QEvent
from PySide6.QtWidgets import QApplication, QComboBox, QDialog, QLabel, QVBoxLayout

from yumekai_importer.ui.styles.theme import apply_light_theme
from yumekai_importer.ui.widgets.tables import make_table, set_rows
from yumekai_importer.ui.windows.pending_review_window import PendingReviewWindow


def sample_product():
    return dict(isbn='9788419914163', title='Título completo de una obra que ocupa varias líneas',
                author='Autora de prueba', publisher='Editorial de prueba', series='Colección de prueba',
                volume='1-3', language='Castellano', book_format='Rústica con sobrecubierta', pages=256,
                work_type='Manga', demographic='Seinen', retail_price='10.00', sale_price='9.50',
                yumekai_status='yk_on_demand', sku=None, is_featured=1,
                description='Sinopsis con <etiquetas> y un contenido largo. ' * 30,
                image_url='https://example.com/portada-completa.jpg', review_status='pending_review')


class FullTableAndThemeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def tearDown(self):
        # Flush deferred widget deletion before another test replaces the app style.
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        self.app.processEvents()

    def test_all_product_data_is_available_in_both_tabs_and_tooltips(self):
        w = PendingReviewWindow()
        p = sample_product()
        ready = dict(p, isbn='9791370138479', sku='YMK-9791370138479', review_status='ready_to_upload')
        w._products['pending_review'][p['isbn']] = p
        w._products['ready_to_upload'][ready['isbn']] = ready
        w._update_filter_options()
        w._fill_tables()
        expected = {'Autoría': p['author'], 'Editorial': p['publisher'], 'Colección': p['series'],
                    'Tomo': '1-3', 'Idioma': 'Castellano', 'Formato': p['book_format'], 'Páginas': '256',
                    'Tipo de obra': 'Manga', 'Demografía': 'Seinen', 'PVP': '10,00 €',
                    'Rebajado': '9,50 €', 'Estado Yumekai': 'Bajo demanda', 'Destacado': 'Sí',
                    'Categorías': 'Manga, Manga > Seinen', 'Sinopsis': p['description'],
                    'Portada (URL)': p['image_url']}
        for table in w._tables.values():
            columns = {table.horizontalHeaderItem(c).text(): c for c in range(table.columnCount())}
            self.assertEqual(table.columnCount(), 21)
            for caption, value in expected.items():
                self.assertEqual(table.item(0, columns[caption]).text(), value, caption)
            tooltip = table.item(0, columns['Sinopsis']).toolTip()
            self.assertIn('&lt;etiquetas&gt;', tooltip)
            self.assertEqual(tooltip.count('contenido largo'), 30)
        w.close()
        w.deleteLater()

    def test_horizontal_scroll_keeps_the_complete_title_and_check_available(self):
        table = make_table(['Marcar', 'Título', 'Sinopsis', 'Portada'], stretch_column=None,
                           column_widths={0: 75, 1: 200, 2: 600, 3: 600}, freeze_title=True, frozen_columns=2)
        text = sample_product()['title']
        set_rows(table, [('', text, 'Sinopsis larga', 'https://example.com/portada')])
        table.fit_title_rows()
        table.resize(650, 250)
        table.show()
        self.app.processEvents()
        table.horizontalScrollBar().setValue(table.horizontalScrollBar().maximum())
        self.app.processEvents()
        frozen = table._frozen_view
        index = table.model().index(0, 1)
        self.assertEqual(frozen.model().data(index), text)
        self.assertTrue(frozen.visualRect(index).intersects(frozen.viewport().rect()))
        self.assertGreater(table.horizontalScrollBar().value(), 0)
        self.assertGreater(table.rowHeight(0), table.verticalHeader().defaultSectionSize())
        table.close()
        table.deleteLater()

    def test_dark_system_palette_does_not_make_dialogs_or_popups_dark(self):
        self.app.setStyleSheet('')
        dark = QPalette()
        for role in (QPalette.Window, QPalette.Base, QPalette.Button, QPalette.AlternateBase):
            dark.setColor(role, QColor('#1E1E1E'))
        for role in (QPalette.WindowText, QPalette.Text, QPalette.ButtonText):
            dark.setColor(role, QColor('#000000'))
        self.app.setPalette(dark)
        apply_light_theme(self.app)
        dialog = QDialog()
        layout = QVBoxLayout(dialog)
        layout.addWidget(QLabel('Texto que debe ser legible'))
        combo = QComboBox()
        combo.addItems(['Todas las editoriales', 'Editorial de prueba'])
        layout.addWidget(combo)
        dialog.resize(450, 180)
        dialog.show()
        self.app.processEvents()
        background = dialog.grab().toImage().pixelColor(5, 5)
        self.assertGreater(background.lightness(), 230)
        self.assertLess(dialog.palette().color(QPalette.WindowText).lightness(), 80)
        combo.showPopup()
        self.app.processEvents()
        popup = combo.view().window()
        self.assertGreater(popup.palette().color(QPalette.Window).lightness(), 230)
        self.assertGreater(combo.view().palette().color(QPalette.Base).lightness(), 230)
        self.assertLess(combo.view().palette().color(QPalette.Text).lightness(), 80)
        combo.hidePopup()
        dialog.close()
        dialog.deleteLater()

    def test_unused_header_area_and_menus_use_the_light_palette(self):
        apply_light_theme(self.app)
        table = make_table(['Título', 'ISBN'], stretch_column=None, column_widths={0: 200, 1: 150})
        table.resize(1000, 200)
        table.show()
        self.app.processEvents()
        header = table.horizontalHeader()
        image = header.grab().toImage()
        color = image.pixelColor(image.width() - 10, image.height() // 2)
        self.assertGreater(color.lightness(), 230)
        self.assertNotIn('@THEME_ICON_DIR@', self.app.styleSheet())
        table.close()
        table.deleteLater()


if __name__ == '__main__':
    unittest.main()
