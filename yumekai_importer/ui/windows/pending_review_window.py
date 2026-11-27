from yumekai_importer.ui.widgets.status_message import StatusMessage
from yumekai_importer.ui.widgets.presentation import button_role, review_dialog_layout, style_button_box
from datetime import datetime

from PySide6.QtCore import QModelIndex, QSignalBlocker, Qt, Slot, QTimer
from PySide6.QtGui import QAction, QBrush, QCloseEvent, QColor, QShowEvent
from PySide6.QtWidgets import (
    QComboBox, QDialog, QDialogButtonBox, QFileDialog,
    QHBoxLayout, QLabel, QLineEdit, QMenu, QMessageBox, QPushButton, QTabWidget,
    QVBoxLayout, QWidget,
)

from yumekai_importer.catalog.review_fields import review_categories, sale_price_preview
from yumekai_importer.catalog.exception_rules import required_issues, ready_exception_issues
from yumekai_importer.ui.widgets.exception_approval_dialog import confirm_exceptions
from yumekai_importer.catalog.sd_review import sd_review_changes
from yumekai_importer.catalog.norma_review import norma_review_changes
from yumekai_importer.catalog.suppliers import supplier_block_reason
from yumekai_importer.catalog.change_selection import confirm_change_selection
from yumekai_importer.diagnostics import logger
from yumekai_importer.catalog.classification import canonical_demographic
from yumekai_importer.catalog.collection_edit import collection_changes, collection_key
from yumekai_importer.catalog.manual_completion import manually_complete, pending_data_issues
from yumekai_importer.catalog.duplicate_titles import find_duplicate_titles
from yumekai_importer.catalog.review_filters import matches_review_filters
from yumekai_importer.catalog.review_quality import export_review, recommended_issues
from yumekai_importer.catalog.review_workflow import (
    STOCK_LABELS, readiness_issues, search_text, stock_code,
)
from yumekai_importer.storage.catalog_api import CatalogApi
from yumekai_importer.storage.review_draft_backup import ReviewDraftBackup
from yumekai_importer.storage.credentials import load_credentials
from yumekai_importer.storage.norma_credentials import load_norma_credentials, forget_norma_credentials
from yumekai_importer.ui.widgets.norma_access_dialog import NormaAccessDialog
from yumekai_importer.storage.woocommerce_csv import export_products
from yumekai_importer.ui.widgets.product_review_dialog import ProductReviewDialog
from yumekai_importer.ui.widgets.collection_edit_dialog import CollectionEditDialog, review_collection_changes
from yumekai_importer.ui.widgets.csv_export_dialog import CsvExportDialog
from yumekai_importer.ui.widgets.export_review_dialog import ExportReviewDialog
from yumekai_importer.ui.widgets.review_filters_panel import ReviewFiltersPanel
from yumekai_importer.ui.widgets.duplicate_titles_dialog import DuplicateTitlesDialog
from yumekai_importer.ui.widgets.title_review_dialog import TitleReviewDialog
from yumekai_importer.ui.widgets.change_review_dialog import review_changes
from yumekai_importer.ui.widgets.review_check_delegate import ReviewCheckDelegate
from yumekai_importer.ui.widgets.tables import make_table, set_rows, filter_table_rows
from yumekai_importer.ui.workers.load_pending_worker import LoadPendingWorker, StoreLinkWorker
from yumekai_importer.ui.workers.review_action_worker import ReviewActionWorker
from yumekai_importer.ui.workers.sd_recheck_worker import SdRecheckWorker
from yumekai_importer.ui.workers.norma_recheck_worker import NormaRecheckWorker
from yumekai_importer.ui.workers.manual_completion_worker import ManualCompletionWorker

API_URL = "https://yumekai.es/importer-api"
PRODUCT_COLUMNS = (
    ("title", "Título", 350), ("isbn", "ISBN", 155), ("author", "Autoría", 210),
    ("publisher", "Editorial", 185), ("series", "Colección", 190), ("volume", "Tomo", 85),
    ("language", "Idioma", 120), ("book_format", "Formato", 215), ("pages", "Páginas", 90),
    ("work_type", "Tipo de obra", 130), ("demographic", "Demografía", 130),
    ("retail_price", "PVP", 100), ("sale_price", "Rebajado", 105),
    ("yumekai_status", "Estado Yumekai", 150), ("sku", "SKU", 145),
    ("is_featured", "Destacado", 110), ("categories", "Categorías", 240),
    ("description", "Sinopsis", 390), ("image_url", "Portada (URL)", 330),
)
TABLE_COLUMNS = (("selected", "Marcar", 75), *PRODUCT_COLUMNS, ("issues", "Revisión", 300))
REVIEW_TABS = (("pending_review", "Por revisar"), ("ready_to_upload", "Listas para subir"))


def _cell_text(product, field):
    value = product.get(field)
    if field == "yumekai_status":
        return STOCK_LABELS.get(stock_code(value), "Por comprobar")
    if field == "is_featured":
        return "Sí" if value in (1, "1", True) else "No"
    if field == "demographic" and str(product.get("work_type") or "").casefold() != "manga":
        return "—"
    if field == "demographic":
        return canonical_demographic(value) or "Por completar"
    if field == "sku" and not value:
        return "Sin SKU" if product.get('review_status') == 'in_store' else "Se genera al pasar a lista"
    if field == "categories":
        return ", ".join(map(str, value)) if isinstance(value, (list, tuple)) and value else "Por completar"
    if value is None or value == "":
        return "Por completar"
    if field in {"retail_price", "sale_price"}:
        return str(value).replace(".", ",") + " €"
    return str(value)


class PendingReviewWindow(QWidget):
    def __init__(self, *, draft_backup=None) -> None:
        super().__init__()
        self.setObjectName("pendingReviewWindow")
        self._worker = None
        self._link_worker = None
        self._action_worker = None
        self._sd_worker = None
        self._norma_worker = None
        self._completion_worker = None
        self._manual_complete_isbns = set()
        self._completion_ready = False
        self._sd_results = {}
        self._duplicates_dialog = None
        self._products = {status: {} for status, _ in REVIEW_TABS}
        self._drafts = {}  # Unsaved changes from editing or the latest supplier check.
        self._draft_backup = draft_backup
        self._backup_error = None
        self._selected = set()
        self._loaded = False
        self._store_check_failed = False
        self._api_override = None
        self._norma_access = None
        self._norma_remember_access = False

        self._filter_timer = QTimer(self)
        self._filter_timer.setSingleShot(True)
        self._filter_timer.setInterval(200)
        self._filter_timer.timeout.connect(self._apply_filter_rows)

        title = QLabel("Revisar pendientes")
        title.setObjectName("pageTitle")
        self._tools_button = button_role(QPushButton("Organizar fichas"), "secondary")
        self._tools_button.setObjectName("reviewMenuButton")
        tools_menu = QMenu(self)
        self._tools_button.setMenu(tools_menu)
        self._recover_drafts_action = QAction("Recuperar última revisión local", self)
        self._recover_drafts_action.triggered.connect(self._restore_draft_backup)
        tools_menu.addAction(self._recover_drafts_action)
        tools_menu.addSeparator()
        self._refresh_button = QPushButton("Actualizar lista", self)
        self._refresh_button.clicked.connect(self._load_pending)
        self._refresh_button.setToolTip("Vuelve a leer las dos listas guardadas en el importador.")
        self._link_store_button = button_role(
            QPushButton("Comprobar productos ya subidos", self),
            "secondary",
        )
        self._link_store_button.setToolTip(
            "Después de importar el CSV en WooCommerce, "
            "comprueba las dos listas completas por ISBN. "
            "Guarda antes los cambios pendientes."
        )
        self._link_store_button.clicked.connect(
            self._link_imported_products
        )
        self._duplicates_button = QAction("Ver duplicados (0)", self)
        self._duplicates_button.setToolTip("Compara títulos repetidos en ambas listas, aunque tengan distinto ISBN.")
        self._duplicates_button.triggered.connect(self._show_duplicates)
        self._title_button = QAction("Revisar colección/tomo de la selección", self)
        self._title_button.triggered.connect(self._review_titles)
        tools_menu.addAction(self._duplicates_button)
        tools_menu.addAction(self._title_button)
        self._collection_edit_action = QAction("Editar colección por lote…", self)
        self._collection_edit_action.setToolTip("Elegir una colección y editar sus campos comunes en la pestaña actual.")
        self._collection_edit_action.triggered.connect(self._edit_collection)
        tools_menu.addAction(self._collection_edit_action)
        tools_menu.addSeparator()

        self._supplier_button = QPushButton("Recomprobar")
        self._supplier_button.setObjectName("reviewMenuButton")
        self._supplier_button.setToolTip("Volver a consultar y comparar los datos por distribuidor")
        supplier_menu = QMenu(self)
        self._supplier_button.setMenu(supplier_menu)
        self._supplier_menus = {}
        for code, label in (("sd", "SD Distribuciones"), ("norma", "Norma Editorial"),
                            ("milky_way", "Milky Way"), ("planeta", "Planeta")):
            menu = supplier_menu.addMenu(label)
            self._supplier_menus[code] = menu
            if code not in {"sd", "norma"}:
                menu.menuAction().setText(label + " · Próximamente")
                menu.addAction("Próximamente").setEnabled(False)
                menu.menuAction().setEnabled(False)
        self._sd_button = QAction("Recomprobar selección (0)", self)
        self._sd_button.setToolTip("Marca una o más fichas para consultar de nuevo sus datos en SD.")
        self._sd_button.triggered.connect(lambda _checked=False: self._recheck_sd())
        self._sd_stock_button = QAction("Solo disponibilidad", self)
        self._sd_stock_button.triggered.connect(lambda _checked=False: self._recheck_sd(stock_only=True))
        self._sd_report_button = QAction("Ver último resultado SD", self)
        self._sd_report_button.triggered.connect(self._show_sd_report)
        self._supplier_menus["sd"].addAction(self._sd_button)
        self._supplier_menus["sd"].addAction(self._sd_stock_button)
        self._supplier_menus["sd"].addAction(self._sd_report_button)
        self._norma_button = QAction("Recomprobar selección (0)", self)
        self._norma_button.triggered.connect(lambda _checked=False: self._recheck_norma())
        self._norma_report_button = QAction("Ver último resultado Norma", self)
        self._norma_stock_button = QAction("Solo disponibilidad", self)
        self._norma_stock_button.triggered.connect(lambda _checked=False: self._recheck_norma(stock_only=True))
        self._norma_report_button.triggered.connect(self._show_norma_report)
        self._supplier_menus["norma"].addAction(self._norma_button)
        self._supplier_menus["norma"].addAction(self._norma_stock_button)
        self._supplier_menus["norma"].addAction(self._norma_report_button)
        self._supplier_menus["norma"].addSeparator()
        self._norma_access_action = QAction("Acceso ZonaLibros…", self)
        self._norma_access_action.triggered.connect(lambda _checked=False: self._configure_norma_access())
        self._norma_forget_action = QAction("Olvidar acceso ZonaLibros", self)
        self._norma_forget_action.triggered.connect(self._forget_norma_access)
        self._supplier_menus["norma"].addAction(self._norma_access_action)
        self._supplier_menus["norma"].addAction(self._norma_forget_action)
        self._stop_sd_button = QPushButton("Detener consulta")
        self._stop_sd_button.setObjectName("clearButton")
        self._stop_sd_button.clicked.connect(self._stop_supplier_check)
        self._stop_sd_button.hide()
        header = QHBoxLayout()
        header.addWidget(title)
        header.addStretch()
        header.addWidget(self._tools_button)
        header.addWidget(self._supplier_button)
        header.addWidget(self._refresh_button)
        header.addWidget(self._stop_sd_button)

        self._search = QLineEdit()
        self._search.setPlaceholderText("Buscar título, ISBN, autoría o colección…")
        self._search.setClearButtonEnabled(True)
        self._search.setAccessibleName("Buscar título, ISBN, autoría o colección")
        self._publisher_filter = QComboBox()
        self._publisher_filter.setAccessibleName("Filtrar por editorial")
        self._type_filter = QComboBox()
        self._type_filter.setAccessibleName("Filtrar por tipo de obra")
        self._clear_filters = QPushButton("Limpiar filtros")
        self._clear_filters.setObjectName("clearButton")
        self._clear_filters.clicked.connect(self._reset_filters)
        self._more_filters = QPushButton("Más filtros")
        self._more_filters.setObjectName("reviewFilterButton")
        self._more_filters.setCheckable(True)
        self._advanced_filters = ReviewFiltersPanel(self)
        self._advanced_filters.hide()
        self._more_filters.toggled.connect(self._advanced_filters.setVisible)
        self._advanced_filters.changed.connect(self._filters_changed)
        self._search.textChanged.connect(self._filters_changed)
        self._publisher_filter.currentIndexChanged.connect(self._filters_changed)
        self._type_filter.currentIndexChanged.connect(self._filters_changed)
        filters = QHBoxLayout()
        filters.addWidget(self._search, 2)
        filters.addWidget(self._publisher_filter, 1)
        filters.addWidget(self._type_filter, 1)
        filters.addWidget(self._more_filters)
        filters.addWidget(self._clear_filters)

        self._summary = QLabel()
        self._summary.setObjectName("reviewSummaryText")
        self._summary.setWordWrap(True)
        self._incomplete_button = QPushButton("Con datos pendientes")
        self._incomplete_button.setObjectName("reviewFilterButton")
        self._incomplete_button.setCheckable(True)
        self._incomplete_button.setToolTip("Mostrar fichas con datos pendientes que no hayas marcado como completas")
        self._incomplete_button.toggled.connect(self._filters_changed)
        summary_bar = QWidget()
        summary_bar.setObjectName("reviewStatusBar")
        summary_bar.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        summary_layout = QHBoxLayout(summary_bar)
        summary_layout.setContentsMargins(12, 6, 8, 6)
        summary_layout.addWidget(self._summary, 1)
        self._completion_button = button_role(QPushButton("Marcar como ficha completa"), "secondary")
        self._completion_button.clicked.connect(self._toggle_manual_completion)
        summary_layout.addWidget(self._completion_button)
        summary_layout.addWidget(self._incomplete_button)
        self._select_visible = QPushButton("Marcar visibles")
        self._select_visible.clicked.connect(self._toggle_visible)
        self._select_visible.setObjectName("clearButton")
        self._save_button = button_role(QPushButton("Guardar cambios pendientes"), "primary")
        self._save_button.clicked.connect(self._retry_drafts)
        self._selection_tools = QPushButton("Acciones de selección (0)")
        self._selection_tools.setObjectName("reviewMenuButton")
        selection_menu = QMenu(self)
        self._selection_tools.setMenu(selection_menu)
        button_role(self._supplier_button, "soft")
        button_role(self._clear_filters, "quiet")
        self._ready_button = QAction("Pasar a listas para subir", self)
        self._ready_button.triggered.connect(self._mark_ready)
        self._return_button = QAction("Devolver a revisión", self)
        self._return_button.triggered.connect(self._return_pending)
        self._export_button = button_role(QPushButton("Generar CSV"), "primary")
        self._export_button.clicked.connect(self._export_csv)
        self._delete_button = QAction("Borrar selección…", self)
        self._delete_button.triggered.connect(self._delete_selected)
        selection_menu.addAction(self._ready_button)
        selection_menu.addAction(self._return_button)
        self._mark_complete_action = QAction("Marcar como ficha completa…", self)
        self._mark_complete_action.triggered.connect(lambda: self._set_manual_completion(True))
        self._unmark_complete_action = QAction("Quitar marca de ficha completa…", self)
        self._unmark_complete_action.triggered.connect(lambda: self._set_manual_completion(False))
        selection_menu.addSeparator()
        selection_menu.addAction(self._mark_complete_action)
        selection_menu.addAction(self._unmark_complete_action)
        selection_menu.addSeparator()
        selection_menu.addAction(self._delete_button)
        actions = QHBoxLayout()
        actions.addWidget(self._select_visible)
        actions.addWidget(self._selection_tools)
        actions.addWidget(self._link_store_button)
        actions.addStretch()
        actions.addWidget(self._save_button)
        actions.addWidget(self._export_button)

        self._feedback_container = StatusMessage()
        self._feedback = self._feedback_container.label
        self._feedback_icon = self._feedback_container.icon
        self._feedback_close = self._feedback_container.close_button

        help_label = QLabel("Doble clic para editar. El título y las casillas permanecen visibles al desplazarte.")
        help_label.setObjectName("reviewHint")
        help_label.setWordWrap(True)
        self._tabs = QTabWidget()
        self._tabs.setObjectName("reviewTabs")
        self._tabs.tabBar().setObjectName("reviewTabBar")
        self._tables = {}
        for status, label in REVIEW_TABS:
            table = make_table(
                [heading for _, heading, _ in TABLE_COLUMNS], stretch_column=None,
                column_widths={i: width for i, (_, _, width) in enumerate(TABLE_COLUMNS)},
                freeze_title=True, frozen_columns=2,
            )
            table.setWordWrap(False)
            table.set_frozen_column_delegate(0, ReviewCheckDelegate)
            table.itemChanged.connect(self._selection_changed)
            table.doubleClicked.connect(self._open_product)
            self._tables[status] = table
            self._tabs.addTab(table, label)
        self._tabs.currentChanged.connect(self._tab_changed)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(40, 24, 40, 24)
        layout.setSpacing(12)
        layout.addLayout(header)
        layout.addLayout(filters)
        layout.addWidget(self._advanced_filters)
        layout.addWidget(summary_bar)
        layout.addLayout(actions)
        layout.addWidget(help_label)
        layout.addWidget(self._feedback_container)
        layout.addWidget(self._tabs, 1)
        self._update_filter_options()
        self._fill_tables()

    @property
    def _status(self):
        return REVIEW_TABS[self._tabs.currentIndex()][0]

    @property
    def _busy(self):
        return any(
            worker is not None
            for worker in (
                self._worker,
                self._link_worker,
                self._action_worker,
                self._sd_worker,
                self._norma_worker,
                self._completion_worker,
            )
        )

    def _api(self):
        if self._api_override is not None:
            return self._api_override
        try:
            credentials = load_credentials()
            if not credentials:
                raise ValueError("Ejecuta la prueba de conexión para guardar tu acceso a Hostalia.")
            return CatalogApi(API_URL, *credentials)
        except Exception as error:
            self._set_feedback(str(error), kind="error")
            return None

    def showEvent(self, event: QShowEvent) -> None:
        super().showEvent(event)
        if not self._drafts:
            self._load_pending()

    def _set_feedback(self, message, kind="info"):
        if message:
            logger.log(40 if kind == "error" else 20, "pending.feedback %s", message)
        self._feedback_container.set_message(message, kind)

        if self._duplicates_dialog is not None:
            self._duplicates_dialog.set_feedback(message)

    def _checkpoint_drafts(self, *, clear_when_empty=False):
        if self._draft_backup is None:
            return
        try:
            if self._drafts:
                products = {key: product for rows in self._products.values() for key, product in rows.items()
                            if key in self._drafts}
                results = {key: result for key, result in self._sd_results.items() if key in self._drafts}
                self._draft_backup.save(products, self._drafts, results)
            elif clear_when_empty:
                self._draft_backup.clear()
            self._backup_error = None
        except (OSError, ValueError) as error:
            self._backup_error = str(error)

    def _restore_draft_backup(self):
        if self._busy or self._drafts or self._draft_backup is None:
            return
        try:
            saved = self._draft_backup.load()
        except (OSError, ValueError) as error:
            self._set_feedback(str(error), kind="error")
            return
        if not self._loaded:
            self._set_feedback('Pulsa Actualizar lista antes de recuperar la revisión, para leer las fichas guardadas.', kind='warning')
            return
        if not saved or not saved["drafts"]:
            self._set_feedback("No hay una revisión local pendiente de recuperar.")
            return
        current_keys = {key for rows in self._products.values() for key in rows}
        skipped = set(saved['drafts']) - current_keys
        if skipped:
            # Keep the edits as a separate recovery file, without bringing shop products back into pending.
            archive = ReviewDraftBackup(self._draft_backup.path.with_name('revisiones-fuera-de-pendientes.json'))
            try:
                archived = archive.load() or {'products': {}, 'drafts': {}, 'sd_results': {}}
                for field in ('products', 'drafts', 'sd_results'):
                    archived[field].update({key: value for key, value in saved[field].items() if key in skipped})
                archive.save(archived['products'], archived['drafts'], archived['sd_results'])
                for field in ('products', 'drafts', 'sd_results'):
                    saved[field] = {key: value for key, value in saved[field].items() if key not in skipped}
                if saved['drafts']:
                    self._draft_backup.save(saved['products'], saved['drafts'], saved['sd_results'])
                else:
                    self._draft_backup.clear()
            except (OSError, ValueError) as error:
                self._set_feedback('No se pudo archivar la revisión que ya no está pendiente: ' + str(error), kind='error')
                return
        # Preserve the original snapshots/revisions: recovery must not overwrite a newer server edit.
        for key in saved["drafts"]:
            for rows in self._products.values():
                rows.pop(key, None)
            product = saved["products"][key]
            self._products[product["review_status"]][key] = product
        self._drafts = saved["drafts"]
        self._sd_results.update(saved["sd_results"])
        self._loaded = True
        self._update_filter_options()
        self._reset_filters()
        self._set_feedback(f"Recuperados {len(self._drafts)} cambios de la copia local. "
                           + (f'{len(skipped)} revisiones ya no corresponden a fichas pendientes y se han conservado aparte. ' if skipped else '')
                           + 'Los datos nuevos que pudiera haber en el servidor se comprobarán al guardar.')

    def _all_current_products(self):
        return {key: self._current_product(key) for rows in self._products.values() for key in rows}

    def _current_product(self, original):
        for products in self._products.values():
            if original in products:
                product = dict(products[original])
                break
        else:
            raise KeyError(original)
        changes = self._drafts.get(original, {}).get("changes", {})
        product.update(changes)
        if "retail_price" in changes:
            product["sale_price"] = sale_price_preview(changes["retail_price"])
        product["yumekai_status"] = stock_code(product.get("yumekai_status")) or None
        product["categories"] = review_categories(product.get("work_type"), product.get("demographic"))
        product["manual_complete"] = original in self._manual_complete_isbns
        return product

    def _visible_keys(self, status=None, *, include_incomplete=True):
        status = status or self._status
        criteria = self._advanced_filters.criteria()
        query = self._search.text()
        publisher = self._publisher_filter.currentData()
        work_type = self._type_filter.currentData()
        incomplete = include_incomplete and self._incomplete_button.isChecked()

        return [
            isbn
            for isbn in self._products[status]
            if matches_review_filters(
                self._current_product(isbn),
                query,
                publisher,
                work_type,
                criteria=criteria,
                incomplete_only=incomplete,
            )
        ]

    def _update_filter_options(self):
        products = [self._current_product(isbn) for rows in self._products.values() for isbn in rows]
        for combo, field, label in ((self._publisher_filter, "publisher", "Todas las editoriales"),
                                    (self._type_filter, "work_type", "Todos los tipos de obra")):
            previous = combo.currentData()
            names = {search_text(row.get(field)): str(row.get(field) or "").strip() for row in products}
            names = {key: value for key, value in names.items() if key}
            with QSignalBlocker(combo):
                combo.clear()
                combo.addItem(label, None)
                combo.addItem("Sin completar", "")
                for value in sorted(names.values(), key=search_text):
                    combo.addItem(value, value)
                combo.setCurrentIndex(max(0, combo.findData(previous)))
        self._advanced_filters.set_products(products)

    def _filters_changed(self, *_):
        self._selected.clear()

        for name in (
            "_tabs", "_selection_tools", "_select_visible",
            "_tools_button", "_supplier_button", "_save_button",
            "_export_button", "_ready_button", "_return_button",
            "_delete_button", "_link_store_button", "_completion_button",
        ):
            control = getattr(self, name, None)
            if control is not None:
                control.setEnabled(False)

        self._filter_timer.start()

    def _apply_filter_rows(self):
        self._filter_timer.stop()

        for status, _ in REVIEW_TABS:
            visible = set(self._visible_keys(status))
            selected = self._selected if status == self._status else set()

            if status == self._status:
                self._selected.intersection_update(visible)

            filter_table_rows(
                self._tables[status],
                visible,
                selected,
            )

        self._update_actions()

    def _reset_filters(self):
        with QSignalBlocker(self._search), QSignalBlocker(self._publisher_filter), QSignalBlocker(self._type_filter), \
             QSignalBlocker(self._incomplete_button):
            self._search.clear()
            self._publisher_filter.setCurrentIndex(0)
            self._type_filter.setCurrentIndex(0)
            self._incomplete_button.setChecked(False)
        self._advanced_filters.clear(emit=False)
        self._more_filters.setChecked(False)
        self._selected.clear()
        self._apply_filter_rows()

    def _tab_changed(self, *_):
        self._selected.clear()
        self._apply_filter_rows()

    def _fill_tables(self):
        self._filter_timer.stop()
        self._selected.intersection_update(self._visible_keys())
        for status, label in REVIEW_TABS:
            table = self._tables[status]
            keys = list(self._products[status])
            rows = []
            for isbn in keys:
                product = self._current_product(isbn)
                if manually_complete(product):
                    note = "Ficha completa · Marcada manualmente"
                else:
                    issues = readiness_issues(product)
                    note = "; ".join(issues) or "Sin avisos"
                    recommended = recommended_issues(product)
                    if recommended:
                        note += " · " + "; ".join(recommended) + " (recomendado)"
                if isbn in self._drafts:
                    note = "Cambios sin guardar · " + note
                    if self._drafts[isbn].get("save_error"):
                        note = "No guardada: " + self._drafts[isbn]["save_error"] + " · " + note
                if isbn in self._sd_results:
                    record = self._sd_results[isbn]
                    label = "Norma" if record.get("supplier") == "norma" else "SD"
                    note += f" · {label}: " + ("Datos guardados · " if record.get("saved") else "") + record["note"]
                rows.append(tuple("" if field == "selected" else note if field == "issues"
                                  else _cell_text(product, field) for field, _, _ in TABLE_COLUMNS))
            with QSignalBlocker(table):
                set_rows(table, rows)
                for row, isbn in enumerate(keys):
                    item = table.item(row, 0)
                    item.setData(Qt.ItemDataRole.UserRole, isbn)
                    item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
                    item.setCheckState(Qt.CheckState.Checked if status == self._status and isbn in self._selected
                                       else Qt.CheckState.Unchecked)
                    if isbn in self._drafts:
                        for col in range(table.columnCount()):
                            table.item(row, col).setBackground(QBrush(QColor("#FFF4CE")))
            table.fit_title_rows()
            self._tabs.setTabText(self._tabs.indexOf(table), f"{label} ({len(self._products[status])})")
        products = self._all_current_products()
        self._duplicates_button.setText(f"Ver duplicados ({len(find_duplicate_titles(products))})")
        if self._duplicates_dialog is not None:
            self._duplicates_dialog.set_products(products, self._drafts)
        self._apply_filter_rows()

    def _selection_changed(self, item):
        if item.column() != 0:
            return
        isbn = item.data(Qt.ItemDataRole.UserRole)
        if isbn is None:
            return
        logger.info("pending.mark isbn=%s selected=%s", isbn, item.checkState() == Qt.CheckState.Checked)
        if item.checkState() == Qt.CheckState.Checked:
            self._selected.add(isbn)
        else:
            self._selected.discard(isbn)
        self._update_actions()

    def _toggle_visible(self):
        keys = set(self._visible_keys())
        if keys and keys <= self._selected:
            self._selected.difference_update(keys)
        else:
            self._selected.update(keys)
        self._apply_filter_rows()
        logger.info("pending.mark_visible selected=%s", len(self._selected))

    def _update_actions(self):
        pending = self._status == "pending_review"
        count = len(self._selected)
        supplier_products = {key: self._current_product(key) for key in self._selected}
        sd_blocked = supplier_block_reason(supplier_products, "sd")
        norma_blocked = supplier_block_reason(supplier_products, "norma")
        visible = self._visible_keys()
        self._summary.setText(f"{len(visible)} de {len(self._products[self._status])} fichas · {count} marcadas"
                              + (f" · {len(self._drafts)} con cambios sin guardar" if self._drafts else ""))
        self._ready_button.setVisible(pending)
        self._return_button.setVisible(not pending)
        self._export_button.setVisible(not pending)
        self._save_button.setVisible(bool(self._drafts))
        self._ready_button.setText(f"Pasar a listas para subir ({count})")
        self._delete_button.setText(f"Borrar selección ({count})")
        self._return_button.setText(f"Devolver a revisión ({count})")
        self._selection_tools.setText(f"Acciones de selección ({count})")
        self._selection_tools.setEnabled(bool(count) and not self._busy)
        complete_count = len(self._selected & self._manual_complete_isbns)
        can_complete = bool(count) and not self._busy and self._completion_ready
        self._completion_button.setText("Quitar marca de ficha completa" if count and complete_count == count
                                        else "Marcar como ficha completa")
        self._completion_button.setEnabled(can_complete)
        self._completion_button.setToolTip(
            "Cambiar la marca manual de las fichas seleccionadas, con confirmación."
            if self._completion_ready else "Actualiza la lista para cargar las marcas compartidas de ficha completa."
        )
        self._mark_complete_action.setEnabled(can_complete and complete_count < count)
        self._unmark_complete_action.setEnabled(can_complete and complete_count > 0)
        self._tools_button.setEnabled(not self._busy)
        self._recover_drafts_action.setVisible(not self._drafts and self._draft_backup is not None and self._draft_backup.exists())
        self._recover_drafts_action.setEnabled(not self._busy and not self._drafts
            and self._draft_backup is not None and self._draft_backup.exists())
        self._title_button.setEnabled(bool(count) and not self._busy)
        self._collection_edit_action.setEnabled(not self._busy and any(
            collection_key(self._current_product(key).get("series")) for key in self._products[self._status]
        ))
        if self._sd_worker is None:
            self._sd_button.setText(f"Recomprobar selección ({count})")
            self._sd_button.setEnabled(bool(count) and not self._busy and not sd_blocked)
            self._supplier_button.setText(f"Recomprobar ({count})")
        else:
            self._sd_button.setEnabled(not self._sd_worker.stop_requested.is_set())
            self._supplier_button.setText("Deteniendo SD…" if self._sd_worker.stop_requested.is_set() else "Consultando SD…")
        self._supplier_button.setEnabled(not self._busy or self._sd_worker is not None)
        self._stop_sd_button.setVisible(self._sd_worker is not None)
        self._stop_sd_button.setEnabled(self._sd_worker is not None and not self._sd_worker.stop_requested.is_set())
        self._sd_report_button.setVisible(bool(self._supplier_records("sd")))
        self._sd_report_button.setEnabled(not self._busy)
        self._sd_stock_button.setEnabled(bool(count) and not self._busy and not sd_blocked)
        self._sd_button.setToolTip(sd_blocked or "Consultar las fichas marcadas en SD Distribuciones.")
        self._sd_stock_button.setToolTip(sd_blocked or "Consultar disponibilidad en SD Distribuciones.")
        self._supplier_menus["sd"].setToolTipsVisible(True)
        self._supplier_button.setToolTip("Consultar las fichas marcadas por distribuidor.")
        self._norma_button.setText(f"Recomprobar selección ({count})")
        self._norma_button.setEnabled(bool(count) and not self._busy and not norma_blocked)
        self._norma_stock_button.setEnabled(bool(count) and not self._busy and not norma_blocked)
        self._norma_stock_button.setToolTip(norma_blocked or "Consultar solo la disponibilidad actual en ZonaLibros, sin MangaUpdates.")
        self._norma_button.setToolTip(norma_blocked or "Consultar estado, páginas, formato y datos de la ficha en Norma ZonaLibros por ISBN.")
        self._supplier_menus["norma"].setToolTipsVisible(True)
        self._norma_report_button.setVisible(bool(self._supplier_records("norma")))
        self._norma_report_button.setEnabled(not self._busy)
        self._norma_access_action.setEnabled(not self._busy)
        self._norma_forget_action.setEnabled(not self._busy)
        if self._norma_worker is not None:
            stopping = self._norma_worker.stop_requested.is_set()
            self._norma_button.setText("Deteniendo Norma…" if stopping else "Detener consulta Norma")
            self._norma_button.setEnabled(not stopping)
            self._supplier_button.setText("Deteniendo Norma…" if stopping else "Consultando Norma…")
            self._supplier_button.setEnabled(True)
            self._stop_sd_button.setVisible(True)
            self._stop_sd_button.setEnabled(not stopping)
        self._export_button.setText(f"Generar CSV ({count or len(visible)})")
        for button in (self._ready_button, self._return_button, self._delete_button):
            button.setEnabled(bool(count) and not self._busy)
        self._export_button.setEnabled(bool(visible) and not self._busy and not self._drafts)
        self._save_button.setEnabled(bool(self._drafts) and not self._busy)
        self._refresh_button.setEnabled(not self._busy)
        self._link_store_button.setEnabled(
            self._loaded and not self._busy and not self._drafts
        )
        self._duplicates_button.setEnabled(not self._busy)
        if self._duplicates_dialog is not None:
            self._duplicates_dialog.set_busy(self._busy, has_drafts=bool(self._drafts))
        self._select_visible.setEnabled(bool(visible) and not self._busy)
        self._select_visible.setText("Desmarcar visibles" if visible and set(visible) <= self._selected else "Marcar visibles")
        incomplete = sum(bool(pending_data_issues(self._current_product(key)))
                         for key in self._visible_keys(include_incomplete=False))
        self._incomplete_button.setText(f"Con datos pendientes ({incomplete})")
        active = self._advanced_filters.active_count()
        self._more_filters.setText(f"Más filtros ({active})" if active else "Más filtros")
        for widget in (self._search, self._publisher_filter, self._type_filter, self._clear_filters, self._tabs,
                       self._more_filters, self._advanced_filters, self._incomplete_button):
            widget.setEnabled(not self._busy)

    def _confirm_discard(self):
        if not self._drafts:
            return True
        return QMessageBox.question(
            self, "Cambios sin guardar", "Hay cambios pendientes de guardar. ¿Quieres descartarlos?",
            QMessageBox.StandardButton.Discard | QMessageBox.StandardButton.Cancel,
            QMessageBox.StandardButton.Cancel,
        ) == QMessageBox.StandardButton.Discard

    @Slot()
    def _load_pending(self):
        if self._busy or not self._confirm_discard():
            return

        api = self._api()
        if api is None:
            return

        self._worker = LoadPendingWorker(api, self)
        self._worker.discard_drafts = bool(self._drafts)
        self._worker.stage.connect(self._set_feedback)
        self._worker.finished.connect(self._finish_load)

        self._set_feedback("Cargando las fichas del importador…")
        self._update_actions()
        self._worker.start()

    def _finish_load(self):
        worker, self._worker = self._worker, None

        if worker.error is not None:
            self._set_feedback(
                "No se pudieron leer las fichas. "
                "Se conserva la lista anterior. "
                + worker.error,
                kind="error",
            )
        else:
            self._products = {
                status: {
                    str(row["isbn"]): row
                    for row in worker.products_by_status[status]
                }
                for status, _ in REVIEW_TABS
            }

            self._drafts.clear()
            self._sd_results.clear()
            self._selected.clear()
            self._store_check_failed = False
            self._loaded = True
            complete_isbns = getattr(worker, "manual_complete_isbns", None)
            self._completion_ready = complete_isbns is not None
            if self._completion_ready:
                self._manual_complete_isbns = set(complete_isbns)

            self._checkpoint_drafts(
                clear_when_empty=getattr(
                    worker, "discard_drafts", False
                )
            )
            self._update_filter_options()
            self._fill_tables()

            total = sum(
                len(rows) for rows in self._products.values()
            )
            self._set_feedback(
                f"{total} ficha(s) cargadas del importador."
                + (" No se pudieron actualizar las marcas de ficha completa: " + worker.completion_error
                   if getattr(worker, "completion_error", None) else ""),
                kind="error" if getattr(worker, "completion_error", None) else "success",
            )

        worker.deleteLater()
        self._update_actions()

    @Slot()
    def _link_imported_products(self):
        if self._busy or not self._loaded:
            return

        if self._drafts:
            self._set_feedback(
                "Guarda los cambios pendientes "
                "antes de comprobar la tienda.",
                kind="warning",
            )
            return

        api = self._api()
        if api is None:
            return

        isbns = [
            isbn
            for rows in self._products.values()
            for isbn in rows
        ]

        self._link_worker = StoreLinkWorker(api, isbns, self)
        self._link_worker.stage.connect(self._set_feedback)
        self._link_worker.finished.connect(
            self._finish_link_imported
        )

        self._set_feedback("Comprobando productos ya subidos…")
        self._update_actions()
        self._link_worker.start()

    def _finish_link_imported(self):
        worker, self._link_worker = self._link_worker, None
        confirmed = {
            row["isbn"] for row in worker.confirmed
        }

        if confirmed:
            for isbn in confirmed:
                for rows in self._products.values():
                    rows.pop(isbn, None)

                self._selected.discard(isbn)
                self._sd_results.pop(isbn, None)

            self._update_filter_options()
            self._fill_tables()

        remaining = sum(
            len(rows) for rows in self._products.values()
        )

        message = (
            f"{len(confirmed)} ficha(s) retiradas de las listas "
            f"con vínculo confirmado. "
            f"{remaining} siguen en preparación."
        )

        if worker.error:
            self._set_feedback(
                message
                + " No se pudo completar la comprobación. "
                + worker.error
                + " Pulsa Actualizar lista antes de reintentar.",
                kind="error",
            )
        elif worker.conflicts:
            self._set_feedback(
                message
                + " Se conservan las coincidencias ambiguas: "
                + ", ".join(worker.conflicts[:6])
                + ("…" if len(worker.conflicts) > 6 else ""),
                kind="warning",
            )
        else:
            self._set_feedback(message, kind="success")

        worker.deleteLater()
        self._update_actions()

    def _apply_pending_snapshot(self, products_by_status, *, discard_drafts=False):
        self._products = {status: {str(row['isbn']): row for row in products_by_status[status]}
                          for status, _ in REVIEW_TABS}
        self._drafts.clear()
        self._sd_results.clear()
        self._selected.clear()
        self._checkpoint_drafts(clear_when_empty=discard_drafts)
        self._loaded = True
        self._update_filter_options()
        self._fill_tables()

    def _show_initial_pending(self, products_by_status):
        if self._worker is None:
            return
        self._store_check_failed = True  # No export before the shop check has completed.
        self._apply_pending_snapshot(products_by_status,
                                     discard_drafts=getattr(self._worker, 'discard_drafts', False))

    def _entry(self, original, *, include_draft=True):
        previous = self._products[self._status].get(original)
        if previous is None:
            previous = next(rows[original] for rows in self._products.values() if original in rows)
        draft = self._drafts.get(original, {}) if include_draft else {}
        return {"original_isbn": original, "expected_updated_at": previous.get("updated_at"),
                "expected_revision": previous.get("_revision"),
                "expected_review_status": previous["review_status"],
                "changes": dict(draft.get("changes", {})),
                "ready_to_upload": draft.get("ready_to_upload", previous["review_status"] == "ready_to_upload")}

    @Slot(QModelIndex)
    def _open_product(self, index):
        if self._busy or not index.isValid():
            return
        original = self._tables[self._status].item(index.row(), 0).data(Qt.ItemDataRole.UserRole)
        self._edit_product(original)

    def _edit_product(self, original, owner=None):
        if self._busy:
            return
        product = self._current_product(original)
        suggestions = {}
        all_products = [self._current_product(key) for rows in self._products.values() for key in rows]
        for field in ("author", "publisher"):
            suggestions[field] = sorted({str(p[field]) for p in all_products if p.get(field)}, key=search_text)
        known = {str(p["isbn"]) for p in all_products if str(p["isbn"]) != str(product["isbn"])}
        ready = self._drafts.get(original, {}).get("ready_to_upload", product.get("review_status") == "ready_to_upload")
        dialog = ProductReviewDialog(product, PRODUCT_COLUMNS, STOCK_LABELS, owner or self,
                                     suggestions=suggestions, reviewed=ready, existing_isbns=known)
        result = dialog.exec()
        changes, ready = dialog.changes, dialog.ready_to_upload
        dialog.deleteLater()
        if result != QDialog.DialogCode.Accepted:
            return
        draft = self._drafts.setdefault(original, {"changes": {}, "ready_to_upload": ready})
        draft["changes"].update(changes)
        draft["ready_to_upload"] = ready
        self._checkpoint_drafts()
        self._fill_tables()
        self._start_action("save", [self._entry(original)])

    def _edit_collection(self):
        if self._busy:
            return
        products = {key: self._current_product(key) for key in self._products[self._status]}
        selected_series = {collection_key(products[key].get("series"))
                           for key in self._selected if key in products}
        initial_series = next(iter(selected_series)) if len(selected_series) == 1 else None
        tab_label = dict(REVIEW_TABS)[self._status]
        dialog = CollectionEditDialog(products, self, tab_label=tab_label, initial_series=initial_series)
        result = dialog.exec()
        proposals = dialog.changes
        dialog.deleteLater()
        if result != QDialog.DialogCode.Accepted or not proposals:
            return
        rows = {key: {"product": products[key], "changes": changes} for key, changes in proposals.items()}
        selected = review_collection_changes(rows, parent=self)
        if selected is None or not selected:
            return
        try:
            for key, changes in selected.items():
                # Validate the final field selection against what will actually be saved.
                collection_changes({key: self._products[self._status][key]}, changes)
        except ValueError as error:
            self._set_feedback("No se han aplicado cambios por lote. " + str(error), kind="error")
            return
        entries = []
        for key, changes in selected.items():
            ready = products[key].get("review_status") == "ready_to_upload"
            draft = self._drafts.setdefault(key, {"changes": {}, "ready_to_upload": ready})
            draft["changes"].update(changes)
            draft.pop("save_error", None)
            entry = self._entry(key)
            entry["changes"] = dict(changes)
            entry["ready_to_upload"] = ready
            entries.append(entry)
        self._checkpoint_drafts()
        self._update_filter_options()
        self._fill_tables()
        self._start_action("save", entries)

    def _show_duplicates(self):
        if self._busy or self._duplicates_dialog is not None:
            return
        dialog = DuplicateTitlesDialog(self._all_current_products(), PRODUCT_COLUMNS, _cell_text, self)
        self._duplicates_dialog = dialog
        dialog.editRequested.connect(lambda original: self._edit_product(original, dialog))
        dialog.deleteRequested.connect(lambda keys: self._delete_products(keys, dialog))
        dialog.saveRequested.connect(self._retry_drafts)
        dialog.set_products(self._all_current_products(), self._drafts)
        self._update_actions()
        try:
            dialog.exec()
        finally:
            self._duplicates_dialog = None
            dialog.deleteLater()

    def _retry_drafts(self, *, keys=None, fields=None):
        if self._busy or not self._drafts:
            return

        scope = set(self._drafts if keys is None else keys)

        rows = {
            key: {
                "product": next(
                    products[key]
                    for products in self._products.values()
                    if key in products
                ),
                "changes": dict(draft.get("changes", {})),
            }
            for key, draft in self._drafts.items()
            if key in scope and draft.get("changes")
        }
        if fields is not None:
            for row in rows.values():
                row["changes"] = {field: value for field, value in row["changes"].items() if field in fields}
            rows = {key: row for key, row in rows.items() if row["changes"]}

        discarded = 0

        if rows:
            selected = review_changes(rows, parent=self)

            # Cancelar conserva todas las propuestas.
            if selected is None:
                return

            discarded = confirm_change_selection(self._drafts, rows, selected, self._selected)
            for key in rows:
                kept = self._drafts.get(key, {}).get("changes", {})
                record = self._sd_results.get(key)
                if record and not record.get("saved"):
                    record["changed"] = bool(kept)

                    if not kept:
                        record["result"] = "Propuestas descartadas"
                        record["note"] = (
                            "Propuestas descartadas. "
                            + record.get("note", "")
                        )

            self._checkpoint_drafts(clear_when_empty=True)
            self._update_filter_options()
            self._fill_tables()

        remaining = scope & self._drafts.keys()
        if fields is not None:
            remaining = {key for key in remaining if fields.intersection(self._drafts[key]["changes"])}
        if not remaining:
            self._set_feedback(
                f"{discarded} cambio(s) descartados. "
                "Se conservan los valores anteriores.",
                kind="info",
            )
            return

        entries = [
            self._entry(key)
            for key in sorted(remaining)
        ]
        if fields is not None:
            for entry in entries:
                entry["changes"] = {field: value for field, value in entry["changes"].items() if field in fields}

        self._start_action("save", entries)

    def _review_titles(self):
        if self._busy or not self._selected:
            return
        products = {key: self._current_product(key) for key in self._visible_keys() if key in self._selected}
        titles = [str(product.get("title") or "") for rows in self._products.values() for product in rows.values()]
        dialog = TitleReviewDialog(products, self, known_titles=titles)
        if dialog.table.rowCount() == 0:
            dialog.deleteLater()
            self._set_feedback(
                "No hay cambios que proponer en las fichas seleccionadas.",
                kind="success",
            )
            return
        result = dialog.exec()
        proposals = dialog.changes
        dialog.deleteLater()
        if result != QDialog.DialogCode.Accepted:
            return
        self._selected.difference_update(products)
        for key, changes in proposals.items():
            draft = self._drafts.setdefault(key, {"changes": {},
                "ready_to_upload": products[key].get("review_status") == "ready_to_upload"})
            draft["changes"].update(changes)
        self._checkpoint_drafts()
        self._fill_tables()
        self._set_feedback(f"Colección/tomo: cambios propuestos en {len(proposals)} ficha(s). "
                           "Revisa los campos que quieres guardar.")
        if proposals:
            entries = []
            for key, changes in proposals.items():
                entry = self._entry(key)
                entry['changes'] = dict(changes)
                entries.append(entry)
            self._start_action('save', entries)

    def _recheck_sd(self, *, stock_only=False):
        if self._sd_worker is not None:
            self._sd_worker.stop_requested.set()
            self._sd_button.setText("Deteniendo SD…")
            self._sd_button.setEnabled(False)
            self._update_actions()
            return
        if self._busy or not self._selected:
            return
        products = {key: self._current_product(key) for key in sorted(self._selected)}
        blocked = supplier_block_reason(products, "sd")
        if blocked:
            self._set_feedback(blocked, kind="error")
            return
        self._sd_results = self._supplier_records("norma")
        self._sd_worker = SdRecheckWorker(products, self, stock_only=stock_only)
        self._sd_worker.progress.connect(self._sd_progress)
        self._sd_worker.finished.connect(self._finish_sd_recheck)
        self._sd_button.setText(f"Detener SD (0/{len(products)})")
        self._set_feedback(("Consultando solo disponibilidad SD. " if stock_only else
                            "Buscando por ISBN en SD. Se compararán también los campos ya rellenados. ") +
                           "Los cambios quedarán para revisar y guardar.")
        self._update_actions()
        self._sd_worker.start()

    @Slot(int, int)
    def _sd_progress(self, completed, total):
        if self._sd_worker is not None and not self._sd_worker.stop_requested.is_set():
            self._sd_button.setText(f"Detener SD ({completed}/{total})")
            self._supplier_button.setText(f"SD · {completed}/{total}")

    @Slot()
    def _finish_sd_recheck(self):
        worker = self._sd_worker
        if worker is None:
            return
        self._sd_worker = None
        changed = found = errors = missing = cancelled = 0
        labels = {"found": "Encontrado", "not_found": "No encontrado", "error": "Error", "cancelled": "Sin consultar / detenida"}
        for key, result in worker.results.items():
            product = worker.products[key]
            changes, note = sd_review_changes(product, result, stock_only=getattr(worker, 'stock_only', False))
            if result.status == "found":
                found += 1
            elif result.status == "not_found":
                missing += 1
            elif result.status == "error":
                errors += 1
            else:
                cancelled += 1
            if changes:
                changed += 1
                previous = self._drafts.setdefault(key, {"changes": {},
                    "ready_to_upload": product.get("review_status") == "ready_to_upload"})
                previous["changes"].update(changes)
            self._sd_results[key] = {"title": str(product.get("title") or ""), "isbn": result.isbn,
                "result": labels.get(result.status, result.status), "note": note, "url": result.url,
                "changed": bool(changes), "saved": False}
        self._checkpoint_drafts()
        self._update_filter_options()
        self._fill_tables()
        message = (
            f"SD: {found} encontradas · "
            f"{missing} no encontradas · "
            f"{errors} con error · "
            f"{cancelled} sin completar.\n"
            f"Cambios propuestos en {changed} ficha(s). "
        )

        if changed:
            message += (
                "Se abrirá «Revisar cambios» "
                "para elegir qué guardar. "
            )
        else:
            message += "No hay cambios nuevos que revisar. "

        message += (
            "En «Recomprobar → SD Distribuciones → "
            "Ver último resultado SD» puedes consultar "
            "el resultado de cada ficha."
        )

        if worker.error:
            message += "\n" + str(worker.error)

        self._set_feedback(
            message,
            kind="error" if errors or worker.error else "info",
        )

        worker.deleteLater()
        self._update_actions()

        if changed:
            keys = [key for key, record in self._supplier_records("sd").items() if record.get("changed")]
            if getattr(worker, "stock_only", False):
                self._retry_drafts(keys=keys, fields={"yumekai_status"})
            else:
                self._retry_drafts(keys=keys)

    def _show_sd_report(self):
        if not self._supplier_records("sd"):
            return
        dialog = QDialog(self)
        dialog.setWindowTitle("Resultado de la última consulta SD")
        screen = self.screen()
        available = screen.availableGeometry() if screen is not None else None
        dialog.resize(min(1180, available.width() - 40) if available else 1100,
                      min(650, available.height() - 60) if available else 600)
        layout = review_dialog_layout(dialog)
        message = QLabel("La consulta compara los datos actuales de SD y propone las diferencias, también en campos ya rellenados. "
                         "Pulsa Guardar cambios pendientes en la pantalla anterior para conservarlos.")
        message.setWordWrap(True)
        layout.addWidget(message)
        table = make_table(["Título", "ISBN", "Resultado", "Detalle", "URL SD"], stretch_column=None,
                           column_widths={0: 290, 1: 160, 2: 155, 3: 600, 4: 370}, freeze_title=True)
        set_rows(table, [(record["title"], record["isbn"], "Guardado" if record.get("saved") else record["result"],
                          record["note"], record["url"]) for record in self._supplier_records("sd").values()])
        table.fit_title_rows()
        layout.addWidget(table, 1)
        buttons = QDialogButtonBox()
        buttons.addButton("Cerrar", QDialogButtonBox.ButtonRole.RejectRole)
        buttons.rejected.connect(dialog.reject)
        style_button_box(buttons)
        layout.addWidget(buttons)
        dialog.exec()
        dialog.deleteLater()

    def _supplier_records(self, supplier):
        return {key: record for key, record in self._sd_results.items()
                if record.get("supplier", "sd") == supplier}

    def _stop_supplier_check(self):
        worker = self._norma_worker or self._sd_worker
        if worker is not None:
            worker.stop_requested.set()
            self._update_actions()

    def _recheck_norma(self, *, stock_only=False):
        if self._norma_worker is not None:
            self._norma_worker.stop_requested.set()
            self._update_actions()
            return
        if self._busy or not self._selected:
            return
        products = {key: self._current_product(key) for key in sorted(self._selected)}
        blocked = supplier_block_reason(products, "norma")
        if blocked:
            self._set_feedback(blocked, kind="error")
            return
        if self._norma_access is None:
            try:
                self._norma_access = load_norma_credentials()
                self._norma_remember_access = self._norma_access is not None
            except Exception:
                self._norma_access = None
        if self._norma_access is None and not self._configure_norma_access():
            return
        self._sd_results = self._supplier_records("sd")
        self._norma_worker = NormaRecheckWorker(products, self, credentials=self._norma_access,
                                               remember_access=self._norma_remember_access, stock_only=stock_only)
        self._norma_worker.progress.connect(self._norma_progress)
        self._norma_worker.finished.connect(self._finish_norma_recheck)
        self._set_feedback(("Consultando solo disponibilidad en Norma ZonaLibros. " if stock_only else
                           "Recomprobando los datos actuales de Norma, incluidos los campos ya rellenados. ") +
                           "Al terminar podrás elegir qué guardar.")
        self._update_actions()
        self._norma_worker.start()

    def _configure_norma_access(self):
        if self._busy:
            return False
        if self._norma_access is None:
            try:
                self._norma_access = load_norma_credentials()
                self._norma_remember_access = self._norma_access is not None
            except Exception:
                pass
        dialog = NormaAccessDialog(self._norma_access, self, remember=self._norma_remember_access)
        accepted = dialog.exec() == QDialog.DialogCode.Accepted
        if accepted:
            if self._norma_remember_access and not dialog.remember:
                try:
                    forget_norma_credentials()
                except Exception:
                    self._set_feedback("No se pudo eliminar el acceso recordado. Revisa el almacén de credenciales del equipo.", kind="error")
                    dialog.deleteLater()
                    return False
            self._norma_access = dialog.credentials
            self._norma_remember_access = dialog.remember
        dialog.deleteLater()
        return accepted

    def _forget_norma_access(self):
        if self._busy:
            return
        self._norma_access = None
        self._norma_remember_access = False
        try:
            forget_norma_credentials()
        except Exception:
            self._set_feedback("Acceso olvidado en esta sesión. No se pudo eliminar del almacén de credenciales del equipo.", kind="error")
            return
        self._set_feedback("Acceso a Norma ZonaLibros olvidado. Se volverá a pedir al consultar.")

    @Slot(int, int)
    def _norma_progress(self, completed, total):
        if self._norma_worker is not None and not self._norma_worker.stop_requested.is_set():
            self._supplier_button.setText(f"Norma · {completed}/{total}")

    @Slot()
    def _finish_norma_recheck(self):
        worker = self._norma_worker
        if worker is None:
            return
        self._norma_worker = None
        changed = found = errors = missing = cancelled = 0
        labels = {"found": "Encontrado", "not_found": "No encontrado", "error": "Error", "cancelled": "Sin consultar / detenida"}
        for key, result in worker.results.items():
            product = worker.products[key]
            changes, note = norma_review_changes(product, result, stock_only=getattr(worker, "stock_only", False))
            if result.status == "found":
                found += 1
            elif result.status == "not_found":
                missing += 1
            elif result.status == "error":
                errors += 1
            else:
                cancelled += 1
            if changes:
                changed += 1
                previous = self._drafts.setdefault(key, {"changes": {},
                    "ready_to_upload": product.get("review_status") == "ready_to_upload"})
                previous["changes"].update(changes)
            self._sd_results[key] = {"title": str(product.get("title") or ""), "isbn": result.isbn,
                "result": labels.get(result.status, result.status), "note": note, "url": result.url,
                "changed": bool(changes), "saved": False, "supplier": "norma"}
        self._checkpoint_drafts()
        self._update_filter_options()
        self._fill_tables()
        message = (
            f"Norma: {found} encontradas · "
            f"{missing} no encontradas · "
            f"{errors} con error · "
            f"{cancelled} sin completar.\n"
            f"Cambios propuestos en {changed} ficha(s). "
        )

        if changed:
            message += (
                "Se abrirá «Revisar cambios» "
                "para elegir qué guardar. "
            )
        else:
            message += "No hay cambios nuevos que revisar. "

        message += (
            "En «Recomprobar → Norma Editorial → "
            "Ver último resultado Norma» puedes consultar "
            "el resultado de cada ficha."
        )

        if worker.error:
            message += "\n" + str(worker.error)

        self._set_feedback(
            message,
            kind="error" if errors or worker.error else "info",
        )

        worker.deleteLater()
        self._update_actions()

        if changed:
            keys = [key for key, record in self._supplier_records("norma").items() if record.get("changed")]
            if getattr(worker, "stock_only", False):
                self._retry_drafts(keys=keys, fields={"yumekai_status"})
            else:
                self._retry_drafts(keys=keys)

    def _show_norma_report(self):
        if not self._supplier_records("norma"):
            return
        dialog = QDialog(self)
        dialog.setWindowTitle("Resultado de la última consulta Norma")
        screen = self.screen()
        available = screen.availableGeometry() if screen is not None else None
        dialog.resize(min(1180, available.width() - 40) if available else 1100,
                      min(650, available.height() - 60) if available else 600)
        layout = review_dialog_layout(dialog)
        message = QLabel("Norma ZonaLibros confirma el ISBN y compara los datos actuales, también si ya estaban rellenados. "
                         "El tipo se propone solo con evidencia específica. "
                         "Pulsa Guardar cambios pendientes en la pantalla anterior para conservarlos.")
        message.setWordWrap(True)
        layout.addWidget(message)
        table = make_table(["Título", "ISBN", "Resultado", "Detalle", "URL Norma"], stretch_column=None,
                           column_widths={0: 290, 1: 160, 2: 155, 3: 600, 4: 370}, freeze_title=True)
        set_rows(table, [(record["title"], record["isbn"], "Guardado" if record.get("saved") else record["result"],
                          record["note"], record["url"]) for record in self._supplier_records("norma").values()])
        table.fit_title_rows()
        layout.addWidget(table, 1)
        buttons = QDialogButtonBox()
        buttons.addButton("Cerrar", QDialogButtonBox.ButtonRole.RejectRole)
        buttons.rejected.connect(dialog.reject)
        style_button_box(buttons)
        layout.addWidget(buttons)
        dialog.exec()
        dialog.deleteLater()

    def _toggle_manual_completion(self):
        self._set_manual_completion(not bool(self._selected) or not self._selected <= self._manual_complete_isbns)

    def _set_manual_completion(self, complete):
        if self._busy or not self._completion_ready:
            return
        keys = sorted(key for key in self._selected if key in self._products[self._status]
                      and (key in self._manual_complete_isbns) != complete)
        if not keys:
            return
        title = "Marcar como ficha completa" if complete else "Quitar marca de ficha completa"
        message = (
            f"¿Quieres marcar {len(keys)} ficha(s) como completas?\n\n"
            "Dejarán de aparecer en «Con datos pendientes», aunque falten datos o haya avisos. "
            "Podrás quitar la marca desde el listado general o el filtro «Completadas manualmente»."
            if complete else
            f"¿Quieres quitar la marca de ficha completa a {len(keys)} ficha(s)?\n\n"
            "Volverán a aparecer en «Con datos pendientes» si tienen datos pendientes o avisos."
        )
        if QMessageBox.question(self, title, message,
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No) != QMessageBox.StandardButton.Yes:
            return
        api = self._api()
        if api is None:
            return
        self._completion_worker = ManualCompletionWorker(api, keys, complete, self)
        self._completion_worker.finished.connect(self._finish_manual_completion)
        self._set_feedback("Guardando marca de ficha completa…")
        self._update_actions()
        self._completion_worker.start()

    def _finish_manual_completion(self):
        worker, self._completion_worker = self._completion_worker, None
        if worker.error is not None:
            self._completion_ready = False
            self._set_feedback("No se pudo confirmar el cambio de marca. " + worker.error
                               + " Actualiza la lista para comprobar el resultado.", kind="error")
        else:
            if worker.complete:
                self._manual_complete_isbns.update(worker.isbns)
            else:
                self._manual_complete_isbns.difference_update(worker.isbns)
            self._selected.difference_update(worker.isbns)
            self._fill_tables()
            self._set_feedback(f"{len(worker.isbns)} ficha(s) "
                               + ("marcadas como completas." if worker.complete else "con la marca de completa quitada."),
                               kind="success")
        worker.deleteLater()
        self._update_actions()

    def _mark_ready(self):
        if self._selected & self._drafts.keys():
            self._retry_drafts(keys=self._selected)
            return
        if not self._selected:
            return
        self._start_action("ready", [self._entry(key) for key in sorted(self._selected)])

    def _return_pending(self):
        self._start_action("pending", [self._entry(key) for key in sorted(self._selected)])

    def _delete_selected(self):
        self._delete_products(sorted(self._selected))

    def _delete_products(self, keys, owner=None):
        if self._busy or not keys:
            return
        keys = sorted(set(keys))
        names = [str(self._current_product(key).get("title")) for key in keys]
        box = QMessageBox(owner or self)
        box.setWindowTitle("Confirmar borrado")
        box.setIcon(QMessageBox.Icon.Warning)
        box.setText(f"¿Borrar {len(keys)} ficha(s) del importador?")
        box.setInformativeText("\n".join(names[:5]) + (f"\nY {len(keys)-5} más." if len(keys) > 5 else "")
                               + "\nEsta acción es definitiva y no borra productos de WordPress.")
        box.setDetailedText("\n".join(f"{key} · {name}" for key, name in zip(keys, names)))
        delete = box.addButton("Borrar fichas", QMessageBox.ButtonRole.DestructiveRole)
        cancel = box.addButton("Cancelar", QMessageBox.ButtonRole.RejectRole)
        box.setDefaultButton(cancel)
        box.exec()
        confirmed = box.clickedButton() is delete
        box.deleteLater()
        if confirmed:
            self._start_action("delete", [self._entry(key, include_draft=False) for key in keys])

    def _start_action(self, action, entries):
        if self._busy or not entries:
            return
        entries, failed = self._preflight_entries(action, entries)
        if entries is None:  # Cancelled: keep every selection and draft.
            return
        if not entries:
            self._set_feedback("No se ha enviado ninguna ficha.\n" + "\n".join(
                f"{row['original_isbn']}: {row['message']}" for row in failed[:8]), kind="error")
            return
        api = self._api()
        if api is None:
            return
        self._checkpoint_drafts()
        self._action_worker = ReviewActionWorker(api, action, entries, self)
        self._action_worker.preflight_failed = failed
        self._action_worker.finished.connect(self._finish_action)
        self._set_feedback("Borrando fichas…" if action == "delete" else "Guardando fichas…")
        self._update_actions()
        self._action_worker.start()

    def _preflight_entries(self, action, entries):
        warnings, valid, failed = {}, [], []
        for original_entry in entries:
            entry = dict(original_entry)
            entry.pop("exceptions_confirmed", None)  # Permission belongs to this attempt only.
            key = entry["original_isbn"]
            ready = action == "ready" or (action == "save" and entry.get("ready_to_upload"))
            if ready:
                stored = next(rows[key] for rows in self._products.values() if key in rows)
                product = {**stored, **entry.get("changes", {})}
                mandatory = required_issues(product)
                if mandatory:
                    failed.append({"original_isbn": key, "message": " · ".join(mandatory)})
                    continue
                issues = ready_exception_issues(product)
                if issues:
                    warnings[key] = {"product": product, "issues": issues}
            valid.append(entry)
        approved = confirm_exceptions(warnings, parent=self, purpose="Pasar a Listas para subir",
                                      normal_count=len(valid) - len(warnings))
        if approved is None:
            return None, []
        sending = []
        for entry in valid:
            key = entry["original_isbn"]
            if key in warnings:
                if key not in approved:
                    failed.append({"original_isbn": key, "message": "Excepción sin autorizar; sigue pendiente."})
                    continue
                entry["exceptions_confirmed"] = True
            sending.append(entry)
        return sending, failed

    def _finish_action(self):
        worker = self._action_worker
        self._action_worker = None
        had_drafts = bool(self._drafts)
        result = worker.result or {}
        originals = (result.get("deleted", []) if worker.action == "delete" else
                     [entry["original_isbn"] for entry in result.get("saved", [])])
        requests = {entry['original_isbn']: entry for entry in worker.products}
        remaining = {}
        if worker.action == 'save':
            for original in originals:
                draft = self._drafts.get(original)
                if draft:
                    rest = {field: value for field, value in draft['changes'].items()
                            if field not in requests[original].get('changes', {})}
                    if rest:
                        remaining[original] = {**draft, 'changes': rest}
        for original in originals:
            for rows in self._products.values():
                rows.pop(original, None)
            self._drafts.pop(original, None)
            self._selected.discard(original)
            if worker.action == "delete":
                self._manual_complete_isbns.discard(original)
        if worker.action != "delete":
            for entry in result.get("saved", []):
                product = entry["product"]
                self._products[product["review_status"]][str(product["isbn"])] = product
                original = entry["original_isbn"]
                if original in self._manual_complete_isbns:
                    self._manual_complete_isbns.discard(original)
                    self._manual_complete_isbns.add(str(product["isbn"]))
                if original in remaining:
                    self._drafts[str(product['isbn'])] = remaining[original]
                if original in self._sd_results and self._sd_results[original].get("changed"):
                    record = self._sd_results.pop(original)
                    record["saved"] = True
                    self._sd_results[str(product["isbn"])] = record
        failed = [*result.get("failed", []), *getattr(worker, "preflight_failed", [])]
        for failure in failed:
            key = failure["original_isbn"]
            if key in self._drafts:
                self._drafts[key]["save_error"] = failure["message"]
        for status in self._products:
            self._products[status] = dict(sorted(self._products[status].items(),
                key=lambda pair: (search_text(pair[1].get("title")), pair[0])))
        self._checkpoint_drafts(clear_when_empty=had_drafts and bool(originals))
        self._update_filter_options()
        self._fill_tables()
        verb = {"save": "guardadas", "ready": "listas para subir", "pending": "devueltas a revisión", "delete": "borradas"}[worker.action]
        if worker.error is not None:
            message = (f"{len(originals)} ficha(s) guardadas antes de interrumpirse la conexión. "
                       if originals else "No se pudo confirmar la operación. ")
            self._set_feedback(message + str(worker.error) +
                               " Los cambios no confirmados siguen pendientes.", kind="error")
        elif failed:
            details = "\n".join(f"{row['original_isbn']}: {row['message']}" for row in failed[:8])
            extra = f"\nY {len(failed)-8} más; consulta la columna Revisión." if len(failed) > 8 else ""
            self._set_feedback(f"{len(originals)} ficha(s) {verb}. {len(failed)} pendientes con problemas; "
                               "sus cambios se conservan.\n" + details + extra, kind="error")
        else:
            self._set_feedback(f"{len(originals)} ficha(s) {verb}.", kind="success")
        worker.deleteLater()
        self._update_actions()

    def _export_csv(self):
        if self._busy or self._drafts or self._status != "ready_to_upload":
            return
        keys = [key for key in self._visible_keys() if not self._selected or key in self._selected]
        if not keys:
            return
        products = {key: self._current_product(key) for key in keys}
        review = export_review(products)
        if review:
            check = ExportReviewDialog(review, len(products), self)
            result = check.exec()
            return_to_review = check.return_to_review
            check.deleteLater()
            if return_to_review:
                self._start_action("pending", [self._entry(key) for key in review])
                return
            if result != QDialog.DialogCode.Accepted:
                return
        dialog = CsvExportDialog(len(keys), bool(self._selected), self)
        if self._store_check_failed:
            notice = StatusMessage(dialog)
            notice.set_message('No se ha podido comprobar qué fichas ya existen en WooCommerce. '
                               'Puedes generar el CSV, pero revisa las coincidencias antes de importarlo en la tienda.', 'warning')
            dialog.layout().insertWidget(1, notice)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            dialog.deleteLater()
            return
        published, tax = dialog.publication.currentData(), dialog.tax_class.text().strip()
        reference = dialog.wordpress_reference
        dialog.deleteLater()
        path, _ = QFileDialog.getSaveFileName(self, "Guardar CSV para WooCommerce",
            f"yumekai-{datetime.now():%Y%m%d-%H%M}.csv", "CSV (*.csv)")
        if not path:
            return
        if not path.lower().endswith(".csv"):
            path += ".csv"
        try:
            count = export_products(path, [self._current_product(key) for key in keys],
                                    published=published, tax_class=tax, wordpress_reference=reference,
                                    allow_incomplete=True)
        except (OSError, ValueError) as error:
            self._set_feedback(f"No se pudo generar el CSV. {error}", kind="error")
            return
        self._set_feedback(f"CSV generado: {count} ficha(s). {path}\n"
                           "En WordPress, comprueba el mapeo de «Estado Yumekai» y los campos Meta: _yk_.", kind="success")

    def can_leave(self):
        if self._busy:
            self._set_feedback(
                "Espera a que termine la operación "
                "para salir de esta pantalla."
            )
            return False

        if not self._confirm_discard():
            return False

        had_drafts = bool(self._drafts)
        self._drafts.clear()
        self._selected.clear()
        self._checkpoint_drafts(clear_when_empty=had_drafts)
        self._fill_tables()

        return True

    def closeEvent(self, event: QCloseEvent):
        if not self.can_leave():
            event.ignore()
            return
        self._drafts.clear()
        super().closeEvent(event)
