from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QColor, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import (
    QApplication,
    QStyle,
    QStyledItemDelegate,
    QStyleOptionViewItem,
)


class ReviewCheckDelegate(QStyledItemDelegate):
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
        painter.setPen(QPen(QColor("#765A73"), 1.5))
        painter.setBrush(QColor("#ECD7E8" if checked else "#FFFFFF"))
        painter.drawRoundedRect(square, 4, 4)

        if checked:
            painter.translate(square.left(), square.top())
            width, height = square.width(), square.height()
            tick = QPainterPath()
            tick.moveTo(width * 0.23, height * 0.52)
            tick.lineTo(width * 0.43, height * 0.71)
            tick.lineTo(width * 0.77, height * 0.32)
            pen = QPen(QColor("#4D354C"), 2)
            pen.setCapStyle(Qt.PenCapStyle.RoundCap)
            pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
            painter.strokePath(tick, pen)

        painter.restore()