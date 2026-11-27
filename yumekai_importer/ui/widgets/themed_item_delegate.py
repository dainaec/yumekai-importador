"""Adapt custom row colours at paint time without changing model data."""

from PySide6.QtCore import Qt
from PySide6.QtGui import QBrush
from PySide6.QtWidgets import QStyledItemDelegate

from yumekai_importer.ui.styles.theme_colors import theme_color


class ThemedItemDelegate(QStyledItemDelegate):
    def initStyleOption(self, option, index):
        super().initStyleOption(option, index)
        if option.backgroundBrush.style() == Qt.BrushStyle.SolidPattern:
            color = option.backgroundBrush.color()
            themed = theme_color(color.name())
            themed.setAlpha(color.alpha())
            option.backgroundBrush = QBrush(themed)
