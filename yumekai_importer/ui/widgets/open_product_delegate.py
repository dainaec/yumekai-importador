from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QColor, QPainter
from PySide6.QtWidgets import QApplication, QStyle, QStyledItemDelegate, QStyleOptionViewItem

from yumekai_importer.ui.widgets.themed_item_delegate import ThemedItemDelegate


class OpenProductDelegate(ThemedItemDelegate):
    def paint(self, painter, option, index) -> None:
        cell = QStyleOptionViewItem(option)
        self.initStyleOption(cell, index)
        symbol = cell.text
        cell.text = ""

        widget = cell.widget
        style = widget.style() if widget is not None else QApplication.style()
        style.drawControl(QStyle.ControlElement.CE_ItemViewItem, cell, painter, widget)

        button = QRectF(0, 0, 24, 22)
        button.moveCenter(QRectF(cell.rect).center())
        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(QColor("#B9A66A"))
        painter.setBrush(QColor("#FFF1BF"))
        painter.drawRoundedRect(button, 5, 5)

        font = painter.font()
        font.setBold(True)
        font.setPixelSize(16)
        painter.setFont(font)
        painter.setPen(QColor("#4D354C"))
        painter.drawText(button, Qt.AlignmentFlag.AlignCenter.value, symbol)
        painter.restore()
