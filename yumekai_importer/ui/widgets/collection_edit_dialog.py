"""Choose a collection and the shared fields to replace across its products."""
from PySide6.QtCore import QRegularExpression, QSignalBlocker, Qt
from PySide6.QtGui import QRegularExpressionValidator
from PySide6.QtWidgets import (
    QAbstractItemView, QCheckBox, QComboBox, QCompleter, QDialog, QDialogButtonBox,
    QGridLayout, QHeaderView, QLabel, QLineEdit, QPlainTextEdit, QScrollArea,
    QTableWidget, QTableWidgetItem, QWidget,
)

from yumekai_importer.catalog.classification import DEMOGRAPHICS
from yumekai_importer.catalog.collection_edit import (
    COLLECTION_FIELDS, collection_changes, collection_key, collection_products, common_value,
)
from yumekai_importer.catalog.review_fields import BOOK_FORMATS, PAGES_INPUT
from yumekai_importer.catalog.review_workflow import WORK_TYPES
from yumekai_importer.ui.widgets.change_review_dialog import ChangeReviewDialog
from yumekai_importer.ui.widgets.presentation import review_dialog_layout, style_button_box


class CollectionEditDialog(QDialog):
    def __init__(self, products, parent=None, *, tab_label="Por revisar", initial_series=None):
        super().__init__(parent)
        self.setWindowTitle("Editar colección por lote")
        self.setObjectName("collectionEditDialog")
        self._products = products
        self.changes = {}
        self._checks, self._editors = {}, {}
        screen = self.screen().availableGeometry() if self.screen() else None
        self.resize(min(880, screen.width() - 40) if screen else 880,
                    min(820, screen.height() - 60) if screen else 760)
        layout = review_dialog_layout(self)
        hint = QLabel(
            f"Elige una colección de «{tab_label}». Se incluyen sus fichas aunque estén ocultas por los filtros "
            "de la tabla. Marca solo los campos que quieras reemplazar en todos sus tomos."
        )
        hint.setTextFormat(Qt.TextFormat.PlainText)
        hint.setObjectName("dialogDescription")
        hint.setWordWrap(True)
        layout.addWidget(hint)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        body = QWidget()
        grid = QGridLayout(body)
        grid.setContentsMargins(0, 0, 10, 0)
        grid.setHorizontalSpacing(18)
        grid.setVerticalSpacing(10)
        grid.setColumnStretch(1, 1)
        self._collection = QComboBox()
        self._collection.setEditable(True)
        self._collection.setInsertPolicy(QComboBox.InsertPolicy.NoInsert)
        self._collection.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
        self._collection.setMinimumContentsLength(18)
        self._collection.lineEdit().setPlaceholderText("Escribe para buscar una colección…")
        self._collection.setAccessibleName("Colección que se editará por lote")
        series = {}
        for product in products.values():
            value = " ".join(str(product.get("series") or "").split())
            if value:
                series.setdefault(collection_key(value), value)
        for key in sorted(series):
            self._collection.addItem(series[key], key)
        self._collection.setCurrentIndex(-1)
        completer = self._collection.completer()
        completer.setCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)
        completer.setFilterMode(Qt.MatchFlag.MatchContains)
        completer.setCompletionMode(QCompleter.CompletionMode.PopupCompletion)
        self._publisher = QComboBox()
        self._publisher.setAccessibleName("Limitar la colección a una editorial")
        grid.addWidget(QLabel("Colección"), 0, 0)
        grid.addWidget(self._collection, 0, 1)
        grid.addWidget(QLabel("Editorial"), 1, 0)
        grid.addWidget(self._publisher, 1, 1)
        self._summary = QLabel()
        self._summary.setTextFormat(Qt.TextFormat.PlainText)
        self._summary.setWordWrap(True)
        self._summary.setObjectName("reviewSummary")
        grid.addWidget(self._summary, 2, 0, 1, 2)

        self._table = QTableWidget(0, 4)
        self._table.setHorizontalHeaderLabels(("Título", "ISBN", "Editorial", "Tomo"))
        self._table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self._table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self._table.setAlternatingRowColors(True)
        self._table.setShowGrid(False)
        self._table.verticalHeader().hide()
        self._table.verticalHeader().setDefaultSectionSize(32)
        self._table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self._table.setColumnWidth(1, 155)
        self._table.setColumnWidth(2, 140)
        self._table.setColumnWidth(3, 60)
        self._table.setMinimumHeight(115)
        self._table.setMaximumHeight(170)
        grid.addWidget(self._table, 3, 0, 1, 2)
        field_hint = QLabel("Los valores comunes se muestran como ayuda. Los campos desmarcados se conservan.")
        field_hint.setObjectName("reviewHint")
        field_hint.setWordWrap(True)
        grid.addWidget(field_hint, 4, 0, 1, 2)
        choices = {"work_type": WORK_TYPES, "demographic": DEMOGRAPHICS, "book_format": BOOK_FORMATS}
        for row, (field, label) in enumerate(COLLECTION_FIELDS, 5):
            check = QCheckBox(label)
            check.setToolTip(f"Reemplazar {label.lower()} en todas las fichas indicadas arriba")
            if field in choices:
                editor = QComboBox()
                editor.addItem("Selecciona…", None)
                for value in choices[field]:
                    editor.addItem(value, value)
            elif field == "pages":
                editor = QLineEdit()
                editor.setPlaceholderText("Número entero de páginas")
                editor.setValidator(QRegularExpressionValidator(QRegularExpression(PAGES_INPUT), editor))
            else:
                editor = QPlainTextEdit()
                editor.setPlaceholderText("Sinopsis común que se aplicará a todos los tomos…")
                editor.setMinimumHeight(115)
            editor.setAccessibleName(label + " común para la colección")
            self._checks[field], self._editors[field] = check, editor
            check.toggled.connect(self._field_toggled)
            if isinstance(editor, QComboBox):
                editor.currentIndexChanged.connect(self._update_fields)
            grid.addWidget(check, row, 0, Qt.AlignmentFlag.AlignTop)
            grid.addWidget(editor, row, 1)
        self._demographic_hint = QLabel()
        self._demographic_hint.setObjectName("reviewHint")
        self._demographic_hint.setWordWrap(True)
        grid.addWidget(self._demographic_hint, 10, 0, 1, 2)
        scroll.setWidget(body)
        layout.addWidget(scroll, 1)
        self._error = QLabel()
        self._error.setObjectName("reviewValidationError")
        self._error.setWordWrap(True)
        self._error.setTextFormat(Qt.TextFormat.PlainText)
        self._error.hide()
        layout.addWidget(self._error)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        self._preview = buttons.button(QDialogButtonBox.StandardButton.Ok)
        self._preview.setText("Revisar cambios…")
        buttons.button(QDialogButtonBox.StandardButton.Cancel).setText("Cancelar")
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        style_button_box(buttons)
        layout.addWidget(buttons)
        self._collection.currentTextChanged.connect(self._collection_changed)
        self._publisher.currentIndexChanged.connect(self._scope_changed)
        self._collection_changed()
        if initial_series and collection_key(initial_series) in series:
            self._collection.setCurrentIndex(self._collection.findData(collection_key(initial_series)))

    def _targets(self):
        return collection_products(self._products, self._collection.currentText(), self._publisher.currentData())

    def _collection_changed(self, *_):
        products = collection_products(self._products, self._collection.currentText())
        publishers = {}
        for product in products.values():
            value = str(product.get("publisher") or "").strip()
            publishers.setdefault(collection_key(value), value)
        with QSignalBlocker(self._publisher):
            self._publisher.clear()
            self._publisher.addItem("Todas las editoriales", None)
            for _, value in sorted(publishers.items()):
                self._publisher.addItem(value or "Sin editorial", value)
        self._scope_changed()

    def _scope_changed(self, *_):
        products = self._targets()
        self._summary.setText(
            f"{len(products)} ficha(s) de esta colección en la pestaña actual. "
            "La otra pestaña conserva sus datos."
            if products else "Selecciona una colección de la lista. Las fichas sin colección no se agrupan."
        )
        self._table.setRowCount(len(products))
        for row, product in enumerate(products.values()):
            for column, field in enumerate(("title", "isbn", "publisher", "volume")):
                value = str(product.get(field) or "")
                item = QTableWidgetItem(value)
                item.setToolTip(value)
                self._table.setItem(row, column, item)
        for field, editor in self._editors.items():
            with QSignalBlocker(self._checks[field]), QSignalBlocker(editor):
                self._checks[field].setChecked(False)
                value = common_value(products, field)
                if isinstance(editor, QComboBox):
                    editor.setCurrentIndex(max(0, editor.findData(value)))
                elif isinstance(editor, QPlainTextEdit):
                    editor.setPlainText(str(value or ""))
                else:
                    editor.setText(str(value or ""))
        self._error.hide()
        self._update_fields()

    def _field_toggled(self, *_):
        self._error.hide()
        self._update_fields()

    def _update_fields(self, *_):
        products = self._targets()
        effective_type = self._editors["work_type"].currentData() if self._checks["work_type"].isChecked() else None
        manga = bool(products) and (
            effective_type == "Manga" if self._checks["work_type"].isChecked()
            else all(product.get("work_type") == "Manga" for product in products.values())
        )
        if not manga:
            with QSignalBlocker(self._checks["demographic"]):
                self._checks["demographic"].setChecked(False)
        for field, editor in self._editors.items():
            available = bool(products) and (field != "demographic" or manga)
            self._checks[field].setEnabled(available)
            editor.setEnabled(available and self._checks[field].isChecked())
        self._demographic_hint.setText(
            "La demografía se aplica a Manga. Para cambiarla en una colección con otros tipos de obra, "
            "marca Tipo de obra y elige Manga."
        )
        self._demographic_hint.setVisible(bool(products) and not manga)
        self._preview.setEnabled(bool(products) and any(check.isChecked() for check in self._checks.values()))

    def accept(self):
        values = {}
        for field, editor in self._editors.items():
            if not self._checks[field].isChecked():
                continue
            values[field] = (editor.currentData() if isinstance(editor, QComboBox)
                             else editor.toPlainText() if isinstance(editor, QPlainTextEdit) else editor.text())
        try:
            self.changes = collection_changes(self._targets(), values)
            if not self.changes:
                raise ValueError("Los valores elegidos ya coinciden en toda la colección. No hay cambios que guardar.")
        except ValueError as error:
            self._error.setText(str(error))
            self._error.show()
            return
        super().accept()


def review_collection_changes(rows, parent=None):
    dialog = ChangeReviewDialog(rows, parent=parent)
    dialog.setWindowTitle("Revisar edición de colección")
    dialog.findChild(QLabel, "dialogTitle").setText(dialog.windowTitle())
    dialog.message.setText(
        "Revisa los valores actuales y propuestos para cada tomo. Puedes desmarcar cambios individuales. "
        "Doble clic en un valor para leer el texto completo. Al confirmar se guardarán solo los cambios "
        "marcados de esta edición por lote. Cancelar conserva tus cambios pendientes anteriores "
        "sin aplicar esta edición."
    )
    accepted = dialog.exec() == QDialog.DialogCode.Accepted
    result = dialog.accepted_changes if accepted else None
    dialog.deleteLater()
    return result
