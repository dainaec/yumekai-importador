from PySide6.QtCore import Qt
from PySide6.QtGui import QCloseEvent
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QPushButton,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from yumekai_importer.ui.windows.import_window import ImportWindow
from yumekai_importer.ui.windows.pending_review_window import PendingReviewWindow
from yumekai_importer.ui.widgets.catalog_home import CatalogHome
from yumekai_importer.storage.review_draft_backup import ReviewDraftBackup


class CatalogWindow(QWidget):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("Yumekai")
        self.setObjectName("catalogWindow")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.resize(1100, 700)

        self._pages = QStackedWidget()
        self._import_page = ImportWindow()
        self._review_page = PendingReviewWindow(draft_backup=ReviewDraftBackup())
        destinations = (
            ("Importar", self._import_page),
            ("Revisar pendientes", self._review_page),
            ("Inventario actual", self._section_page("Inventario actual")),
        )

        self._home_page = self._build_home(destinations)
        self._pages.addWidget(self._home_page)
        for _, page in destinations:
            self._pages.addWidget(page)

        self._navigation = QWidget()
        nav_layout = QHBoxLayout(self._navigation)
        nav_layout.setContentsMargins(40, 16, 40, 0)

        back_button = QPushButton("← Inicio")
        back_button.clicked.connect(lambda: self._show_page(self._home_page))
        nav_layout.addWidget(back_button)
        nav_layout.addStretch()

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addWidget(self._navigation)
        layout.addWidget(self._pages, 1)

        self._show_page(self._home_page)

    def _build_home(self, destinations: tuple[tuple[str, QWidget], ...]) -> QWidget:
        return CatalogHome(destinations, self._show_page)

    def _section_page(self, name: str) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(40, 24, 40, 24)

        title = QLabel(name)
        title.setObjectName("pageTitle")
        layout.addWidget(title)
        layout.addWidget(QLabel("Sección en preparación"))
        layout.addStretch()
        return page

    def _show_page(self, page: QWidget) -> None:
        if (self._pages.currentWidget() is self._review_page and page is not self._review_page
                and not self._review_page.can_leave()):
            return
        self._pages.setCurrentWidget(page)
        self._navigation.setVisible(page is not self._home_page)

    def closeEvent(self, event: QCloseEvent) -> None:
        for page in (self._import_page, self._review_page):
            if not page.close():
                event.ignore()
                self._show_page(page)
                return
        super().closeEvent(event)
