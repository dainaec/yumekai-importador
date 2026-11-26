from yumekai_importer.ui.widgets.presentation import button_role, review_dialog_layout
from pathlib import Path

from PySide6.QtCore import QStandardPaths, Qt
from PySide6.QtGui import QCloseEvent
from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
    QDialogButtonBox,
    QHBoxLayout,
    QLabel,
    QMessageBox,
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
from yumekai_importer.storage.local_recovery import (
    RECOVERY_GROUPS,
    delete_local_recoveries,
)


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

        back_button = button_role(QPushButton("← Inicio"), "secondary")
        back_button.clicked.connect(
            lambda: self._show_page(self._home_page)
        )

        nav_layout.addWidget(back_button)
        nav_layout.addStretch()
        support = QPushButton("Ayuda y registros")
        support.setObjectName("reviewMenuButton")
        support_menu = QMenu(self)
        add_diagnostics_actions(support_menu, self)
        support_menu.addSeparator()
        support_menu.addAction(
            "Eliminar recuperaciones locales…"
        ).triggered.connect(self._delete_local_recovery)
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

    def _delete_local_recovery(self):
        if (
            self._review_page._busy
            or self._inventory_page._busy
            or self._import_page._save_worker is not None
        ):
            QMessageBox.information(
                self,
                "Operación en curso",
                "Espera a que termine la operación o detén la consulta "
                "antes de eliminar las recuperaciones.",
            )
            return

        dialog = QDialog(self)
        dialog.setWindowTitle("Eliminar recuperaciones locales")
        layout = review_dialog_layout(dialog)

        explanation = QLabel(
            "Selecciona las recuperaciones que quieres descartar. "
            "También se descartarán sus cambios sin guardar en esta sesión. "
            "Los productos guardados en el servidor conservan sus datos."
        )
        explanation.setWordWrap(True)
        layout.addWidget(explanation)

        checks = {}

        for group, (label, _) in RECOVERY_GROUPS.items():
            checkbox = QCheckBox(label, dialog)
            checkbox.setChecked(True)
            layout.addWidget(checkbox)
            checks[group] = checkbox

        creation_note = QLabel(
            "Si una creación llegó a completarse en la tienda, el producto "
            "seguirá allí. Comprueba la tienda antes de volver a crearlo."
        )
        creation_note.setWordWrap(True)
        layout.addWidget(creation_note)
        checks["creation"].toggled.connect(creation_note.setVisible)

        toggle = button_role(
            QPushButton("Desmarcar todas"),
            "secondary",
        )
        layout.addWidget(toggle)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Cancel
        )
        remove = buttons.addButton(
            "Eliminar seleccionadas",
            QDialogButtonBox.ButtonRole.DestructiveRole,
        )
        button_role(remove, "danger")
        remove.clicked.connect(dialog.accept)
        buttons.rejected.connect(dialog.reject)
        layout.addWidget(buttons)

        def update_selection(*_):
            states = [
                checkbox.isChecked()
                for checkbox in checks.values()
            ]
            remove.setEnabled(any(states))
            toggle.setText(
                "Desmarcar todas" if all(states) else "Marcar todas"
            )

        def toggle_all():
            checked = not all(
                checkbox.isChecked()
                for checkbox in checks.values()
            )
            for checkbox in checks.values():
                checkbox.setChecked(checked)

        for checkbox in checks.values():
            checkbox.toggled.connect(update_selection)

        toggle.clicked.connect(toggle_all)

        if dialog.exec() != QDialog.DialogCode.Accepted:
            return

        if (
            self._review_page._busy
            or self._inventory_page._busy
            or self._import_page._save_worker is not None
        ):
            QMessageBox.information(
                self,
                "Operación en curso",
                "Espera a que termine la operación "
                "antes de eliminar recuperaciones.",
            )
            return

        selected = {
            group
            for group, checkbox in checks.items()
            if checkbox.isChecked()
        }

        if not selected:
            return

        try:
            cleared, deleted, failures = delete_local_recoveries(
                selected
            )
        except (OSError, ValueError) as error:
            QMessageBox.warning(
                self,
                "No se pudo limpiar",
                str(error),
            )
            return

        self._discard_local_recovery_state(cleared)

        logger.info(
            "recovery.deleted groups=%s files=%s failed_groups=%s",
            sorted(cleared),
            deleted,
            sorted(failures),
        )

        if failures:
            details = "\n\n".join(
                f"{RECOVERY_GROUPS[group][0]}:\n{message}"
                for group, message in failures.items()
            )
            QMessageBox.warning(
                self,
                "Limpieza incompleta",
                f"Archivos eliminados: {deleted}.\n"
                "Estas recuperaciones no se pudieron eliminar "
                "por completo:\n\n" + details,
            )
        else:
            QMessageBox.information(
                self,
                "Recuperaciones eliminadas",
                "Se han descartado las recuperaciones seleccionadas.\n"
                f"Archivos eliminados: {deleted}.",
            )

    def _discard_local_recovery_state(self, cleared):
        if "pending" in cleared:
            self._review_page._drafts.clear()
            self._review_page._sd_results.clear()
            self._review_page._selected.clear()
            self._review_page._backup_error = None
            self._review_page._update_filter_options()
            self._review_page._fill_tables()

        if "store" in cleared:
            self._inventory_page._drafts.clear()
            self._inventory_page._sd_results.clear()
            self._inventory_page._selected.clear()

        if "manual" in cleared:
            self._inventory_page._manual_recovery = None

        if cleared & {"store", "manual", "creation"}:
            self._inventory_page._update_filter_options()
            self._inventory_page._fill_table()

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
