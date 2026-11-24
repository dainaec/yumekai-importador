from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QComboBox, QDialog, QDialogButtonBox, QFileDialog, QFormLayout, QHBoxLayout,
    QLabel, QLineEdit, QPushButton, QVBoxLayout,
)

from yumekai_importer.storage.woocommerce_csv import load_wordpress_reference


class CsvExportDialog(QDialog):
    def __init__(self, count: int, selected: bool, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Generar CSV para WooCommerce")
        self.resize(690, 380)
        self.wordpress_reference = {}
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel(f"Se exportarán {count} ficha(s) "
                               + ("marcadas." if selected else "visibles con los filtros actuales.")))
        form = QFormLayout()
        self.publication = QComboBox()
        self.publication.addItem("Publicado (1)", 1)
        self.publication.addItem("Borrador (-1)", -1)
        self.publication.addItem("Privado (0)", 0)
        self.tax_class = QLineEdit("tasa-reducida")
        form.addRow("Estado en WordPress", self.publication)
        form.addRow("Clase de impuesto", self.tax_class)
        self.reference_path = QLineEdit()
        self.reference_path.setReadOnly(True)
        self.reference_path.setPlaceholderText("Opcional: exportación de WordPress con todos los metadatos")
        self._browse_button = QPushButton("Elegir CSV…")
        self._browse_button.setObjectName("clearButton")
        self._browse_button.clicked.connect(self._browse_reference)
        self._clear_button = QPushButton("Quitar")
        self._clear_button.setObjectName("clearButton")
        self._clear_button.clicked.connect(self._clear_reference)
        reference_row = QHBoxLayout()
        reference_row.addWidget(self.reference_path, 1)
        reference_row.addWidget(self._browse_button)
        reference_row.addWidget(self._clear_button)
        form.addRow("CSV actual de WordPress", reference_row)
        layout.addLayout(form)
        self._reference_info = QLabel()
        self._reference_info.setWordWrap(True)
        self._reference_info.setTextFormat(Qt.TextFormat.PlainText)
        layout.addWidget(self._reference_info)
        css_note = QLabel("El CSV incluye las 63 columnas de Yumekai. La referencia permite recuperar por ISBN "
                          "el ID y el nombre de CSS de productos existentes. Los nuevos reciben su ID en WordPress; "
                          "la web debe aplicarles la plantilla y generar los estilos.")
        css_note.setWordWrap(True)
        layout.addWidget(css_note)
        note = QLabel("Las fichas permanecerán en Listas para subir. Generar el CSV no confirma su importación en WordPress.")
        note.setWordWrap(True)
        layout.addWidget(note)
        self.error = QLabel()
        self.error.setWordWrap(True)
        self.error.setTextFormat(Qt.TextFormat.PlainText)
        self.error.hide()
        layout.addWidget(self.error)
        buttons = QDialogButtonBox()
        self._generate_button = buttons.addButton("Generar CSV", QDialogButtonBox.ButtonRole.AcceptRole)
        buttons.addButton("Cancelar", QDialogButtonBox.ButtonRole.RejectRole)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        self._clear_reference()

    def _clear_reference(self):
        self.reference_path.clear()
        self.reference_path.setToolTip("")
        self.wordpress_reference = {}
        self._reference_info.setText("Sin referencia: los ID nuevos y los nombres de CSS desconocidos quedan vacíos.")
        self._generate_button.setEnabled(True)
        self.error.hide()

    def set_reference(self, path):
        try:
            references = load_wordpress_reference(path)
        except ValueError as error:
            self.wordpress_reference = {}
            self.reference_path.setText(str(path))
            self.reference_path.setToolTip(str(path))
            self._reference_info.setText("Referencia no válida. Elige otro CSV o pulsa Quitar.")
            self.error.setText(str(error))
            self.error.show()
            self._generate_button.setEnabled(False)
            return False
        self.wordpress_reference = references
        self.reference_path.setText(str(path))
        self.reference_path.setToolTip(str(path))
        self._reference_info.setText(f"{len(references)} productos de WordPress con ID e ISBN válidos para vincular. "
                                     "Los registros sin ISBN utilizable se omiten de la referencia.")
        self.error.hide()
        self._generate_button.setEnabled(True)
        return True

    def _browse_reference(self):
        path, _ = QFileDialog.getOpenFileName(self, "CSV actual de WordPress", "", "CSV (*.csv)",
                                              options=QFileDialog.Option.DontUseNativeDialog)
        if path:
            self.set_reference(path)

    def accept(self):
        if not self._generate_button.isEnabled():
            return
        if not self.tax_class.text().strip():
            self.error.setText("Indica la clase de impuesto; en Yumekai es tasa-reducida.")
            self.error.show()
            return
        super().accept()
