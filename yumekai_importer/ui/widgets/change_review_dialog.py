"""Review exactly which field changes may be submitted."""
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractItemView, QDialog, QDialogButtonBox, QHeaderView, QLabel,
    QPushButton, QTableWidget, QTableWidgetItem, QVBoxLayout,
)
from yumekai_importer.catalog.review_workflow import STOCK_LABELS
from yumekai_importer.catalog.store_review import STORE_FIELDS
from yumekai_importer.ui.widgets.review_check_delegate import ReviewCheckDelegate
from yumekai_importer.diagnostics import logger
from yumekai_importer.catalog.sd_review import FIELD_LABELS


def value_text(field, value):
    if field == 'yumekai_status':
        return STOCK_LABELS.get(value, str(value or 'Por comprobar'))
    return '' if value is None else str(value)


class ChangeReviewDialog(QDialog):
    def __init__(self, rows, *, store=False, parent=None):
        super().__init__(parent)
        self.setWindowTitle('Revisar cambios en tienda' if store else 'Revisar cambios propuestos')
        screen = self.screen().availableGeometry() if self.screen() is not None else None
        self.resize(min(1180, screen.width() - 40) if screen else 1100,
                    min(680, screen.height() - 60) if screen else 640)
        self.accepted_changes = {}
        self._rows = rows
        self._store = store
        layout = QVBoxLayout(self)
        message = QLabel(
            "Marca los campos que quieres guardar. "
            "Doble clic en un valor para leer el texto completo. "
            + (
                "Se aplicarán a WooCommerce tras comprobar "
                "que la ficha sigue igual. Los campos desmarcados se descartarán. "
                if store
                else
                "Al confirmar, los campos desmarcados "
                "se descartarán. "
            )
            + "Cancelar conserva todas las propuestas."
        )
        message.setWordWrap(True)
        layout.addWidget(message)
        count = sum(len(row['changes']) for row in rows.values())
        self.table = QTableWidget(count, 5)
        self.table.setHorizontalHeaderLabels(['Aplicar', 'Producto', 'Campo', 'Actual', 'Propuesto'])
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setAlternatingRowColors(True)
        self.table.setSelectionBehavior(
            QAbstractItemView.SelectionBehavior.SelectRows
        )
        self.table.setSelectionMode(
            QAbstractItemView.SelectionMode.SingleSelection
        )
        self.table.verticalHeader().hide()
        self.table.setColumnWidth(0, 70)
        self.table.setColumnWidth(1, 240)
        self.table.setColumnWidth(2, 130)
        for column in (3, 4):
            self.table.horizontalHeader().setSectionResizeMode(column, QHeaderView.ResizeMode.Stretch)
        self.table.setItemDelegateForColumn(0, ReviewCheckDelegate(self.table))
        self.table.setStyleSheet("""
            QTableView::indicator {
                width: 18px;
                height: 18px;
            }

            QTableView::item:selected {
                background-color: #EAD7EA;
                color: #24212C;
            }
        """)
        self.table.setWordWrap(False)
        index = 0
        for key, row in rows.items():
            product = row['product']
            for field, new in row['changes'].items():
                item = QTableWidgetItem()
                item.setFlags(
                    Qt.ItemFlag.ItemIsEnabled
                    | Qt.ItemFlag.ItemIsSelectable
                    | Qt.ItemFlag.ItemIsUserCheckable
                )
                item.setCheckState(Qt.CheckState.Checked)
                item.setData(Qt.ItemDataRole.UserRole, (key, field))
                self.table.setItem(index, 0, item)
                identity = (f"ID {product.get('woocommerce_id')} · " if store else '') + str(product.get('title') or '') + ' · ' + str(product.get('isbn') or '')
                values = (identity, STORE_FIELDS.get(field, FIELD_LABELS.get(field, field).capitalize()), value_text(field, product.get(field)), value_text(field, new))
                for column, value in enumerate(values, 1):
                    cell = QTableWidgetItem(value)
                    cell.setToolTip(value)
                    self.table.setItem(index, column, cell)
                index += 1
        self.table.cellDoubleClicked.connect(self._show_value)
        layout.addWidget(self.table, 1)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)

        uncheck_button = buttons.addButton(
            "Desmarcar todos",
            QDialogButtonBox.ButtonRole.ActionRole,
        )
        uncheck_button.setObjectName("clearButton")
        uncheck_button.clicked.connect(self._uncheck_all)

        buttons.button(
            QDialogButtonBox.StandardButton.Ok
        ).setText(
            "Aplicar seleccionados y descartar el resto"
            if store
            else "Guardar seleccionados y descartar el resto"
        )
        
        cancel = buttons.button(QDialogButtonBox.StandardButton.Cancel)
        cancel.setText('Cancelar')
        cancel.setObjectName('clearButton')
        cancel.setDefault(True)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _show_value(self, row, column):
        if column not in (3, 4):
            return
        from PySide6.QtWidgets import QHBoxLayout, QPlainTextEdit
        dialog = QDialog(self)
        dialog.setWindowTitle(self.table.item(row, 2).text() + ' · Comparar valores completos')
        available = self.screen().availableGeometry() if self.screen() is not None else None
        dialog.resize(min(1000, available.width() - 40) if available else 900, 480)
        layout = QVBoxLayout(dialog)
        values = QHBoxLayout()
        for index in (3, 4):
            pane = QVBoxLayout()
            pane.addWidget(QLabel(self.table.horizontalHeaderItem(index).text()))
            editor = QPlainTextEdit(self.table.item(row, index).text())
            editor.setReadOnly(True)
            pane.addWidget(editor)
            values.addLayout(pane)
        layout.addLayout(values)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        buttons.button(QDialogButtonBox.StandardButton.Close).setText('Cerrar')
        buttons.rejected.connect(dialog.reject)
        layout.addWidget(buttons)
        dialog.exec()
        dialog.deleteLater()

    def _uncheck_all(self):
        for row in range(self.table.rowCount()):
            self.table.item(row, 0).setCheckState(
                Qt.CheckState.Unchecked
            )

    def accept(self):
        changes = {}

        for row in range(self.table.rowCount()):
            item = self.table.item(row, 0)

            if item.checkState() != Qt.CheckState.Checked:
                continue

            key, field = item.data(Qt.ItemDataRole.UserRole)

            changes.setdefault(key, {})[field] = (
                self._rows[key]["changes"][field]
            )

        # También permite confirmar con todo desmarcado.
        self.accepted_changes = changes
        logger.info("review.confirm store=%s accepted_fields=%s discarded_fields=%s", self._store,
                    sum(len(fields) for fields in changes.values()),
                    self.table.rowCount() - sum(len(fields) for fields in changes.values()))
        super().accept()

    def reject(self):
        logger.info("review.cancel store=%s retained_fields=%s", self._store, self.table.rowCount())
        super().reject()


def review_changes(rows, *, store=False, parent=None):
    if not rows:
        return {}
    dialog = ChangeReviewDialog(rows, store=store, parent=parent)
    accepted = dialog.exec() == QDialog.DialogCode.Accepted
    result = dialog.accepted_changes if accepted else None
    dialog.deleteLater()
    return result
