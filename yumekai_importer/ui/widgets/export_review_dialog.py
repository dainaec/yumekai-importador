from PySide6.QtWidgets import QDialog, QDialogButtonBox, QLabel, QVBoxLayout

from yumekai_importer.ui.widgets.tables import make_table, set_rows


class ExportReviewDialog(QDialog):
    def __init__(self, review: dict, total: int, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Comprobar datos antes de exportar")
        self.return_to_review = False
        screen = self.screen()
        available = screen.availableGeometry() if screen is not None else None
        self.resize(min(1180, available.width() - 40) if available else 1000,
                    min(650, available.height() - 60) if available else 550)
        layout = QVBoxLayout(self)
        message = (f"{len(review)} de {total} fichas tienen datos pendientes o por comprobar. "
                   "Puedes devolver esas fichas a revisión o generar el CSV con los datos disponibles.\n"
                   "Los códigos se conservan completos aunque no cumplan el estándar ISBN-13. Los precios que faltan o no se pueden "
                   "utilizar se exportan vacíos; un precio cero se conserva como cero.")
        label = QLabel(message)
        label.setWordWrap(True)
        layout.addWidget(label)
        self.table = make_table(["Título", "ISBN", "Datos pendientes y avisos"],
                                stretch_column=2, column_widths={0: 265, 1: 155})
        set_rows(self.table, [(str(row["product"].get("title") or "Sin título"),
                               str(row["product"].get("isbn") or key),
                               "\n".join(dict.fromkeys([*row["blocking"], *row["recommended"]])) or "—")
                              for key, row in review.items()])
        self.table.setWordWrap(True)
        self.table.horizontalHeader().sectionResized.connect(lambda *_: self.table.resizeRowsToContents())
        self.table.resizeRowsToContents()
        layout.addWidget(self.table, 1)
        buttons = QDialogButtonBox()
        self._return_button = buttons.addButton("Devolver estas fichas a revisión", QDialogButtonBox.ButtonRole.ActionRole)
        self._return_button.setObjectName("clearButton")
        self._return_button.clicked.connect(self._return_pending)
        self._continue_button = buttons.addButton("Generar CSV igualmente", QDialogButtonBox.ButtonRole.AcceptRole)
        cancel = buttons.addButton("Cancelar", QDialogButtonBox.ButtonRole.RejectRole)
        cancel.setObjectName("clearButton")
        cancel.setDefault(True)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _return_pending(self):
        self.return_to_review = True
        self.reject()
