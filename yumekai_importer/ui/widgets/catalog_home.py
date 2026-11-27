from PySide6.QtCore import Qt
from PySide6.QtSvgWidgets import QSvgWidget
from PySide6.QtWidgets import (
    QBoxLayout, QFrame, QGridLayout, QHBoxLayout, QLabel, QPushButton,
    QScrollArea, QSizePolicy, QVBoxLayout, QWidget,
)

from yumekai_importer.ui.styles.theme_switcher import set_theme_stylesheet
from yumekai_importer.version import APP_VERSION
from yumekai_importer.ui.styles.application_icon import assets_directory
from yumekai_importer.ui.widgets.presentation import button_role


HOME_STYLE = """
QScrollArea#homeScroll, QWidget#homeCanvas {
    background: qlineargradient(
        x1:0, y1:0, x2:1, y2:1,
        stop:0 #FCF7FC, stop:1 #FFFEF6
    );
    border: 0;
}
QWidget#homeContent, QWidget#homeWords { background: transparent; }
QLabel#homeEyebrow {
    color: #80697E; font-size: 12px; font-weight: 600;
    background: transparent;
}
QLabel#homeHeadline {
    color: #302432; font-size: 28px; font-weight: 600;
    background: transparent;
}
QLabel#homeIntro {
    color: #756B77; font-size: 14px; background: transparent;
}
QFrame#homeCard, QFrame#homePrimaryCard {
    background: #FFFFFF; border: 1px solid #E7DEE7; border-radius: 18px;
}
QFrame#homePrimaryCard {
    background: #FFFCF0; border: 1px solid #E6CA75;
}
QLabel#homeCardStep {
    background: #F2E5F0; color: #76576F;
    border: 0; border-radius: 10px; font-size: 15px; font-weight: 700;
}
QFrame#homePrimaryCard QLabel#homeCardStep {
    background: #FBE7A6; color: #705A24;
}
QLabel#homeCardTitle {
    color: #352837; font-size: 20px; font-weight: 600;
    background: transparent; border: 0;
}
QLabel#homeCardDescription {
    color: #796D7B; font-size: 14px;
    background: transparent; border: 0;
}
QPushButton#homeAction, QPushButton#homePrimaryAction {
    min-height: 26px; padding: 9px 14px;
    font-size: 14px; font-weight: 600; border-radius: 10px;
}
QPushButton#homeAction {
    background: #FFFFFF; color: #544258; border: 1px solid #DCCFDE;
}
QPushButton#homeAction:hover { background: #F7EFF7; border-color: #BBA1BA; }
QPushButton#homePrimaryAction {
    background: #FDE48A; color: #493A1E; border: 1px solid #DCC05F;
}
QPushButton#homePrimaryAction:hover { background: #F7D86F; }
QPushButton#homeAction:focus, QPushButton#homePrimaryAction:focus {
    border: 2px solid #8D6A8B; padding: 8px 13px;
}
QLabel#homeFooter, QLabel#homeVersion {
    color: #978B98; font-size: 12px; background: transparent;
    border: 0; padding: 0;
}
"""


class CatalogHome(QScrollArea):
    def __init__(self, destinations, navigate, parent=None):
        super().__init__(parent)
        self.setObjectName("homeScroll")
        self.setWidgetResizable(True)
        self.setFrameShape(QFrame.Shape.NoFrame)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        set_theme_stylesheet(self, HOME_STYLE)

        canvas = QWidget()
        canvas.setObjectName("homeCanvas")
        self.setWidget(canvas)
        outer = QVBoxLayout(canvas)
        outer.setContentsMargins(32, 28, 32, 28)

        self._content = QWidget()
        self._content.setObjectName("homeContent")
        self._content.setMaximumWidth(1160)
        outer.addStretch(1)
        outer.addWidget(self._content, 0, Qt.AlignmentFlag.AlignHCenter)
        outer.addStretch(1)

        layout = QVBoxLayout(self._content)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(22)

        self._brand = QBoxLayout(QBoxLayout.Direction.LeftToRight)
        self._brand.setContentsMargins(12, 0, 12, 0)
        self._brand.setSpacing(36)

        self._logo = QSvgWidget(str(assets_directory() / "logo-yumekai.svg"))
        self._logo.setObjectName("homeBrandLogo")
        self._logo.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self._logo.setFixedSize(190, 172)
        self._logo.renderer().setAspectRatioMode(Qt.AspectRatioMode.KeepAspectRatio)
        self._brand.addWidget(self._logo, 0, Qt.AlignmentFlag.AlignCenter)

        words = QWidget()
        words.setObjectName("homeWords")
        self._words = QVBoxLayout(words)
        self._words.setContentsMargins(0, 0, 0, 0)
        self._words.setSpacing(8)

        self._eyebrow = self._label("INICIO", "homeEyebrow")
        self._headline = self._label("Gestor de catálogo", "homeHeadline")
        self._intro = self._label(
            "Importación, revisión y gestión de productos.",
            "homeIntro",
        )
        self._heading_labels = (self._eyebrow, self._headline, self._intro)
        self._words.addStretch()
        for label in self._heading_labels:
            self._words.addWidget(label)
        self._words.addStretch()

        self._brand.addWidget(words, 1)
        layout.addLayout(self._brand)

        self._grid = QGridLayout()
        self._grid.setContentsMargins(0, 0, 0, 0)
        self._grid.setSpacing(18)
        self._cards = []
        self.buttons = []

        texts = (
            ("01", "Importar catálogo",
             "Añade los Excel de tus distribuidores para preparar nuevas fichas.",
             "Cargar catálogo  →", False),
            ("02", "Revisar pendientes",
             "Completa los datos y revisa las propuestas antes de subir tus productos.",
             "Revisar fichas  →", True),
            ("03", "Productos en tienda",
             "Consulta y edita los productos de tu tienda desde el programa.",
             "Abrir tienda  →", False),
        )

        for (_, destination), (number, title, description, action, primary) in zip(
            destinations, texts
        ):
            card = QFrame()
            card.setObjectName("homePrimaryCard" if primary else "homeCard")
            card.setMinimumHeight(218)
            card.setSizePolicy(
                QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred
            )
            box = QVBoxLayout(card)
            box.setContentsMargins(23, 22, 23, 22)
            box.setSpacing(10)

            badge = self._label(number, "homeCardStep")
            badge.setFixedSize(42, 32)
            badge.setAlignment(Qt.AlignmentFlag.AlignCenter)
            box.addWidget(badge)
            box.addWidget(self._label(title, "homeCardTitle"))
            box.addWidget(self._label(description, "homeCardDescription"))
            box.addStretch()

            button = button_role(
                QPushButton(action), "primary" if primary else "secondary"
            )
            button.setObjectName("homePrimaryAction" if primary else "homeAction")
            button.clicked.connect(
                lambda _checked=False, target=destination: navigate(target)
            )
            box.addWidget(button)
            self.buttons.append(button)
            self._cards.append(card)

        layout.addLayout(self._grid)

        footer = QHBoxLayout()
        signature = self._label("Yumekai · Gestión de catálogo", "homeFooter")
        signature.setWordWrap(False)
        footer.addWidget(signature)
        footer.addStretch()
        footer.addWidget(self._label(f"v{APP_VERSION}", "homeVersion"))
        layout.addLayout(footer)

        self._columns = None
        self._arrange_cards()

    @staticmethod
    def _label(text, name):
        label = QLabel(text)
        label.setObjectName(name)
        label.setWordWrap(True)
        label.setTextFormat(Qt.TextFormat.PlainText)
        return label

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if hasattr(self, "_cards"):
            self._arrange_cards()

    def _arrange_cards(self):
        width = max(320, min(1160, self.viewport().width() - 64))
        self._content.setFixedWidth(width)
        columns = 3 if width >= 950 else 1
        if columns == self._columns:
            return
        self._columns = columns
        compact = columns == 1
        self._brand.setDirection(
            QBoxLayout.Direction.TopToBottom
            if compact else QBoxLayout.Direction.LeftToRight
        )
        alignment = (
            Qt.AlignmentFlag.AlignCenter
            if compact else Qt.AlignmentFlag.AlignLeft
        )
        for label in self._heading_labels:
            label.setAlignment(alignment)

        for card in self._cards:
            self._grid.removeWidget(card)
        for column in range(3):
            self._grid.setColumnStretch(column, 1 if column < columns else 0)
        for index, card in enumerate(self._cards):
            self._grid.addWidget(card, index // columns, index % columns)



