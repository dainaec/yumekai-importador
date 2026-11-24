from PySide6.QtCore import QPointF, QRectF, QRegularExpression, Qt
from PySide6.QtGui import QColor, QPainter, QPen, QPolygonF, QRegularExpressionValidator
from PySide6.QtWidgets import (
    QCheckBox,
    QLabel,
    QLineEdit,
    QStyle,
    QStyleOptionButton,
    QVBoxLayout,
    QWidget,
)

from yumekai_importer.catalog.review_fields import ISBN_INPUT, normalize_review_identifier


class ReviewCheckBox(QCheckBox):
    def __init__(self, text: str) -> None:
        super().__init__(text)
        self.setStyleSheet(
            "QCheckBox::indicator { width: 17px; height: 17px; border: 0; background: transparent; }"
        )

    def paintEvent(self, event) -> None:
        super().paintEvent(event)
        option = QStyleOptionButton()
        self.initStyleOption(option)
        indicator = self.style().subElementRect(QStyle.SubElement.SE_CheckBoxIndicator, option, self)
        box = QRectF(indicator).adjusted(1, 1, -1, -1)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(QPen(QColor("#896B84"), 1.2))
        painter.setBrush(QColor("#FDE48A" if self.isChecked() else "#FFFFFF"))
        painter.drawRoundedRect(box, 3, 3)
        if self.isChecked():
            center = box.center()
            pen = QPen(QColor("#513C4E"), 1.8)
            pen.setCapStyle(Qt.PenCapStyle.RoundCap)
            pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
            painter.setPen(pen)
            painter.drawPolyline(QPolygonF([
                center + QPointF(-4, 0),
                center + QPointF(-1, 3),
                center + QPointF(4, -3),
            ]))
        painter.end()


class IsbnField(QWidget):
    def __init__(self, original: object, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.original = "" if original is None else str(original)
        self.editor = QLineEdit(self.original)
        self.editor.setReadOnly(True)
        self.editor.setCursorPosition(0)
        self.editor.setValidator(QRegularExpressionValidator(QRegularExpression(ISBN_INPUT), self.editor))
        self.unlock = ReviewCheckBox("Corregir ISBN")
        self.warning = QLabel(
            "Comprueba el ISBN en el código de barras de esta edición. "
            "Cambiarlo modifica el identificador de la ficha y el SKU que se generará."
        )
        self.warning.setObjectName("isbnWarning")
        self.warning.setTextFormat(Qt.TextFormat.PlainText)
        self.warning.setWordWrap(True)
        self.warning.hide()

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(5)
        layout.addWidget(self.editor)
        layout.addWidget(self.unlock)
        layout.addWidget(self.warning)
        self.setFocusProxy(self.editor)
        self.unlock.toggled.connect(self._set_unlocked)

    def _set_unlocked(self, unlocked: bool) -> None:
        self.editor.setReadOnly(not unlocked)
        self.warning.setVisible(unlocked)
        if unlocked:
            self.editor.setFocus()
            self.editor.selectAll()
        else:
            self.editor.setText(self.original)
            self.editor.setCursorPosition(0)

    def corrected_isbn(self) -> str | None:
        if not self.unlock.isChecked():
            return None
        return normalize_review_identifier(self.editor.text())
