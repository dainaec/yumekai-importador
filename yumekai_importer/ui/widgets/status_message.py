"""Consistent, dismissible feedback for catalog screens."""
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QHBoxLayout, QLabel, QToolButton, QWidget

from yumekai_importer.ui.styles.theme_switcher import set_theme_stylesheet


class StatusMessage(QWidget):
    COLORS = {
        'info': ('#EFF6FF', '#24538C', '#C7DCF5', 'ⓘ'),
        'success': ('#F0FDF4', '#166534', '#BBE5C8', '✓'),
        'warning': ('#FFF8E4', '#7B5A19', '#E7D59B', '!'),
        'error': ('#FEF2F2', '#991B1B', '#F2CCCC', '!'),
    }

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName('feedbackContainer')
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.icon = QLabel()
        self.icon.setFixedWidth(22)
        self.icon.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.label = QLabel()
        self.label.setTextFormat(Qt.TextFormat.PlainText)
        self.label.setWordWrap(True)
        self.close_button = QToolButton()
        self.close_button.setText('×')
        self.close_button.setToolTip('Cerrar aviso')
        self.close_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.close_button.setFixedSize(24, 24)
        self.close_button.clicked.connect(self.hide)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(10, 9, 8, 9)
        layout.setSpacing(8)
        layout.addWidget(self.icon)
        layout.addWidget(self.label, 1)
        layout.addWidget(self.close_button)
        self.hide()

    def set_message(self, message, kind='info'):
        background, text, border, glyph = self.COLORS.get(kind, self.COLORS['info'])
        set_theme_stylesheet(self, f'''
            QWidget#feedbackContainer {{ background: {background}; border: 1px solid {border}; border-radius: 7px; }}
            QLabel {{ background: transparent; color: {text}; border: 0; padding: 0; }}
            QToolButton {{ background: transparent; color: {text}; border: 0; border-radius: 4px; font-size: 18px; }}
            QToolButton:hover {{ background: {border}; }}
        ''')
        self.icon.setText(glyph)
        self.icon.setStyleSheet('font-size: 16px; font-weight: 700;')
        self.label.setText(message)
        self.setVisible(bool(message))
