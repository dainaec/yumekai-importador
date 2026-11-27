from PySide6.QtCore import QRegularExpression, QSignalBlocker, Qt, Signal
from PySide6.QtGui import QRegularExpressionValidator
from PySide6.QtWidgets import (
    QComboBox, QGridLayout, QHBoxLayout, QLabel, QLineEdit, QVBoxLayout, QWidget,
)

from yumekai_importer.catalog.classification import DEMOGRAPHICS, canonical_demographic
from yumekai_importer.catalog.review_fields import BOOK_FORMATS
from yumekai_importer.catalog.review_filters import filter_error
from yumekai_importer.catalog.review_quality import empty_data
from yumekai_importer.catalog.review_workflow import STOCK_LABELS, search_text


class ReviewFiltersPanel(QWidget):
    changed = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("reviewFiltersPanel")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self._edits = {}
        self._choices = {}
        grid = QGridLayout()
        grid.setHorizontalSpacing(16)
        grid.setVerticalSpacing(10)
        for column in range(4):
            grid.setColumnStretch(column, 1)
        for column, (field, label, placeholder) in enumerate((
            ("isbn", "ISBN", "Contiene…"), ("sku", "SKU", "Contiene…"),
            ("author", "Autoría", "Nombre de autor/a…"), ("series", "Colección", "Nombre de colección…"),
        )):
            editor = QLineEdit()
            editor.setPlaceholderText(placeholder)
            editor.setClearButtonEnabled(True)
            editor.setAccessibleName("Filtrar por " + label)
            self._edits[field] = editor
            grid.addLayout(self._field(label, editor), 0, column)
        for column, (field, label) in enumerate((("demographic", "Demografía"), ("book_format", "Formato"),
                                                ("language", "Idioma"), ("yumekai_status", "Estado Yumekai"))):
            combo = self._combo(field, label)
            grid.addLayout(self._field(label, combo), 1, column)
        choices = (
            ("is_featured", "Destacado", [(None, "Todos"), (1, "Destacados"), (0, "No destacados")]),
            ("description", "Sinopsis", [(None, "Todas"), (1, "Con sinopsis"), (0, "Sin sinopsis")]),
            ("image_url", "Portada", [(None, "Todas"), (1, "Con portada"), (0, "Sin portada")]),
            ("quality", "Validación", [(None, "Todas las fichas"), ("blocking", "Con avisos de datos"),
                                        ("complete", "Sin datos pendientes"), ("manual_complete", "Completadas manualmente")]),
        )
        for column, (field, label, values) in enumerate(choices):
            combo = self._combo(field, label)
            for value, caption in values:
                combo.addItem(caption, value)
            grid.addLayout(self._field(label, combo), 2, column)
        for column, (field, label) in enumerate((("retail_price", "PVP (€)"), ("pages", "Páginas"), ("volume", "Tomo o intervalo"))):
            row = QHBoxLayout()
            for suffix, placeholder in (("min", "Desde"), ("max", "Hasta")):
                editor = QLineEdit()
                editor.setPlaceholderText(placeholder)
                editor.setAccessibleName(f"{label}: {placeholder.lower()}")
                pattern = r"[0-9]{0,8}(?:[.,][0-9]{0,2})?" if field == "retail_price" else r"[0-9]{0,10}"
                editor.setValidator(QRegularExpressionValidator(QRegularExpression(pattern), editor))
                self._edits[field + "_" + suffix] = editor
                row.addWidget(editor)
            block = QVBoxLayout()
            block.addWidget(QLabel(label))
            block.addLayout(row)
            grid.addLayout(block, 3, column)
        hint = QLabel("El filtro de tomo incluye los packs que contienen ese intervalo.")
        hint.setObjectName("reviewHint")
        hint.setWordWrap(True)
        grid.addWidget(hint, 3, 3)
        self.error = QLabel()
        self.error.setObjectName("reviewFilterError")
        self.error.setWordWrap(True)
        self.error.hide()
        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 12, 14, 12)
        layout.addLayout(grid)
        layout.addWidget(self.error)
        self.set_products([])
        for editor in self._edits.values():
            editor.textChanged.connect(self._changed)
        for combo in self._choices.values():
            combo.currentIndexChanged.connect(self._changed)

    @staticmethod
    def _field(label, widget):
        layout = QVBoxLayout()
        layout.setSpacing(4)
        layout.addWidget(QLabel(label))
        layout.addWidget(widget)
        return layout

    def _combo(self, field, label):
        combo = QComboBox()
        combo.setAccessibleName("Filtrar por " + label)
        combo.setMinimumContentsLength(8)
        combo.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
        combo.currentTextChanged.connect(combo.setToolTip)
        self._choices[field] = combo
        return combo

    def set_products(self, products):
        for field, label in (("demographic", "Todas las demografías"), ("book_format", "Todos los formatos"),
                              ("language", "Todos los idiomas"), ("yumekai_status", "Todos los estados")):
            combo = self._choices[field]
            previous = combo.currentData()
            if field == "yumekai_status":
                values = dict(STOCK_LABELS)
            else:
                labels = [product.get(field) for product in products]
                if field == "demographic":
                    labels = [*DEMOGRAPHICS, *(canonical_demographic(value) for value in labels)]
                elif field == "book_format":
                    labels = [*BOOK_FORMATS, *labels]
                names = {search_text(value): str(value).strip() for value in labels if not empty_data(value)}
                if field == "book_format" and "rustica" in names:
                    names["rustica"] = "Rústica"
                values = {value: value for _, value in sorted(names.items())}
            with QSignalBlocker(combo):
                combo.clear()
                combo.addItem(label, None)
                combo.addItem("Por comprobar" if field == "yumekai_status" else "Sin completar", "")
                for value, caption in values.items():
                    combo.addItem(caption, value)
                index = combo.findData(previous)
                if index < 0 and previous is not None:
                    combo.addItem(str(previous), previous)
                    index = combo.count() - 1
                combo.setCurrentIndex(max(0, index))
            combo.setToolTip(combo.currentText())

    def criteria(self):
        return {**{field: editor.text().strip() for field, editor in self._edits.items()},
                **{field: combo.currentData() for field, combo in self._choices.items()}}

    def active_count(self):
        return sum(value is not None and value != "" for value in self.criteria().values()) + sum(
            combo.currentData() == "" for combo in self._choices.values())

    def clear(self, *, emit=True):
        widgets = [*self._edits.values(), *self._choices.values()]
        blockers = [QSignalBlocker(widget) for widget in widgets]
        try:
            for editor in self._edits.values():
                editor.clear()
            for combo in self._choices.values():
                combo.setCurrentIndex(0)
        finally:
            for blocker in blockers:
                blocker.unblock()
        self.error.hide()
        if emit:
            self.changed.emit()

    def _changed(self, *_):
        error = filter_error(self.criteria())
        self.error.setText(error)
        self.error.setVisible(bool(error))
        self.changed.emit()
