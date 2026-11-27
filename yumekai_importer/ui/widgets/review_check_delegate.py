from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QColor, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import (
    QApplication,
    QStyle,
    QStyledItemDelegate,
    QStyleOptionViewItem,
)

from yumekai_importer.ui.styles.theme_colors import theme_color
from yumekai_importer.ui.widgets.themed_item_delegate import ThemedItemDelegate


class ReviewCheckDelegate(ThemedItemDelegate):
    def paint(self, painter, option, index) -> None:
        cell = QStyleOptionViewItem(option)
        self.initStyleOption(cell, index)
        indicator = QStyleOptionViewItem.ViewItemFeature.HasCheckIndicator

        if not cell.features & indicator:
            super().paint(painter, option, index)
            return

        widget = cell.widget
        style = widget.style() if widget is not None else QApplication.style()
        checked = cell.checkState == Qt.CheckState.Checked
        rect = style.subElementRect(
            QStyle.SubElement.SE_ItemViewItemCheckIndicator, cell, widget
        )
        square = QRectF(rect).adjusted(0.75, 0.75, -0.75, -0.75)
        cell.features &= ~indicator

        painter.save()
        style.drawControl(QStyle.ControlElement.CE_ItemViewItem, cell, painter, widget)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(QPen(theme_color("#765A73"), 1.5))
        painter.setBrush(theme_color("#ECD7E8" if checked else "#FFFFFF"))
        painter.drawRoundedRect(square, 4, 4)

        if checked:
            painter.translate(square.left(), square.top())
            width, height = square.width(), square.height()
            tick = QPainterPath()
            tick.moveTo(width * 0.23, height * 0.52)
            tick.lineTo(width * 0.43, height * 0.71)
            tick.lineTo(width * 0.77, height * 0.32)
            pen = QPen(theme_color("#4D354C"), 2)
            pen.setCapStyle(Qt.PenCapStyle.RoundCap)
            pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
            painter.strokePath(tick, pen)

        painter.restore()