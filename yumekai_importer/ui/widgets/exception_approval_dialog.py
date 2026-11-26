"""Two deliberate steps before sending products with data warnings."""
from yumekai_importer.ui.widgets.presentation import review_dialog_layout, style_button_box, button_role
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractItemView, QDialog, QDialogButtonBox, QHBoxLayout, QHeaderView,
    QLabel, QMessageBox, QPushButton, QTableWidget, QTableWidgetItem, QVBoxLayout,
)
from yumekai_importer.ui.widgets.review_check_delegate import ReviewCheckDelegate


class ExceptionApprovalDialog(QDialog):
    def __init__(self, rows: dict, *, purpose: str, normal_count: int = 0, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Autorizar fichas con avisos")
        available = self.screen().availableGeometry() if self.screen() is not None else None
        self.resize(min(1040, available.width() - 40) if available else 1040,
                    min(560, available.height() - 60) if available else 560)
        self._rows = rows
        self._purpose = purpose
        self._normal_count = normal_count
        self.approved_keys = set()
        layout = review_dialog_layout(self)
        caption = QLabel(
            f"{purpose}: {len(rows)} ficha(s) requieren autorización.\n"
            "1. Marca las excepciones que aceptas.  2. Confirma el resumen antes del envío.\n"
            f"Las fichas sin marcar quedan pendientes. Fichas sin avisos: {normal_count}."
        )
        caption.setTextFormat(Qt.TextFormat.PlainText)
        caption.setWordWrap(True)
        layout.addWidget(caption)
        self.table = QTableWidget(len(rows), 4)
        self.table.horizontalHeader().setDefaultAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        self.table.verticalHeader().setDefaultSectionSize(38)
        self.table.setHorizontalHeaderLabels(["Autorizar", "Título", "ISBN / código completo", "Avisos"])
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setAlternatingRowColors(True)
        self.table.setItemDelegateForColumn(0, ReviewCheckDelegate(self.table))
        self.table.setStyleSheet("QTableView::indicator { width: 18px; height: 18px; }")
        self.table.verticalHeader().hide()
        self.table.verticalHeader().setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        self.table.setColumnWidth(0, 85)
        self.table.setColumnWidth(1, 260)
        self.table.setColumnWidth(2, 210)
        self.table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeMode.Stretch)
        for index, (key, data) in enumerate(rows.items()):
            check = QTableWidgetItem()
            check.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsUserCheckable)
            check.setCheckState(Qt.CheckState.Unchecked)
            check.setData(Qt.ItemDataRole.UserRole, key)
            self.table.setItem(index, 0, check)
            values = (data["product"].get("title"), data["product"].get("isbn"), "\n".join(data["issues"]))
            for column, value in enumerate(values, 1):
                item = QTableWidgetItem(str(value or ""))
                item.setToolTip(item.text())
                self.table.setItem(index, column, item)
        layout.addWidget(self.table, 1)
        actions = QHBoxLayout()
        mark = QPushButton("Marcar todas")
        clear = QPushButton("Desmarcar todas")
        mark.setObjectName("clearButton")
        clear.setObjectName("clearButton")
        mark.clicked.connect(lambda: self._mark_all(True))
        clear.clicked.connect(lambda: self._mark_all(False))
        actions.addWidget(mark)
        actions.addWidget(clear)
        actions.addStretch()
        self.buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        self.buttons.button(QDialogButtonBox.StandardButton.Ok).setText("Revisar confirmación")
        cancel = self.buttons.button(QDialogButtonBox.StandardButton.Cancel)
        cancel.setText("Cancelar")
        cancel.setObjectName("clearButton")
        self.buttons.accepted.connect(self.accept)
        self.buttons.rejected.connect(self.reject)
        style_button_box(self.buttons)
        actions.addWidget(self.buttons)
        layout.addLayout(actions)
        self.table.itemChanged.connect(self._update_continue)
        self._update_continue()

    def selected_keys(self):
        return {self.table.item(row, 0).data(Qt.ItemDataRole.UserRole)
                for row in range(self.table.rowCount())
                if self.table.item(row, 0).checkState() == Qt.CheckState.Checked}

    def _mark_all(self, checked):
        for row in range(self.table.rowCount()):
            self.table.item(row, 0).setCheckState(Qt.CheckState.Checked if checked else Qt.CheckState.Unchecked)

    def _update_continue(self, *_):
        self.buttons.button(QDialogButtonBox.StandardButton.Ok).setEnabled(bool(self._normal_count or self.selected_keys()))

    def _confirm_selected(self, keys):
        box = QMessageBox(self)
        box.setWindowTitle("Confirmación final de excepciones")
        box.setIcon(QMessageBox.Icon.Warning)
        box.setText(f"{self._purpose}: confirmar {len(keys)} ficha(s) con avisos.")
        box.setInformativeText(
            "Has autorizado expresamente estos códigos no estándar o datos pendientes. "
            "Los códigos se conservarán completos y los precios vacíos seguirán vacíos. "
            f"Se enviarán además {self._normal_count} ficha(s) sin avisos.\n\n"
            + "\n".join(f"{self._rows[key]['product'].get('isbn')} · {self._rows[key]['product'].get('title')}"
                        for key in list(key for key in self._rows if key in keys)[:4])
            + ("\nConsulta «Mostrar detalles» para ver la lista completa y los avisos." if len(keys) > 4
               else "\nConsulta «Mostrar detalles» para ver los avisos aceptados.")
        )
        box.setDetailedText("\n\n".join(
            f"{self._rows[key]['product'].get('isbn')} · {self._rows[key]['product'].get('title')}\n"
            + "\n".join(self._rows[key]["issues"]) for key in self._rows if key in keys
        ))
        confirm = box.addButton("Confirmar y continuar", QMessageBox.ButtonRole.AcceptRole)
        cancel = box.addButton("Volver a revisar", QMessageBox.ButtonRole.RejectRole)
        box.setDefaultButton(cancel)
        box.setEscapeButton(cancel)
        box.exec()
        accepted = box.clickedButton() is confirm
        box.deleteLater()
        return accepted

    def accept(self):
        keys = self.selected_keys()
        if not keys and not self._normal_count:
            return
        if keys and not self._confirm_selected(keys):
            return
        self.approved_keys = keys
        super().accept()


def confirm_exceptions(rows: dict, *, parent=None, purpose: str, normal_count: int = 0):
    if not rows:
        return set()
    dialog = ExceptionApprovalDialog(rows, purpose=purpose, normal_count=normal_count, parent=parent)
    accepted = dialog.exec() == QDialog.DialogCode.Accepted
    keys = set(dialog.approved_keys) if accepted else None
    dialog.deleteLater()
    return keys
