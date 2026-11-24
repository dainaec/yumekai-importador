from datetime import datetime

from PySide6.QtCore import QModelIndex, QSignalBlocker, Qt, Slot
from PySide6.QtGui import QAction, QBrush, QCloseEvent, QColor, QShowEvent
from PySide6.QtWidgets import (
    QComboBox, QDialog, QDialogButtonBox, QFileDialog,
    QHBoxLayout, QLabel, QLineEdit, QMenu, QMessageBox, QPushButton, QTabWidget,
    QVBoxLayout, QWidget,
)

from yumekai_importer.catalog.review_fields import review_categories, sale_price_preview
from yumekai_importer.catalog.sd_review import sd_review_changes
from yumekai_importer.catalog.classification import canonical_demographic
from yumekai_importer.catalog.duplicate_titles import find_duplicate_titles
from yumekai_importer.catalog.review_filters import matches_review_filters
from yumekai_importer.catalog.review_quality import completeness_issues, export_review, recommended_issues
from yumekai_importer.catalog.review_workflow import (
    STOCK_LABELS, readiness_issues, search_text, stock_code,
)
from yumekai_importer.storage.catalog_api import CatalogApi
from yumekai_importer.storage.credentials import load_credentials
from yumekai_importer.storage.woocommerce_csv import export_products
from yumekai_importer.ui.widgets.product_review_dialog import ProductReviewDialog
from yumekai_importer.ui.widgets.csv_export_dialog import CsvExportDialog
from yumekai_importer.ui.widgets.export_review_dialog import ExportReviewDialog
from yumekai_importer.ui.widgets.review_filters_panel import ReviewFiltersPanel
from yumekai_importer.ui.widgets.duplicate_titles_dialog import DuplicateTitlesDialog
from yumekai_importer.ui.widgets.title_review_dialog import TitleReviewDialog
from yumekai_importer.ui.widgets.review_check_delegate import ReviewCheckDelegate
from yumekai_importer.ui.widgets.tables import make_table, set_rows
from yumekai_importer.ui.workers.load_pending_worker import LoadPendingWorker
from yumekai_importer.ui.workers.review_action_worker import ReviewActionWorker
from yumekai_importer.ui.workers.sd_recheck_worker import SdRecheckWorker

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
        return "Se genera al pasar a lista"
    if field == "categories":
        return ", ".join(map(str, value)) if isinstance(value, (list, tuple)) and value else "Por completar"
    if value is None or value == "":
        return "Por completar"
    if field in {"retail_price", "sale_price"}:
        return str(value).replace(".", ",") + " €"
    return str(value)


class PendingReviewWindow(QWidget):
    def __init__(self) -> None:
        super().__init__()
        self.setObjectName("pendingReviewWindow")
        self._worker = None
        self._action_worker = None
        self._sd_worker = None
        self._sd_results = {}
        self._duplicates_dialog = None
        self._products = {status: {} for status, _ in REVIEW_TABS}
        self._drafts = {}  # Unsaved changes from editing or the latest supplier check.
        self._selected = set()
        self._loaded = False
        self._api_override = None

        title = QLabel("Revisar pendientes")
        title.setObjectName("pageTitle")
        self._tools_button = QPushButton("Herramientas")
        self._tools_button.setObjectName("reviewMenuButton")
        tools_menu = QMenu(self)
        self._tools_button.setMenu(tools_menu)
        self._refresh_button = QAction("Recargar datos", self)
        self._refresh_button.triggered.connect(self._load_pending)
        self._duplicates_button = QAction("Ver duplicados (0)", self)
        self._duplicates_button.setToolTip("Compara títulos repetidos en ambas listas, aunque tengan distinto ISBN.")
        self._duplicates_button.triggered.connect(self._show_duplicates)
        self._title_button = QAction("Revisar colección/tomo de la selección", self)
        self._title_button.triggered.connect(self._review_titles)
        tools_menu.addAction(self._duplicates_button)
        tools_menu.addAction(self._title_button)
        tools_menu.addSeparator()
        tools_menu.addAction(self._refresh_button)
        self._supplier_button = QPushButton("Recomprobar")
        self._supplier_button.setObjectName("reviewMenuButton")
        self._supplier_button.setToolTip("Consultar stock y completar datos por distribuidor")
        supplier_menu = QMenu(self)
        self._supplier_button.setMenu(supplier_menu)
        self._supplier_menus = {}
        for code, label in (("sd", "SD Distribuciones"), ("norma", "Norma Editorial"),
                            ("milky_way", "Milky Way"), ("dirac", "DIRAC / Kibook")):
            menu = supplier_menu.addMenu(label)
            self._supplier_menus[code] = menu
            if code != "sd":
                menu.menuAction().setText(label + " · Próximamente")
                menu.addAction("Próximamente").setEnabled(False)
                menu.menuAction().setEnabled(False)
        self._sd_button = QAction("Recomprobar selección (0)", self)
        self._sd_button.setToolTip("Marca una o más fichas para consultar de nuevo sus datos en SD.")
        self._sd_button.triggered.connect(self._recheck_sd)
        self._sd_report_button = QAction("Ver último resultado SD", self)
        self._sd_report_button.triggered.connect(self._show_sd_report)
        self._supplier_menus["sd"].addAction(self._sd_button)
        self._supplier_menus["sd"].addAction(self._sd_report_button)
        self._stop_sd_button = QPushButton("Detener consulta")
        self._stop_sd_button.setObjectName("clearButton")
        self._stop_sd_button.clicked.connect(self._recheck_sd)
        self._stop_sd_button.hide()
        header = QHBoxLayout()
        header.addWidget(title)
        header.addStretch()
        header.addWidget(self._tools_button)
        header.addWidget(self._supplier_button)
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
        self._incomplete_button.setToolTip("Mostrar fichas con errores o datos recomendados sin completar")
        self._incomplete_button.toggled.connect(self._filters_changed)
        summary_bar = QWidget()
        summary_bar.setObjectName("reviewStatusBar")
        summary_bar.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        summary_layout = QHBoxLayout(summary_bar)
        summary_layout.setContentsMargins(12, 6, 8, 6)
        summary_layout.addWidget(self._summary, 1)
        summary_layout.addWidget(self._incomplete_button)
        self._select_visible = QPushButton("Marcar visibles")
        self._select_visible.clicked.connect(self._toggle_visible)
        self._select_visible.setObjectName("clearButton")
        self._save_button = QPushButton("Guardar cambios pendientes")
        self._save_button.clicked.connect(self._retry_drafts)
        self._selection_tools = QPushButton("Acciones de selección (0)")
        self._selection_tools.setObjectName("reviewMenuButton")
        selection_menu = QMenu(self)
        self._selection_tools.setMenu(selection_menu)
        self._ready_button = QAction("Pasar a listas para subir", self)
        self._ready_button.triggered.connect(self._mark_ready)
        self._return_button = QAction("Devolver a revisión", self)
        self._return_button.triggered.connect(self._return_pending)
        self._export_button = QPushButton("Generar CSV")
        self._export_button.clicked.connect(self._export_csv)
        self._delete_button = QAction("Borrar selección…", self)
        self._delete_button.triggered.connect(self._delete_selected)
        selection_menu.addAction(self._ready_button)
        selection_menu.addAction(self._return_button)
        selection_menu.addSeparator()
        selection_menu.addAction(self._delete_button)
        actions = QHBoxLayout()
        actions.addWidget(self._select_visible)
        actions.addWidget(self._selection_tools)
        actions.addStretch()
        actions.addWidget(self._save_button)
        actions.addWidget(self._export_button)

        self._feedback = QLabel()
        self._feedback.setTextFormat(Qt.TextFormat.PlainText)
        self._feedback.setWordWrap(True)
        self._feedback.hide()
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
        layout.addWidget(self._tabs, 1)
        layout.addWidget(self._feedback)
        self._update_filter_options()
        self._fill_tables()

    @property
    def _status(self):
        return REVIEW_TABS[self._tabs.currentIndex()][0]

    @property
    def _busy(self):
        return self._worker is not None or self._action_worker is not None or self._sd_worker is not None

    def _api(self):
        if self._api_override is not None:
            return self._api_override
        try:
            credentials = load_credentials()
            if not credentials:
                raise ValueError("Ejecuta la prueba de conexión para guardar tu acceso a Hostalia.")
            return CatalogApi(API_URL, *credentials)
        except Exception as error:
            self._set_feedback(str(error))
            return None

    def showEvent(self, event: QShowEvent) -> None:
        super().showEvent(event)
        if not self._drafts:
            self._load_pending()

    def _set_feedback(self, message):
        self._feedback.setText(message)
        self._feedback.setVisible(bool(message))
        if self._duplicates_dialog is not None:
            self._duplicates_dialog.set_feedback(message)

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
        return product

    def _visible_keys(self, status=None, *, include_incomplete=True):
        status = status or self._status
        criteria = self._advanced_filters.criteria()
        incomplete = include_incomplete and self._incomplete_button.isChecked()
        return [isbn for isbn in self._products[status]
                if matches_review_filters(self._current_product(isbn), self._search.text(),
                                          self._publisher_filter.currentData(), self._type_filter.currentData(),
                                          criteria=criteria, incomplete_only=incomplete)]

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
        # Changing a filter clears checks so bulk actions never affect hidden rows.
        self._selected.clear()
        self._fill_tables()

    def _reset_filters(self):
        with QSignalBlocker(self._search), QSignalBlocker(self._publisher_filter), QSignalBlocker(self._type_filter), \
             QSignalBlocker(self._incomplete_button):
            self._search.clear()
            self._publisher_filter.setCurrentIndex(0)
            self._type_filter.setCurrentIndex(0)
            self._incomplete_button.setChecked(False)
        self._advanced_filters.clear(emit=False)
        self._more_filters.setChecked(False)
        self._filters_changed()

    def _tab_changed(self, *_):
        self._selected.clear()
        self._fill_tables()

    def _fill_tables(self):
        self._selected.intersection_update(self._visible_keys())
        for status, label in REVIEW_TABS:
            table = self._tables[status]
            keys = self._visible_keys(status)
            rows = []
            for isbn in keys:
                product = self._current_product(isbn)
                issues = readiness_issues(product)
                note = "; ".join(issues) or "Sin avisos"
                recommended = recommended_issues(product)
                if recommended:
                    note += " · " + "; ".join(recommended) + " (recomendado)"
                if isbn in self._drafts:
                    note = "Cambios sin guardar · " + note
                if isbn in self._sd_results:
                    record = self._sd_results[isbn]
                    note += " · SD: " + ("Datos guardados · " if record.get("saved") else "") + record["note"]
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
        self._update_actions()

    def _selection_changed(self, item):
        if item.column() != 0:
            return
        isbn = item.data(Qt.ItemDataRole.UserRole)
        if isbn is None:
            return
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
        self._fill_tables()

    def _update_actions(self):
        pending = self._status == "pending_review"
        count = len(self._selected)
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
        self._tools_button.setEnabled(not self._busy)
        self._title_button.setEnabled(bool(count) and not self._busy)
        if self._sd_worker is None:
            self._sd_button.setText(f"Recomprobar selección ({count})")
            self._sd_button.setEnabled(bool(count) and not self._busy)
            self._supplier_button.setText(f"Recomprobar ({count})")
        else:
            self._sd_button.setEnabled(not self._sd_worker.stop_requested.is_set())
            self._supplier_button.setText("Deteniendo SD…" if self._sd_worker.stop_requested.is_set() else "Consultando SD…")
        self._supplier_button.setEnabled(not self._busy or self._sd_worker is not None)
        self._stop_sd_button.setVisible(self._sd_worker is not None)
        self._stop_sd_button.setEnabled(self._sd_worker is not None and not self._sd_worker.stop_requested.is_set())
        self._sd_report_button.setVisible(bool(self._sd_results))
        self._sd_report_button.setEnabled(not self._busy)
        self._export_button.setText(f"Generar CSV ({count or len(visible)})")
        for button in (self._ready_button, self._return_button, self._delete_button):
            button.setEnabled(bool(count) and not self._busy)
        self._export_button.setEnabled(bool(visible) and not self._busy and not self._drafts)
        self._save_button.setEnabled(bool(self._drafts) and not self._busy)
        self._refresh_button.setEnabled(not self._busy)
        self._duplicates_button.setEnabled(not self._busy)
        if self._duplicates_dialog is not None:
            self._duplicates_dialog.set_busy(self._busy, has_drafts=bool(self._drafts))
        self._select_visible.setEnabled(bool(visible) and not self._busy)
        self._select_visible.setText("Desmarcar visibles" if visible and set(visible) <= self._selected else "Marcar visibles")
        incomplete = sum(bool(completeness_issues(self._current_product(key)))
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
        self._worker.finished.connect(self._finish_load)
        self._update_actions()
        self._set_feedback("Cargando fichas…")
        self._worker.start()

    def _finish_load(self):
        worker = self._worker
        self._worker = None
        if worker.error is not None:
            self._set_feedback(f"No se pudieron cargar las fichas. {worker.error}")
        else:
            self._products = {status: {str(row["isbn"]): row for row in worker.products_by_status[status]}
                              for status, _ in REVIEW_TABS}
            self._drafts.clear()
            self._sd_results.clear()
            self._selected.clear()
            self._loaded = True
            self._update_filter_options()
            self._fill_tables()
            self._set_feedback("")
        worker.deleteLater()
        self._update_actions()

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
        self._fill_tables()
        self._start_action("save", [self._entry(original)])

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

    def _retry_drafts(self):
        self._start_action("save", [self._entry(key) for key in self._drafts])

    def _review_titles(self):
        if self._busy or not self._selected:
            return
        products = {key: self._current_product(key) for key in self._visible_keys() if key in self._selected}
        titles = [str(product.get("title") or "") for rows in self._products.values() for product in rows.values()]
        dialog = TitleReviewDialog(products, self, known_titles=titles)
        result = dialog.exec()
        proposals = dialog.changes
        dialog.deleteLater()
        if result != QDialog.DialogCode.Accepted:
            return
        for key, changes in proposals.items():
            draft = self._drafts.setdefault(key, {"changes": {},
                "ready_to_upload": products[key].get("review_status") == "ready_to_upload"})
            draft["changes"].update(changes)
        self._fill_tables()
        self._set_feedback(f"Colección/tomo: cambios propuestos en {len(proposals)} ficha(s). "
                           "Pulsa «Guardar cambios pendientes» para guardarlos.")

    def _recheck_sd(self):
        if self._sd_worker is not None:
            self._sd_worker.stop_requested.set()
            self._sd_button.setText("Deteniendo SD…")
            self._sd_button.setEnabled(False)
            self._update_actions()
            return
        if self._busy or not self._selected:
            return
        products = {key: self._current_product(key) for key in sorted(self._selected)}
        self._sd_results.clear()
        self._sd_worker = SdRecheckWorker(products, self)
        self._sd_worker.progress.connect(self._sd_progress)
        self._sd_worker.finished.connect(self._finish_sd_recheck)
        self._sd_button.setText(f"Detener SD (0/{len(products)})")
        self._set_feedback("Buscando por ISBN en SD. Se completarán campos vacíos y se actualizará el formato según SD. "
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
            changes, note = sd_review_changes(product, result)
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
        self._update_filter_options()
        self._fill_tables()
        message = (f"SD: {found} encontradas · {missing} no encontradas · {errors} con error · {cancelled} sin completar.\n"
                   f"Cambios propuestos en {changed} ficha(s). ")
        if changed:
            message += "Revísalos en la tabla y pulsa «Guardar cambios pendientes» para guardarlos. "
        message += "Pulsa «Ver resultado SD» para consultar el motivo de cada ficha."
        if worker.error:
            message += "\n" + worker.error
        self._set_feedback(message)
        worker.deleteLater()
        self._update_actions()

    def _show_sd_report(self):
        if not self._sd_results:
            return
        dialog = QDialog(self)
        dialog.setWindowTitle("Resultado de la última consulta SD")
        screen = self.screen()
        available = screen.availableGeometry() if screen is not None else None
        dialog.resize(min(1180, available.width() - 40) if available else 1100,
                      min(650, available.height() - 60) if available else 600)
        layout = QVBoxLayout(dialog)
        message = QLabel("La consulta completa datos vacíos y propone cambios de formato y disponibilidad según SD. "
                         "Pulsa Guardar cambios pendientes en la pantalla anterior para conservarlos.")
        message.setWordWrap(True)
        layout.addWidget(message)
        table = make_table(["Título", "ISBN", "Resultado", "Detalle", "URL SD"], stretch_column=None,
                           column_widths={0: 290, 1: 160, 2: 155, 3: 600, 4: 370}, freeze_title=True)
        set_rows(table, [(record["title"], record["isbn"], "Guardado" if record.get("saved") else record["result"],
                          record["note"], record["url"]) for record in self._sd_results.values()])
        table.fit_title_rows()
        layout.addWidget(table, 1)
        buttons = QDialogButtonBox()
        buttons.addButton("Cerrar", QDialogButtonBox.ButtonRole.RejectRole)
        buttons.rejected.connect(dialog.reject)
        layout.addWidget(buttons)
        dialog.exec()
        dialog.deleteLater()

    def _mark_ready(self):
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
        api = self._api()
        if api is None:
            return
        self._action_worker = ReviewActionWorker(api, action, entries, self)
        self._action_worker.finished.connect(self._finish_action)
        self._set_feedback("Borrando fichas…" if action == "delete" else "Guardando fichas…")
        self._update_actions()
        self._action_worker.start()

    def _finish_action(self):
        worker = self._action_worker
        self._action_worker = None
        if worker.error is not None:
            self._set_feedback(f"No se pudo confirmar la operación. {worker.error}")
        else:
            result = worker.result
            originals = (result["deleted"] if worker.action == "delete" else
                         [entry["original_isbn"] for entry in result["saved"]])
            for original in originals:
                for rows in self._products.values():
                    rows.pop(original, None)
                self._drafts.pop(original, None)
                self._selected.discard(original)
            if worker.action != "delete":
                for entry in result["saved"]:
                    product = entry["product"]
                    self._products[product["review_status"]][str(product["isbn"])] = product
                    original = entry["original_isbn"]
                    if original in self._sd_results and self._sd_results[original].get("changed"):
                        record = self._sd_results.pop(original)
                        record["saved"] = True
                        self._sd_results[str(product["isbn"])] = record
            for status in self._products:
                self._products[status] = dict(sorted(self._products[status].items(),
                    key=lambda pair: (search_text(pair[1].get("title")), pair[0])))
            self._update_filter_options()
            self._fill_tables()
            verb = {"save": "guardadas", "ready": "listas para subir", "pending": "devueltas a revisión", "delete": "borradas"}[worker.action]
            self._set_feedback(f"{len(originals)} ficha(s) {verb}.")
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
            self._set_feedback(f"No se pudo generar el CSV. {error}")
            return
        self._set_feedback(f"CSV generado: {count} ficha(s). {path}\n"
                           "En WordPress, comprueba el mapeo de «Estado Yumekai» y los campos Meta: _yk_.")

    def can_leave(self):
        if self._busy:
            self._set_feedback("Espera a que termine la operación para salir de esta pantalla.")
            return False
        if not self._confirm_discard():
            return False
        self._drafts.clear()
        self._fill_tables()
        return True

    def closeEvent(self, event: QCloseEvent):
        if not self.can_leave():
            event.ignore()
            return
        self._drafts.clear()
        super().closeEvent(event)
