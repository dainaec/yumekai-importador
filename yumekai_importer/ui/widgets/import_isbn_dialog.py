from PySide6.QtCore import Qt
from PySide6.QtWidgets import QDialog, QDialogButtonBox, QLabel, QVBoxLayout

from yumekai_importer.ui.widgets.isbn_field import IsbnField


class _ImportIsbnDialog(QDialog):
    def __init__(self, result, row: int, values: dict[str, object], parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Corregir ISBN de importación")
        self.resize(480, 200)
        self._result = result
        self._row = row
        self._values = values
        self._isbn = IsbnField(values["isbn_value"])

        title = QLabel(f"Fila {row} · {values['title_value']}")
        title.setTextFormat(Qt.TextFormat.PlainText)
        title.setWordWrap(True)
        self._error = QLabel()
        self._error.setObjectName("isbnError")
        self._error.setTextFormat(Qt.TextFormat.PlainText)
        self._error.setWordWrap(True)
        self._error.hide()

        buttons = QDialogButtonBox()
        apply_button = buttons.addButton("Aplicar corrección", QDialogButtonBox.ButtonRole.AcceptRole)
        apply_button.setEnabled(False)
        cancel_button = buttons.addButton("Cancelar", QDialogButtonBox.ButtonRole.RejectRole)
        cancel_button.setObjectName("clearButton")
        self._isbn.unlock.toggled.connect(apply_button.setEnabled)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 16, 18, 14)
        layout.addWidget(title)
        layout.addWidget(self._isbn)
        layout.addWidget(self._error)
        layout.addWidget(buttons)
        self.setStyleSheet("""
            QDialog { background-color: #FFFFFF; }
            QLabel, QCheckBox { color: #201A22; }
            QLineEdit { background-color: #FFFFFF; color: #201A22;
                        border: 1px solid #CDC5D0; border-radius: 6px; padding: 7px; }
            QLineEdit:read-only { background-color: #F3F0F4; }
            QLabel#isbnWarning { background-color: #FFF7DF; color: #654B16; padding: 7px; }
            QLabel#isbnError { background-color: #FBEFF3; color: #752E43; padding: 7px; }
        """)

    def accept(self) -> None:
        try:
            isbn = self._isbn.corrected_isbn()
            if isbn is None:
                return
            if any(product.isbn == isbn for product in self._result.products):
                raise ValueError(f"El ISBN {isbn} ya está en esta carga.")

            previous_issue_count = len(self._result.issues)
            previous_product_count = len(self._result.products)
            self._result.add_row(self._row, **{**self._values, "isbn_value": isbn})
            if len(self._result.products) == previous_product_count:
                del self._result.issues[previous_issue_count:]
                raise ValueError("La fila tiene otra incidencia. Corrígela en el Excel y vuelve a cargarlo.")

            new_issues = self._result.issues[previous_issue_count:]
            del self._result.issues[previous_issue_count:]
            self._result.issues[:] = [
                issue for issue in self._result.issues
                if issue.row != self._row or issue.field != "ISBN"
            ]
            self._result.issues.extend(issue for issue in new_issues if issue not in self._result.issues)
            del self._result.invalid_isbn_rows[self._row]
        except ValueError as error:
            self._error.setText(str(error))
            self._error.show()
            self._isbn.editor.setFocus()
            return

        super().accept()


def correct_import_isbn(parent, result, excel_row: int) -> bool:
    values = result.invalid_isbn_rows.get(excel_row)
    if values is None:
        return False
    dialog = _ImportIsbnDialog(result, excel_row, values, parent)
    applied = dialog.exec() == QDialog.DialogCode.Accepted
    dialog.deleteLater()
    return applied
