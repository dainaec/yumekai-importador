from yumekai_importer.ui.widgets.presentation import review_dialog_layout, style_button_box, button_role
from itertools import pairwise

from PySide6.QtCore import QPointF, QRegularExpression, Qt
from PySide6.QtGui import (
    QColor,
    QPainter,
    QPalette,
    QPen,
    QPolygonF,
    QRegularExpressionValidator,
    QResizeEvent,
)
from PySide6.QtWidgets import (
    QComboBox,
    QCompleter,
    QDialog,
    QDialogButtonBox,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPlainTextEdit,
    QScrollArea,
    QScrollBar,
    QStyle,
    QStyleOptionComboBox,
    QStyleOptionSlider,
    QVBoxLayout,
    QWidget,
)

from yumekai_importer.catalog.review_fields import (
    BOOK_FORMATS,
    PAGES_INPUT,
    PRICE_INPUT,
    VOLUME_INPUT,
    normalize_pages,
    normalize_price,
    normalize_review_identifier,
    normalize_volume,
    review_categories,
    sale_price_preview,
)
from yumekai_importer.ui.widgets.isbn_field import IsbnField, ReviewCheckBox
from yumekai_importer.catalog.classification import DEMOGRAPHICS, canonical_demographic
from yumekai_importer.catalog.exception_rules import required_issues


_WORK_FIELDS = (
    ("author", "publisher"),
    ("series", "language"),
    ("volume", "pages"),
    ("book_format",),
    ("work_type", "demographic"),
)
_CATALOG_FIELDS = (
    ("retail_price", "sale_price"),
    ("yumekai_status", "is_featured"),
    ("sku",),
    ("categories",),
    ("image_url",),
)


_NUMERIC_FIELDS = {
    "volume": (VOLUME_INPUT, normalize_volume),
    "pages": (PAGES_INPUT, normalize_pages),
    "retail_price": (PRICE_INPUT, normalize_price),
}
_COMPUTED_FIELDS = {"isbn", "sale_price", "sku", "categories"}


def _draw_chevron(painter: QPainter, center: QPointF, direction: int, enabled: bool) -> None:
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    pen = QPen(QColor("#6F556A" if enabled else "#A59BA6"), 1.5)
    pen.setCapStyle(Qt.PenCapStyle.RoundCap)
    pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
    painter.setPen(pen)
    painter.drawPolyline(QPolygonF([
        center + QPointF(-3.5, -1.5 * direction),
        center + QPointF(0, 2 * direction),
        center + QPointF(3.5, -1.5 * direction),
    ]))


class _ReviewComboBox(QComboBox):
    def paintEvent(self, event) -> None:
        super().paintEvent(event)
        option = QStyleOptionComboBox()
        self.initStyleOption(option)
        arrow = self.style().subControlRect(
            QStyle.ComplexControl.CC_ComboBox, option, QStyle.SubControl.SC_ComboBoxArrow, self
        )
        painter = QPainter(self)
        _draw_chevron(painter, QPointF(arrow.center()), 1, self.isEnabled())
        painter.end()


class _ReviewScrollBar(QScrollBar):
    def __init__(self) -> None:
        super().__init__(Qt.Orientation.Vertical)

    def paintEvent(self, event) -> None:
        super().paintEvent(event)
        option = QStyleOptionSlider()
        self.initStyleOption(option)
        painter = QPainter(self)
        for control, direction in (
            (QStyle.SubControl.SC_ScrollBarSubLine, -1),
            (QStyle.SubControl.SC_ScrollBarAddLine, 1),
        ):
            arrow = self.style().subControlRect(
                QStyle.ComplexControl.CC_ScrollBar, option, control, self
            )
            _draw_chevron(painter, QPointF(arrow.center()), direction, self.isEnabled())
        painter.end()


class ProductReviewDialog(QDialog):
    def __init__(
        self,
        product: dict[str, object],
        columns: tuple[tuple[str, str, int], ...],
        stock_labels: dict[str, str],
        parent: QWidget | None = None,
        *,
        suggestions: dict[str, list[str]] | None = None,
        reviewed: bool = False,
        existing_isbns: set[str] | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("Editar ficha")
        self.setObjectName("productReviewDialog")

        palette = self.palette()
        for role, color in (
            (QPalette.ColorRole.Window, "#FFFFFF"),
            (QPalette.ColorRole.Base, "#FFFFFF"),
            (QPalette.ColorRole.Button, "#F7F5F8"),
            (QPalette.ColorRole.WindowText, "#201A22"),
            (QPalette.ColorRole.Text, "#201A22"),
            (QPalette.ColorRole.ButtonText, "#201A22"),
            (QPalette.ColorRole.Highlight, "#ECD7E8"),
            (QPalette.ColorRole.HighlightedText, "#201A22"),
            (QPalette.ColorRole.PlaceholderText, "#695D6E"),
        ):
            palette.setColor(role, QColor(color))
        self.setPalette(palette)

        self.changes: dict[str, object] = {}
        self._product = dict(product)
        self.ready_to_upload = reviewed
        self._editors: dict[str, QWidget] = {}
        self._stored_sku = str(product.get("sku") or "")
        self._existing_isbns = existing_isbns or set()
        suggestions = suggestions or {}

        self._isbn = IsbnField(product.get("isbn"))
        self._ready = ReviewCheckBox("Lista para subir")
        self._ready.setChecked(reviewed)
        self._ready.setToolTip("Marca esta opción y pulsa Guardar ficha para pasarla a Listas para subir.")

        work_types = ("Manga", "Manhwa", "Manhua")
        demographics = DEMOGRAPHICS
        choices = {
            "work_type": [(None, "Por completar"), *((name, name) for name in work_types)],
            "demographic": [(None, "Por completar"), *((name, name) for name in demographics)],
            "book_format": [(None, "Por completar"), *((name, name) for name in BOOK_FORMATS)],
            "yumekai_status": [(None, "Por comprobar"), *stock_labels.items()],
            "is_featured": [(0, "No"), (1, "Sí")],
        }

        labels = {field: label for field, label, _ in columns}
        for field in labels:
            value = product.get(field)
            if field == "demographic":
                value = canonical_demographic(value)
            if field == "isbn":
                editor = self._isbn
            elif field in {"author", "publisher"}:
                editor = _ReviewComboBox()
                editor.setEditable(True)
                editor.setInsertPolicy(QComboBox.InsertPolicy.NoInsert)
                editor.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
                editor.setMinimumContentsLength(7)
                editor.addItems(suggestions.get(field, []))
                editor.setEditText(str(value or ""))
                editor.lineEdit().setCursorPosition(0)
                completer = editor.completer()
                completer.setCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)
                completer.setFilterMode(Qt.MatchFlag.MatchContains)
                completer.setCompletionMode(QCompleter.CompletionMode.PopupCompletion)
            elif field in choices:
                editor = _ReviewComboBox()
                for code, caption in choices[field]:
                    editor.addItem(caption, code)

                if field == "is_featured":
                    value = int(value in (1, "1"))
                index = editor.findData(None if value == "" else value)
                if index < 0:
                    editor.addItem(str(value), value)
                    index = editor.count() - 1
                editor.setCurrentIndex(index)
                if field == "demographic":
                    editor.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
                    editor.setMinimumContentsLength(10)
                    editor.view().setMinimumWidth(260)
                    editor.setToolTip(editor.currentText())
                    editor.currentTextChanged.connect(editor.setToolTip)
            elif field == "categories":
                editor = QPlainTextEdit()
                editor.setVerticalScrollBar(_ReviewScrollBar())
                editor.setReadOnly(True)
                editor.setPlaceholderText("Se genera con el tipo de obra")
                editor.setFixedHeight(64)
            elif field == "description":
                editor = QPlainTextEdit(str(value or ""))
                editor.setVerticalScrollBar(_ReviewScrollBar())
                editor.setFixedHeight(112)
            else:
                text = "" if value is None else str(value)
                if field in {"retail_price", "sale_price"}:
                    text = text.replace(".", ",")
                editor = QLineEdit(text)
                editor.setCursorPosition(0)
                editor.setReadOnly(field in _COMPUTED_FIELDS)
                if field in _NUMERIC_FIELDS:
                    pattern, _ = _NUMERIC_FIELDS[field]
                    validator = QRegularExpressionValidator(QRegularExpression(pattern), editor)
                    editor.setValidator(validator)
                if field == "sku":
                    editor.setPlaceholderText("Se genera al guardar como lista")

            self._editors[field] = editor

        self._initial = {
            field: self._value(editor)
            for field, editor in self._editors.items()
            if field not in _COMPUTED_FIELDS
        }
        self._editors["work_type"].currentIndexChanged.connect(self._sync_categories)
        self._editors["demographic"].currentIndexChanged.connect(self._sync_categories)
        self._sync_categories()
        self._editors["retail_price"].textChanged.connect(self._sync_sale_price)
        self._isbn.editor.textChanged.connect(self._sync_sku)
        self._ready.toggled.connect(self._sync_sku)
        self._sync_sku()

        identity_rows = (("title", "isbn"),)
        synopsis_rows = (("description",),)
        arranged_fields = {
            field
            for row in identity_rows + _WORK_FIELDS + _CATALOG_FIELDS + synopsis_rows
            for field in row
        }
        catalog_rows = _CATALOG_FIELDS + tuple(
            (field,) for field in labels if field not in arranged_fields
        )

        identity = self._field_grid(identity_rows, labels)
        identity.setColumnStretch(0, 3)

        work_fields = self._field_grid(_WORK_FIELDS, labels)
        self._sections = QHBoxLayout()
        self._sections.setSpacing(16)
        self._sections.addWidget(self._section("Datos de la obra", work_fields), 1)
        self._sections.addWidget(self._section("Catálogo", self._field_grid(catalog_rows, labels)), 1)

        content = QWidget()
        content.setObjectName("productReviewFields")
        content.setAttribute(Qt.WidgetAttribute.WA_StyledBackground)
        content_layout = QVBoxLayout(content)
        content_layout.setContentsMargins(0, 0, 10, 4)
        content_layout.setSpacing(16)
        content_layout.addLayout(identity)
        content_layout.addWidget(self._isbn.warning)
        content_layout.addLayout(self._sections)
        if "description" in self._editors:
            content_layout.addWidget(self._section("", self._field_grid(synopsis_rows, labels)))
        content_layout.addStretch(1)

        self._scroll = QScrollArea()
        self._scroll.setObjectName("productReviewScroll")
        self._scroll.viewport().setObjectName("productReviewViewport")
        self._scroll.setVerticalScrollBar(_ReviewScrollBar())
        self._scroll.setWidgetResizable(True)
        self._scroll.setWidget(content)

        self._error = QLabel()
        self._error.setObjectName("reviewValidationError")
        self._error.setTextFormat(Qt.TextFormat.PlainText)
        self._error.setWordWrap(True)
        self._error.hide()

        buttons = QDialogButtonBox()
        buttons.addButton("Guardar ficha", QDialogButtonBox.ButtonRole.AcceptRole)
        cancel_button = buttons.addButton("Cancelar", QDialogButtonBox.ButtonRole.RejectRole)
        cancel_button.setObjectName("clearButton")
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)

        layout = review_dialog_layout(self)
        layout.setContentsMargins(22, 18, 22, 16)
        layout.setSpacing(12)
        layout.addWidget(self._scroll, 1)
        layout.addWidget(self._error)
        footer = QHBoxLayout()
        footer.addWidget(self._ready)
        footer.addStretch()
        style_button_box(buttons)
        footer.addWidget(buttons)
        layout.addLayout(footer)
        self.setStyleSheet(_REVIEW_STYLE)

        tab_order = [
            self._editors[field]
            for row in identity_rows + _WORK_FIELDS + catalog_rows + synopsis_rows
            for field in row
            if field in self._editors
        ]
        isbn_index = tab_order.index(self._isbn)
        tab_order[isbn_index:isbn_index + 1] = [self._isbn.editor, self._isbn.unlock]
        tab_order.append(self._ready)
        for previous, following in pairwise(tab_order):
            self.setTabOrder(previous, following)

        screen = parent.screen() if parent is not None else self.screen()
        if screen is None:
            self.resize(880, 650)
        else:
            available = screen.availableGeometry()
            self.resize(min(880, available.width() - 32), min(650, available.height() - 52))

    def resizeEvent(self, event: QResizeEvent) -> None:
        direction = (
            QHBoxLayout.Direction.TopToBottom if event.size().width() < 840
            else QHBoxLayout.Direction.LeftToRight
        )
        if self._sections.direction() != direction:
            self._sections.setDirection(direction)
            self._scroll.widget().updateGeometry()
        super().resizeEvent(event)

    def _field_grid(
        self, rows: tuple[tuple[str, ...], ...], labels: dict[str, str]
    ) -> QGridLayout:
        grid = QGridLayout()
        grid.setHorizontalSpacing(12)
        grid.setVerticalSpacing(10)
        grid.setColumnStretch(0, 1)
        grid.setColumnStretch(1, 1)

        for row, fields in enumerate(rows):
            present = [field for field in fields if field in self._editors]
            for column, field in enumerate(present):
                editor = self._editors[field]
                label = QLabel(labels[field])
                label.setObjectName("reviewFieldLabel")
                label.setBuddy(editor)
                cell = QVBoxLayout()
                cell.setSpacing(4)
                cell.addWidget(label)
                cell.addWidget(editor)
                grid.addLayout(
                    cell, row, column, 1, 2 if len(present) == 1 else 1, Qt.AlignmentFlag.AlignTop
                )

        return grid

    @staticmethod
    def _section(title: str, fields: QGridLayout) -> QFrame:
        section = QFrame()
        section.setObjectName("reviewSection")
        layout = QVBoxLayout(section)
        layout.setContentsMargins(16, 14, 16, 15)
        layout.setSpacing(12)
        if title:
            heading = QLabel(title)
            heading.setObjectName("reviewSectionTitle")
            layout.addWidget(heading)
        layout.addLayout(fields)
        layout.addStretch(1)
        return section

    @staticmethod
    def _value(editor):
        if isinstance(editor, QComboBox):
            return editor.currentText() if editor.isEditable() else editor.currentData()
        if isinstance(editor, QPlainTextEdit):
            return editor.toPlainText()
        return editor.text()

    def _sync_categories(self) -> None:
        work_type = self._editors["work_type"].currentData()
        is_manga = str(work_type or "").casefold() == "manga"
        demographic = self._editors["demographic"]
        demographic.setEnabled(is_manga)
        categories = review_categories(work_type, demographic.currentData())
        self._editors["categories"].setPlainText("\n".join(categories))

    def _sync_sku(self) -> None:
        sku = self._stored_sku
        if self._ready.isChecked():
            try:
                sku = f"YMK-{normalize_review_identifier(self._isbn.editor.text())}"
            except ValueError:
                sku = ""
        self._editors["sku"].setText(sku)

    def _sync_sale_price(self, text: str) -> None:
        try:
            price = normalize_price(text.strip())
            preview = sale_price_preview(price)
        except ValueError:
            preview = None
        self._editors["sale_price"].setText((preview or "").replace(".", ","))

    def accept(self) -> None:
        changes = {}
        try:
            isbn = self._isbn.corrected_isbn()
            if isbn is not None and isbn != self._isbn.original and isbn in self._existing_isbns:
                raise ValueError(f"Ya existe una ficha con el ISBN {isbn}.")
        except ValueError as error:
            self._show_error(str(error), self._isbn.editor)
            return

        if isbn is not None and isbn != self._isbn.original:
            changes["isbn"] = isbn

        for field, initial in self._initial.items():
            editor = self._editors[field]
            value = self._value(editor)
            if value == initial or not editor.isEnabled():
                continue

            try:
                normalized = self._normalize(field, value)
            except ValueError as error:
                self._show_error(str(error), editor)
                return
            if value != initial:
                changes[field] = normalized

        self.changes = changes
        self.ready_to_upload = self._ready.isChecked()
        if self.ready_to_upload:
            issues = required_issues({**self._product, **changes})
            if issues:
                self._show_error(" · ".join(issues), self._editors["yumekai_status"])
                return
        super().accept()

    def _show_error(self, message: str, editor: QWidget) -> None:
        self._error.setText(message)
        self._error.show()
        self._scroll.ensureWidgetVisible(editor)
        editor.setFocus()

    @staticmethod
    def _normalize(field: str, value: object) -> object:
        if value is None or isinstance(value, int):
            return value

        text = str(value).strip()
        if field in _NUMERIC_FIELDS:
            _, normalize = _NUMERIC_FIELDS[field]
            return normalize(text)
        return text or None


_REVIEW_STYLE = """
QDialog#productReviewDialog,
QScrollArea#productReviewScroll,
QWidget#productReviewFields,
QWidget#productReviewViewport {
    background-color: #FFFFFF;
}

QScrollArea#productReviewScroll { border: 0; }

QFrame#reviewSection {
    background-color: #FCFAFC;
    border: 1px solid #DED9E0;
    border-radius: 10px;
}

QLabel#reviewSectionTitle {
    color: #513C4E;
    font-size: 15px;
    font-weight: bold;
}

QLabel#reviewFieldLabel { color: #312735; font-weight: 600; }

QLineEdit, QComboBox, QPlainTextEdit {
    background-color: #FFFFFF;
    color: #201A22;
    border: 1px solid #CDC5D0;
    border-radius: 6px;
    padding: 6px 9px;
    selection-background-color: #ECD7E8;
    selection-color: #201A22;
}

QLineEdit, QComboBox { min-height: 18px; }

QLineEdit:read-only, QComboBox:disabled, QPlainTextEdit:read-only {
    background-color: #F3F0F4;
    color: #645866;
}

QLineEdit:focus, QComboBox:focus, QPlainTextEdit:focus { border-color: #896B84; }

QComboBox {
    padding-right: 26px;
    combobox-popup: 0;
}

QComboBox:editable QLineEdit {
    border: 0;
    padding: 0;
}

QComboBox::drop-down {
    subcontrol-origin: padding;
    subcontrol-position: top right;
    border: 0;
    width: 24px;
}

QComboBox::down-arrow, QScrollBar::up-arrow:vertical, QScrollBar::down-arrow:vertical {
    width: 0;
    height: 0;
}

QAbstractItemView {
    background-color: #FFFFFF;
    color: #201A22;
    border: 1px solid #CDC5D0;
    selection-background-color: #ECD7E8;
    selection-color: #201A22;
    outline: 0;
}

QScrollBar { background-color: #F7F5F8; border: 0; margin: 0; }
QScrollBar:vertical { width: 12px; margin: 14px 0; }
QScrollBar:horizontal { height: 12px; }
QScrollBar::handle { background-color: #A1849D; border-radius: 5px; }
QScrollBar::handle:hover { background-color: #896B84; }
QScrollBar::handle:vertical { min-height: 28px; }
QScrollBar::handle:horizontal { min-width: 28px; }

QScrollBar::sub-line:vertical {
    height: 14px;
    background-color: #F0E8F1;
    subcontrol-origin: margin;
    subcontrol-position: top;
}

QScrollBar::add-line:vertical {
    height: 14px;
    background-color: #F0E8F1;
    subcontrol-origin: margin;
    subcontrol-position: bottom;
}

QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {
    width: 0;
    height: 0;
}

QScrollBar::add-page, QScrollBar::sub-page { background: transparent; }

QLabel#isbnWarning {
    color: #654B16;
    background-color: #FFF7DF;
    border: 1px solid #E6D4A3;
    border-radius: 6px;
    padding: 8px 10px;
}

QLabel#reviewValidationError {
    color: #752E43;
    background-color: #FBEFF3;
    border: 1px solid #E9CFD8;
    border-radius: 6px;
    padding: 8px 10px;
}
"""
