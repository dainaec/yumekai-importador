from PySide6.QtCore import Qt
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import (
    QFrame, QGridLayout, QHBoxLayout, QLabel, QPushButton, QScrollArea,
    QSizePolicy, QVBoxLayout, QWidget,
)

from yumekai_importer.ui.styles.application_icon import assets_directory


class CatalogHome(QScrollArea):
    def __init__(self, destinations, navigate, parent=None):
        super().__init__(parent)
        self.setObjectName("homeScroll")
        self.setWidgetResizable(True)
        self.setFrameShape(QFrame.Shape.NoFrame)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        canvas = QWidget()
        canvas.setObjectName("homeCanvas")
        self.setWidget(canvas)
        outer = QVBoxLayout(canvas)
        outer.setContentsMargins(32, 32, 32, 32)
        outer.setSpacing(0)
        content = QWidget()
        content.setObjectName("homeContent")
        content.setMaximumWidth(1180)
        content.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        outer.addStretch(1)
        outer.addWidget(content, 0, Qt.AlignmentFlag.AlignHCenter)
        outer.addStretch(1)
        layout = QVBoxLayout(content)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(26)

        brand = QHBoxLayout()
        brand.setSpacing(18)
        logo = QPixmap(str(assets_directory() / "yumekai-logo.png"))
        mark = QLabel()
        mark.setObjectName("homeLogo")
        if not logo.isNull():
            mark.setPixmap(logo.scaled(330, 94, Qt.AspectRatioMode.KeepAspectRatio,
                                      Qt.TransformationMode.SmoothTransformation))
            brand.addWidget(mark)
        else:
            mark.setPixmap(QPixmap(str(assets_directory() / "app-icon.png")).scaled(
                78, 78, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation))
            brand.addWidget(mark)
            words = QVBoxLayout()
            words.setSpacing(2)
            words.addWidget(self._label("YUMEKAI", "homeBrand"))
            words.addWidget(self._label("Importador y gestor de catálogo", "homeBrandCaption"))
            brand.addLayout(words)
        brand.addStretch()
        layout.addLayout(brand)

        hero = QFrame()
        hero.setObjectName("homeHero")
        hero_layout = QVBoxLayout(hero)
        hero_layout.setContentsMargins(32, 26, 32, 30)
        hero_layout.setSpacing(12)
        hero_layout.addWidget(self._label("TU ESPACIO DE TRABAJO", "homeEyebrow"))
        hero_layout.addWidget(self._label("Tu catálogo, a punto para la tienda.", "homeHeadline"))
        hero_layout.addWidget(self._label("Importa novedades, revisa las fichas y prepara los productos para WooCommerce.",
                                          "homeIntro"))
        layout.addWidget(hero)

        self._grid = QGridLayout()
        self._grid.setContentsMargins(0, 0, 0, 0)
        self._grid.setSpacing(18)
        self._cards = []
        self.buttons = []
        copy = (
            ("01 / INCORPORAR", "Importar catálogo", "Carga los Excel de tus distribuidores y reúne las novedades en un solo lugar.",
             "Importar Excel", False),
            ("02 / PREPARAR", "Revisar pendientes", "Completa fichas, comprueba los datos y genera el CSV cuando lo necesites.",
             "Abrir revisión", True),
            ("03 / CONSULTAR", "Inventario actual", "El espacio para consultar y gestionar los productos que ya están en la tienda.",
             "Próximamente", False),
        )
        for (_, destination), (step, title, description, action, primary) in zip(destinations, copy):
            card = QFrame()
            card.setObjectName("homePrimaryCard" if primary else "homeCard")
            card.setMinimumHeight(250)
            box = QVBoxLayout(card)
            box.setContentsMargins(24, 24, 24, 22)
            box.setSpacing(13)
            box.addWidget(self._label(step, "homeCardStep"))
            box.addWidget(self._label(title, "homeCardTitle"))
            box.addWidget(self._label(description, "homeCardDescription"))
            box.addStretch()
            button = QPushButton(action)
            button.setObjectName("homePrimaryAction" if primary else "homeAction")
            button.setMinimumHeight(46)
            button.setCursor(Qt.CursorShape.PointingHandCursor)
            button.clicked.connect(lambda _checked=False, target=destination: navigate(target))
            if title == "Inventario actual":
                button.setEnabled(False)
            box.addWidget(button)
            self.buttons.append(button)
            self._cards.append(card)
        layout.addLayout(self._grid)
        layout.addWidget(self._label("De las novedades a la tienda · Importar → Revisar → Exportar", "homeFooter"))
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
        columns = 3 if self.viewport().width() >= 950 else 1
        if columns == self._columns:
            return
        self._columns = columns
        for card in self._cards:
            self._grid.removeWidget(card)
        for column in range(3):
            self._grid.setColumnStretch(column, 1 if column < columns else 0)
        for index, card in enumerate(self._cards):
            self._grid.addWidget(card, index // columns, index % columns)
