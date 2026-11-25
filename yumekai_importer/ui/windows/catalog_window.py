from pathlib import Path

from PySide6.QtCore import QStandardPaths, Qt
from PySide6.QtGui import QCloseEvent
from PySide6.QtWidgets import (
    QHBoxLayout,
    QPushButton,
    QMenu,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from yumekai_importer.storage.review_draft_backup import ReviewDraftBackup
from yumekai_importer.ui.widgets.catalog_home import CatalogHome
from yumekai_importer.ui.windows.import_window import ImportWindow
from yumekai_importer.ui.windows.pending_review_window import PendingReviewWindow
from yumekai_importer.ui.windows.store_review_window import StoreReviewWindow
from yumekai_importer.ui.widgets.diagnostics_menu import add_diagnostics_actions
from yumekai_importer.diagnostics import logger


class CatalogWindow(QWidget):
    def __init__(self) -> None:
        super().__init__()

        self.setWindowTitle("Yumekai")
        self.setObjectName("catalogWindow")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.resize(1100, 700)

        self._pages = QStackedWidget()

        self._import_page = ImportWindow()

        self._review_page = PendingReviewWindow(
            draft_backup=ReviewDraftBackup()
        )

        backup_path = (
            Path(
                QStandardPaths.writableLocation(
                    QStandardPaths.StandardLocation.AppLocalDataLocation
                )
            )
            / "store-recovery.json"
        )

        self._inventory_page = StoreReviewWindow(
            draft_backup=ReviewDraftBackup(backup_path)
        )

        destinations = (
            ("Importar", self._import_page),
            ("Revisar pendientes", self._review_page),
            ("Productos en tienda", self._inventory_page),
        )

        self._home_page = self._build_home(destinations)

        self._pages.addWidget(self._home_page)
        self._pages.addWidget(self._import_page)
        self._pages.addWidget(self._review_page)
        self._pages.addWidget(self._inventory_page)

        self._navigation = QWidget()
        nav_layout = QHBoxLayout(self._navigation)
        nav_layout.setContentsMargins(40, 16, 40, 0)

        back_button = QPushButton("← Inicio")
        back_button.clicked.connect(
            lambda: self._show_page(self._home_page)
        )

        nav_layout.addWidget(back_button)
        nav_layout.addStretch()
        support = QPushButton("Ayuda y registros")
        support.setObjectName("reviewMenuButton")
        support_menu = QMenu(self)
        add_diagnostics_actions(support_menu, self)
        support.setMenu(support_menu)
        nav_layout.addWidget(support)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addWidget(self._navigation)
        layout.addWidget(self._pages, 1)

        self._show_page(self._home_page)

    def _build_home(
        self,
        destinations: tuple[tuple[str, QWidget], ...],
    ) -> QWidget:
        return CatalogHome(destinations, self._show_page)

    def _show_page(self, page: QWidget) -> None:
        current = self._pages.currentWidget()

        if current is not page:
            if current in (self._review_page, self._inventory_page):
                if not current.can_leave():
                    return

        self._pages.setCurrentWidget(page)
        logger.info("navigation.open page=%s", type(page).__name__)
        back = self._navigation.layout().itemAt(0).widget()
        back.setVisible(page is not self._home_page)
        self._navigation.show()

    def closeEvent(self, event: QCloseEvent) -> None:
        for page in (self._review_page, self._inventory_page):
            if not page.can_leave():
                event.ignore()
                self._pages.setCurrentWidget(page)
                self._navigation.show()
                return

        if not self._import_page.close():
            event.ignore()
            self._pages.setCurrentWidget(self._import_page)
            self._navigation.show()
            return

        super().closeEvent(event)
