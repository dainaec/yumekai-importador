from PySide6.QtCore import QRegularExpression, QSignalBlocker, Qt
from PySide6.QtGui import QRegularExpressionValidator
from PySide6.QtWidgets import (QAbstractItemView, QDialog, QDialogButtonBox, QLabel,
                              QLineEdit, QStyledItemDelegate, QVBoxLayout)

from yumekai_importer.catalog.review_fields import VOLUME_INPUT, normalize_volume
from yumekai_importer.catalog.title_parser import analyze_title, collection_context
from yumekai_importer.ui.widgets.tables import make_table, set_rows


class _VolumeDelegate(QStyledItemDelegate):
    def createEditor(self, parent, option, index):
        editor = QLineEdit(parent)
        editor.setValidator(QRegularExpressionValidator(QRegularExpression(VOLUME_INPUT), editor))
        return editor


class TitleReviewDialog(QDialog):
    def __init__(self, products: dict, parent=None, *, known_titles=()):
        super().__init__(parent)
        self.setWindowTitle('Revisar colección y tomo')
        self.changes = {}
        self._products = products
        self._keys = list(products)
        context = collection_context([*known_titles, *(p.get('title') or '' for p in products.values())])
        self._proposals = [analyze_title(str(p.get('title') or ''), str(p.get('isbn') or ''), known_series=context)
                           for p in products.values()]
        screen = self.screen()
        available = screen.availableGeometry() if screen is not None else None
        self.resize(min(1320, available.width() - 40) if available else 1100,
                    min(700, available.height() - 60) if available else 600)
        layout = QVBoxLayout(self)
        text = QLabel('Compara los valores actuales y propuestos. Solo se aplicarán las filas marcadas. '
                      'Puedes editar Colección propuesta y Tomo propuesto con doble clic. '
                      'Los casos dudosos quedan desmarcados y sin un tomo inventado.')
        text.setWordWrap(True)
        layout.addWidget(text)
        self.table = make_table(['Aplicar', 'Título', 'Tomo actual', 'Tomo propuesto',
                                 'Colección actual', 'Colección propuesta', 'Motivo'], stretch_column=None,
                                column_widths={0: 75, 1: 330, 2: 100, 3: 140, 4: 260, 5: 300, 6: 550},
                                freeze_title=True, frozen_columns=2)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.DoubleClicked)
        self.table.setItemDelegateForColumn(3, _VolumeDelegate(self.table))
        rows = []
        for product, proposal in zip(products.values(), self._proposals):
            rows.append(('', str(product.get('title') or ''), str(product.get('volume') or ''),
                         proposal.volume or '', str(product.get('series') or ''), proposal.series, proposal.reason))
        set_rows(self.table, rows)
        for row, proposal in enumerate(self._proposals):
            key = self._keys[row]
            product = products[key]
            different = proposal.series != product.get('series') or proposal.volume != (product.get('volume') or None)
            for col in range(self.table.columnCount()):
                item = self.table.item(row, col)
                item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
            for col in (3, 5):
                item = self.table.item(row, col)
                item.setFlags(item.flags() | Qt.ItemFlag.ItemIsEditable)
            mark = self.table.item(row, 0)
            mark.setFlags(mark.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            mark.setCheckState(Qt.CheckState.Checked if proposal.reliable and different else Qt.CheckState.Unchecked)
        self.table.itemChanged.connect(self._item_changed)
        self.table.fit_title_rows()
        layout.addWidget(self.table, 1)
        self.error = QLabel()
        self.error.setWordWrap(True)
        self.error.setTextFormat(Qt.TextFormat.PlainText)
        self.error.hide()
        layout.addWidget(self.error)
        buttons = QDialogButtonBox()
        buttons.addButton('Aplicar propuestas marcadas', QDialogButtonBox.ButtonRole.AcceptRole)
        buttons.addButton('Cancelar', QDialogButtonBox.ButtonRole.RejectRole)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _item_changed(self, item):
        if item.column() in (3, 5):
            with QSignalBlocker(self.table):
                self.table.item(item.row(), 0).setCheckState(Qt.CheckState.Checked)
                self.table.item(item.row(), 6).setText('Propuesta editada manualmente.')

    def accept(self):
        changes = {}
        for row, key in enumerate(self._keys):
            if self.table.item(row, 0).checkState() != Qt.CheckState.Checked:
                continue
            series = self.table.item(row, 5).text().strip()
            if not series or len(series) > 255:
                self.error.setText('La colección debe tener entre 1 y 255 caracteres.')
                self.error.show()
                return
            try:
                volume = normalize_volume(self.table.item(row, 3).text().strip())
            except ValueError as error:
                self.error.setText(str(error))
                self.error.show()
                return
            fields = {'series': series, 'volume': volume}
            fields = {name: value for name, value in fields.items()
                      if value != (self._products[key].get(name) or None)}
            if fields:
                changes[key] = fields
        self.changes = changes
        super().accept()
