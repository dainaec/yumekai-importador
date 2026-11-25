from yumekai_importer.diagnostics import logger
from collections.abc import Callable
from decimal import Decimal
from pathlib import Path

from PySide6.QtCore import Qt, Slot
from PySide6.QtWidgets import (
    QFileDialog,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QSplitter,
    QVBoxLayout,
    QWidget,
)

from yumekai_importer.catalog.product import YumekaiStatus
from yumekai_importer.catalog.exception_rules import import_exception_issues
from yumekai_importer.ui.widgets.exception_approval_dialog import confirm_exceptions

from yumekai_importer.importers.import_result import ImportResult
from yumekai_importer.importers.issues_excel import export_import_issues
from yumekai_importer.importers.norma.excel import read_norma_excel
from yumekai_importer.importers.sd.excel import read_sd_excel

from yumekai_importer.storage.catalog_api import CatalogApi
from yumekai_importer.storage.credentials import load_credentials

from yumekai_importer.ui.workers.save_import_worker import SaveImportWorker
from yumekai_importer.ui.widgets.tables import make_table, set_rows



PRODUCT_COLUMNS = (
    ("Título", 350),
    ("ISBN", 160),
    ("Stock", 144),
    ("Editorial", 190),
    ("PVP", 100),
    ("Rebajado", 112),
    ("Tipo de obra", 140),
    ("Demografía", 140),
    ("Páginas", 92),
    ("Formato", 220),
    ("Autoría", 250),
    ("Colección", 200),
    ("Tomo", 85),
    ("Idioma", 120),
    ("Sinopsis", 390),
    ("Portada (URL)", 330),
)

def _format_price(price: Decimal | None) -> str:
    if price is None:
        return ""
    return f"{price:.2f} €".replace(".", ",")

STOCK_LABELS = {
    YumekaiStatus.ON_DEMAND: "Bajo demanda",
    YumekaiStatus.OUT_OF_STOCK: "Sin existencias",
    YumekaiStatus.IN_STOCK: "Hay existencias",
    YumekaiStatus.ON_BACKORDER: "Se puede reservar",
}

class ImportWindow(QWidget):
    def __init__(self) -> None:
        super().__init__()
        self._result = ImportResult()
        self._source_filename = "catalogo.xlsx"
        self._issues_exported = True
        self._save_worker: SaveImportWorker | None = None
        self.setWindowTitle("Yumekai")
        self.setObjectName("importWindow")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.resize(1100, 700)

        outer_layout = QHBoxLayout(self)
        outer_layout.setContentsMargins(40, 24, 40, 24)

        content = QWidget()
        content.setMaximumWidth(1440)
        outer_layout.addStretch()
        outer_layout.addWidget(content, 1)
        outer_layout.addStretch()

        layout = QVBoxLayout(content)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(12)

        title = QLabel("Importar catálogo")
        title.setObjectName("pageTitle")
        layout.addWidget(title)

        actions = QHBoxLayout()
        actions.setSpacing(8)
        sd_button = QPushButton("Cargar SD")
        norma_button = QPushButton("Cargar Norma")
        clear_button = QPushButton("Limpiar")
        clear_button.setObjectName("clearButton")

        sd_button.clicked.connect(lambda: self._load_excel(read_sd_excel))
        norma_button.clicked.connect(lambda: self._load_excel(read_norma_excel))
        clear_button.clicked.connect(self._clear)

        actions.addWidget(sd_button)
        actions.addWidget(norma_button)
        actions.addStretch()

        self._file_buttons = (sd_button, norma_button, clear_button)
        self.save_button = QPushButton("Guardar carga")
        self.save_button.setEnabled(False)
        self.save_button.clicked.connect(self._save_to_hostalia)

        actions.addWidget(self.save_button)
        actions.addWidget(clear_button)
        layout.addLayout(actions)

        self.summary = QLabel("Carga el Excel y guarda las fichas. La consulta SD se realiza desde Revisar.")
        self.summary.setTextFormat(Qt.TextFormat.PlainText)
        self.summary.setObjectName("importSummary")
        layout.addWidget(self.summary)

        self.products_table = make_table(
            [name for name, _ in PRODUCT_COLUMNS],
            stretch_column=None,
            column_widths={
                index: width for index, (_, width) in enumerate(PRODUCT_COLUMNS)
            },
            freeze_title=True,
        )
        self.products_table.setWordWrap(False)
        self.issues_table = make_table(
            ["Fila Excel", "Título", "Campo", "Incidencia"],
            stretch_column=3,
            column_widths={0: 104, 1: 310, 2: 116},
        )

        issues_box = QGroupBox("Incidencias de importación")
        issues_layout = QVBoxLayout(issues_box)
        issues_actions = QHBoxLayout()
        issues_actions.addStretch()
        self.export_issues_button = QPushButton("Exportar incidencias a Excel")
        self.export_issues_button.setEnabled(False)
        self.export_issues_button.clicked.connect(self._export_issues)
        issues_actions.addWidget(self.export_issues_button)
        issues_layout.addLayout(issues_actions)
        issues_layout.addWidget(self.issues_table)

        splitter = QSplitter(Qt.Orientation.Vertical)
        splitter.addWidget(self.products_table)
        splitter.addWidget(issues_box)
        splitter.setChildrenCollapsible(False)
        splitter.setHandleWidth(24)
        splitter.setSizes([450, 200])
        layout.addWidget(splitter, 1)

    def _load_excel(self, reader: Callable[[str], ImportResult]) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "Selecciona el Excel", str(Path("data").resolve()), "Excel (*.xlsx)"
        )
        if not path:
            return

        try:
            result = reader(path)
        except Exception as error:
            logger.exception("import.failed")
            QMessageBox.warning(self, "No se pudo leer el Excel", str(error))
            return

        if self._confirm_leave_issues():
            self._show_result(result, Path(path).name)

    def _show_result(self, result: ImportResult, filename: str) -> None:
        logger.info("import.loaded source=%s products=%s issues=%s", filename, len(result.products), len(result.issues))
        self._result = result
        self._source_filename = filename
        self._issues_exported = not bool(result.issues)
        self.export_issues_button.setEnabled(bool(result.issues))
        self._show_products()

        set_rows(
            self.issues_table,
            [
                (str(issue.row), issue.title or "Sin título", issue.field, issue.message)
                for issue in result.issues
            ],
        )
        self.summary.setText(
            f"{filename} · {len(result.products)} fichas · {len(result.issues)} incidencias"
        )

        self.save_button.setEnabled(bool(result.products))


    def _export_issues(self) -> bool:
        if not self._result.issues:
            return False
        suggested = Path(self._source_filename).stem + "_incidencias.xlsx"
        path, _ = QFileDialog.getSaveFileName(
            self, "Guardar incidencias para revisar", suggested, "Excel (*.xlsx)"
        )
        if not path:
            return False
        if not path.lower().endswith(".xlsx"):
            path += ".xlsx"
        try:
            count = export_import_issues(self._result, path)
            logger.info("import.issues_exported count=%s file=%s", count, Path(path).name)
        except Exception as error:
            logger.exception("import.failed")
            QMessageBox.warning(self, "No se pudieron exportar las incidencias", str(error))
            return False
        self._issues_exported = True
        QMessageBox.information(
            self, "Incidencias exportadas",
            f"Guardadas {count} filas con incidencias en:\n{path}\n\n"
            "El Excel incluye los datos originales, los datos completados y los motivos. "
            "Puedes corregir la hoja Revisar y cargarla de nuevo con el mismo importador.",
        )
        return True

    def _confirm_leave_issues(self) -> bool:
        if self._issues_exported or not self._result.issues:
            return True
        dialog = QMessageBox(self)
        dialog.setWindowTitle("Incidencias sin exportar")
        dialog.setIcon(QMessageBox.Icon.Warning)
        dialog.setText("Hay filas con incidencias que todavía no has exportado.")
        dialog.setInformativeText(
            "Guárdalas en un Excel para revisarlas después. "
            "Las filas sin código o título no se envían. Los códigos no estándar y el PVP pendiente "
            "se pueden autorizar manualmente al guardar la carga."
        )
        export_button = dialog.addButton("Exportar Excel", QMessageBox.ButtonRole.AcceptRole)
        discard_button = dialog.addButton("Continuar sin exportar", QMessageBox.ButtonRole.DestructiveRole)
        dialog.addButton("Cancelar", QMessageBox.ButtonRole.RejectRole)
        dialog.setDefaultButton(export_button)
        dialog.exec()
        if dialog.clickedButton() is export_button:
            return self._export_issues()
        return dialog.clickedButton() is discard_button

    def _show_products(self) -> None:
        rows = []
        pending = "Por completar"

        for product in self._result.products:
            work_type = product.work_type or ""
            demographic = product.demographic or pending
            if work_type and work_type.casefold() != "manga":
                demographic = "—"

            rows.append((
                product.title,
                product.isbn,
                STOCK_LABELS.get(product.yumekai_status, "Por comprobar"),
                product.publisher or pending,
                _format_price(product.retail_price) or pending,
                _format_price(product.sale_price) or pending,
                work_type or pending,
                demographic,
                str(product.pages) if product.pages is not None else pending,
                product.book_format or pending,
                product.author or pending,
                product.series or pending,
                str(product.volume) if product.volume is not None else pending,
                product.language or pending,
                product.description or pending,
                product.image_url or pending,
            ))

        set_rows(self.products_table, rows)
        self.products_table.fit_title_rows()
        
    def _clear(self) -> None:
        logger.info("import.clear products=%s", len(self._result.products))
        if not self._confirm_leave_issues():
            return
        self._result = ImportResult()
        self._issues_exported = True
        self.export_issues_button.setEnabled(False)
        self.save_button.setEnabled(False)
        self.products_table.setRowCount(0)
        self.issues_table.setRowCount(0)
        self.summary.setText("Carga el Excel y guarda las fichas. La consulta SD se realiza desde Revisar.")

    def _save_to_hostalia(self) -> None:
        if not self._result.products or self._save_worker is not None:
            return

        candidates = {str(index): product for index, product in enumerate(self._result.products)}
        warnings = {key: {"product": vars(product), "issues": issues}
                    for key, product in candidates.items()
                    if (issues := import_exception_issues(vars(product)))}
        approved = confirm_exceptions(warnings, parent=self, purpose="Guardar carga en el importador",
                                      normal_count=len(candidates) - len(warnings))
        if approved is None:
            return
        products = [product for key, product in candidates.items() if key not in warnings or key in approved]
        if not products:
            return
        approved_codes = {candidates[key].isbn for key in approved}

        try:
            credentials = load_credentials()
        except Exception as error:
            logger.exception("import.failed")
            QMessageBox.warning(self, "Acceso a Hostalia", str(error))
            return

        if credentials is None:
            QMessageBox.warning(
                self, "Acceso a Hostalia", "Ejecuta la prueba de conexión para guardar tu acceso."
            )
            return

        api = CatalogApi("https://yumekai.es/importer-api", *credentials)
        self._save_worker = SaveImportWorker(api, products, self, approved_exceptions=approved_codes)
        self._save_worker.skipped_exceptions = len(candidates) - len(products)
        self._save_worker.finished.connect(self._finish_save)
        self._set_saving(True)
        self._save_worker.start()

    def _set_busy(self, busy: bool) -> None:
        for button in self._file_buttons:
            button.setEnabled(not busy)
        self.save_button.setEnabled(not busy and bool(self._result.products))
        self.export_issues_button.setEnabled(not busy and bool(self._result.issues))

    def _set_saving(self, saving: bool) -> None:
        self._set_busy(saving)
        self.save_button.setText("Guardando…" if saving else "Guardar carga")

    @Slot()
    def _finish_save(self) -> None:
        worker = self._save_worker
        if worker is None:
            return

        counts = worker.result
        error = worker.error
        self._save_worker = None
        worker.deleteLater()
        self._set_saving(False)

        if counts is None:
            logger.error("import.save_failed %s", error or "Sin respuesta")
            QMessageBox.warning(
                self, "No se pudo confirmar la carga", error or "No se recibió el resultado."
            )
            return

        issue_note = ""
        logger.info("import.saved created=%s duplicates=%s exceptions_skipped=%s", counts['created'],
                    counts['duplicates'], worker.skipped_exceptions)
        if self._result.issues:
            issue_rows = {issue.row for issue in self._result.issues}
            rejected = len(issue_rows - self._result.products_by_row.keys())
            issue_note = (
                f"\n\nFilas con incidencias: {len(issue_rows)}."
                f"\nDescartadas antes del envío: {rejected}."
                "\nPuedes conservarlas con «Exportar incidencias a Excel»."
            )
        QMessageBox.information(
            self,
            "Resultado del guardado",
            f"Fichas nuevas: {counts['created']}\nISBN repetidos: {counts['duplicates']}"
            f"\nExcepciones sin autorizar, no enviadas: {worker.skipped_exceptions}."
            f"{issue_note}",
        )

    def closeEvent(self, event) -> None:
        if self._save_worker is not None:
            event.ignore()
        else:
            if not self._confirm_leave_issues():
                event.ignore()
                return
            super().closeEvent(event)
