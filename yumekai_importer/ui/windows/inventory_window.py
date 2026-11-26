from yumekai_importer.ui.widgets.status_message import StatusMessage
from PySide6.QtCore import QSignalBlocker, Qt, Slot, QTimer
from PySide6.QtGui import QCloseEvent, QShowEvent
from PySide6.QtWidgets import (
    QComboBox, QHBoxLayout, QLabel, QLineEdit, QPushButton, QVBoxLayout, QWidget,
)

from yumekai_importer.catalog.review_fields import review_categories
from yumekai_importer.catalog.review_filters import matches_review_filters
from yumekai_importer.catalog.review_quality import completeness_issues, recommended_issues
from yumekai_importer.catalog.review_workflow import readiness_issues, search_text, stock_code
from yumekai_importer.storage.catalog_api import CatalogApi
from yumekai_importer.storage.credentials import load_credentials
from yumekai_importer.ui.widgets.review_check_delegate import ReviewCheckDelegate
from yumekai_importer.ui.widgets.review_filters_panel import ReviewFiltersPanel
from yumekai_importer.ui.widgets.tables import make_table, set_rows, filter_table_rows
from yumekai_importer.ui.windows.pending_review_window import API_URL, TABLE_COLUMNS, _cell_text
from yumekai_importer.ui.workers.inventory_worker import InventoryWorker
from yumekai_importer.diagnostics import logger


# Ambas pantallas utilizan las mismas columnas, anchuras y formatos de celda.
INVENTORY_COLUMNS = TABLE_COLUMNS


class InventoryWindow(QWidget):
    columns = INVENTORY_COLUMNS

    @staticmethod
    def _key(product):
        return str(product['isbn'])

    def __init__(self) -> None:
        super().__init__()
        self.setObjectName("inventoryWindow")
        self._worker = None
        self._products = []
        self._selected = set()
        self._api_override = None
        
        self._filter_timer = QTimer(self)
        self._filter_timer.setSingleShot(True)
        self._filter_timer.setInterval(200)
        self._filter_timer.timeout.connect(self._apply_filter_rows)

        # Cabecera y acciones.
        title = QLabel("Inventario actual")
        title.setObjectName("pageTitle")
        self._refresh_button = QPushButton("Recargar")
        self._refresh_button.setObjectName("clearButton")
        self._refresh_button.clicked.connect(self._load_inventory)
        self._sync_button = QPushButton("Sincronizar con tienda")
        self._sync_button.setToolTip(
            "Comparar todos los ISBN de la tienda, independientemente de los filtros y de las casillas marcadas"
        )
        self._sync_button.clicked.connect(self._sync_store)
        header = QHBoxLayout()
        header.addWidget(title)
        header.addStretch()
        header.addWidget(self._refresh_button)
        header.addWidget(self._sync_button)

        hint = QLabel("Fichas del importador vinculadas a WooCommerce. El título y las casillas permanecen visibles al desplazarte.")
        hint.setObjectName("reviewHint")
        hint.setWordWrap(True)

        self._search = QLineEdit()
        self._search.setPlaceholderText("Buscar título, ISBN, autoría o colección…")
        self._search.setAccessibleName("Buscar título, ISBN, autoría o colección")
        self._search.setClearButtonEnabled(True)
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
        self._select_visible.setObjectName("clearButton")
        self._select_visible.clicked.connect(self._toggle_visible)
        actions = QHBoxLayout()
        actions.addWidget(self._select_visible)
        actions.addStretch()

        self._feedback_banner = StatusMessage()
        self._feedback = self._feedback_banner.label

        # Mismas casillas, título fijo y columnas que Revisar pendientes.
        self._table = make_table(
            [label for _, label, _ in self.columns],
            stretch_column=None,
            column_widths={i: width for i, (_, _, width) in enumerate(self.columns)},
            freeze_title=True, frozen_columns=2,
        )
        self._table.setWordWrap(False)
        self._table.set_frozen_column_delegate(0, ReviewCheckDelegate)
        self._table.itemChanged.connect(self._selection_changed)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(40, 24, 40, 24)
        layout.setSpacing(12)
        layout.addLayout(header)
        layout.addLayout(filters)
        layout.addWidget(self._advanced_filters)
        layout.addWidget(summary_bar)
        layout.addLayout(actions)
        layout.addWidget(hint)
        layout.addWidget(self._feedback_banner)
        layout.addWidget(self._table, 1)
        self._update_filter_options()
        self._fill_table()

    @property
    def _busy(self):
        return self._worker is not None

    def _api(self):
        if self._api_override is not None:
            return self._api_override
        credentials = load_credentials()
        if not credentials:
            raise ValueError("Guarda tu acceso a Hostalia desde la prueba de conexión del importador.")
        return CatalogApi(API_URL, *credentials)

    def showEvent(self, event: QShowEvent) -> None:
        super().showEvent(event)
        self._load_inventory()

    def _set_feedback(self, message, *, error=False, success=False):
        if message:
            logger.log(40 if error else 20, "inventory.feedback %s", message)
        self._feedback_banner.set_message(message, 'error' if error else 'success' if success else 'info')

    def _current_products(self):
        products = []
        for stored in self._products:
            product = dict(stored)
            product["yumekai_status"] = stock_code(product.get("yumekai_status")) or None
            product["categories"] = review_categories(product.get("work_type"), product.get("demographic"))
            products.append(product)
        return products

    def _visible_products(self, *, include_incomplete=True):
        criteria = self._advanced_filters.criteria()
        query = self._search.text()
        publisher = self._publisher_filter.currentData()
        work_type = self._type_filter.currentData()
        incomplete = include_incomplete and self._incomplete_button.isChecked()

        return [
            product
            for product in self._current_products()
            if matches_review_filters(
                product,
                query,
                publisher,
                work_type,
                criteria=criteria,
                incomplete_only=incomplete,
            )
        ]

    def _update_filter_options(self):
        products = self._current_products()
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
            "_table", "_select_visible", "_sync_button", "_refresh_button",
            "_edit_product", "_unpublish", "_publish", "_new_product",
            "_supplier", "_apply", "_recover", "_open_web",
        ):
            control = getattr(self, name, None)
            if control is not None:
                control.setEnabled(False)

        self._filter_timer.start()

    def _apply_filter_rows(self):
        self._filter_timer.stop()

        visible = {
            self._key(product)
            for product in self._visible_products()
        }
        self._selected.intersection_update(visible)

        filter_table_rows(
            self._table,
            visible,
            self._selected,
        )

        self._update_actions()

    def _reset_filters(self):
        with (
            QSignalBlocker(self._search), QSignalBlocker(self._publisher_filter),
            QSignalBlocker(self._type_filter), QSignalBlocker(self._incomplete_button),
        ):
            self._search.clear()
            self._publisher_filter.setCurrentIndex(0)
            self._type_filter.setCurrentIndex(0)
            self._incomplete_button.setChecked(False)
        self._advanced_filters.clear(emit=False)
        self._more_filters.setChecked(False)
        self._selected.clear()
        self._apply_filter_rows()

    def _fill_table(self):
        self._filter_timer.stop()
        products = self._current_products()
        self._selected.intersection_update(self._key(product) for product in products)
        rows = []
        for product in products:
            note = "; ".join(readiness_issues(product)) or "Sin avisos"
            recommended = recommended_issues(product)
            if recommended:
                note += " · " + "; ".join(recommended) + " (recomendado)"
            rows.append(tuple("" if field == "selected" else note if field == "issues"
                              else _cell_text(product, field) for field, _, _ in self.columns))
        with QSignalBlocker(self._table):
            set_rows(self._table, rows)
            for row, product in enumerate(products):
                isbn = self._key(product)
                item = self._table.item(row, 0)
                item.setData(Qt.ItemDataRole.UserRole, isbn)
                item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
                item.setCheckState(Qt.CheckState.Checked if isbn in self._selected else Qt.CheckState.Unchecked)
        self._table.fit_title_rows()
        self._apply_filter_rows()

    def _selection_changed(self, item):
        if item.column() != 0:
            return
        isbn = item.data(Qt.ItemDataRole.UserRole)
        if isbn is None:
            return
        logger.info("inventory.mark key=%s selected=%s", isbn, item.checkState() == Qt.CheckState.Checked)
        if item.checkState() == Qt.CheckState.Checked:
            self._selected.add(isbn)
        else:
            self._selected.discard(isbn)
        self._update_actions()

    def _toggle_visible(self):
        keys = {self._key(product) for product in self._visible_products()}
        if keys and keys <= self._selected:
            self._selected.difference_update(keys)
        else:
            self._selected.update(keys)
        self._apply_filter_rows()
        logger.info("inventory.mark_visible selected=%s", len(self._selected))

    def _update_actions(self):
        for widget in (self._sync_button, self._refresh_button, self._search, self._publisher_filter,
                       self._type_filter, self._clear_filters, self._more_filters, self._advanced_filters,
                       self._incomplete_button, self._table):
            widget.setEnabled(not self._busy)
        syncing = self._worker is not None and self._worker.sync
        self._sync_button.setText("Sincronizando…" if syncing else "Sincronizar con tienda")
        self._refresh_button.setText("Cargando…" if self._busy and not syncing else "Recargar")
        visible = self._visible_products()
        self._summary.setText(f"{len(visible)} de {len(self._products)} fichas · {len(self._selected)} marcadas")
        visible_keys = {self._key(product) for product in visible}
        self._select_visible.setEnabled(bool(visible) and not self._busy)
        self._select_visible.setText("Desmarcar visibles" if visible_keys and visible_keys <= self._selected
                                    else "Marcar visibles")
        incomplete = sum(bool(completeness_issues(product))
                         for product in self._visible_products(include_incomplete=False))
        self._incomplete_button.setText(f"Con datos pendientes ({incomplete})")
        active = self._advanced_filters.active_count()
        self._more_filters.setText(f"Más filtros ({active})" if active else "Más filtros")

    @Slot()
    def _load_inventory(self):
        self._start_worker(sync=False)

    @Slot()
    def _sync_store(self):
        self._start_worker(sync=True)

    def _start_worker(self, *, sync):
        if self._busy:
            return
        try:
            api = self._api()
        except Exception as error:
            self._set_feedback(str(error), error=True)
            return
        self._worker = InventoryWorker(api, sync=sync, parent=self)
        self._worker.finished.connect(self._finish_worker)
        self._update_actions()
        self._set_feedback("Sincronizando ISBN con la tienda…" if sync else "Cargando inventario…")
        self._worker.start()

    @Slot()
    def _finish_worker(self):
        worker = self._worker
        if worker is None:
            return
        self._worker = None

        # Una recarga fallida conserva el listado anterior.
        if worker.products is not None:
            self._products = worker.products
            self._selected.clear()
            self._update_filter_options()
            self._fill_table()

        if worker.error:
            if worker.sync_result is not None:
                self._set_feedback(
                    f"Sincronización completada: {worker.sync_result['linked']} nuevas fichas vinculadas. "
                    f"No se pudo recargar el inventario: {worker.error} Pulsa Recargar.",
                    error=True,
                )
            else:
                self._set_feedback(str(worker.error), error=True)
        elif worker.sync_result is not None:
            result = worker.sync_result
            message = (
                f"Sincronización completada: {result['linked']} nuevas fichas vinculadas · "
                f"{result['already_linked']} ya vinculadas · "
                f"{result['not_in_importer']} no están en el importador."
            )
            if result['invalid_store_isbns']:
                message += f" {result['invalid_store_isbns']} ISBN inválidos omitidos."
            self._set_feedback(message, success=True)
        else:
            self._set_feedback(f"Inventario actualizado: {len(self._products)} fichas vinculadas.", success=True)

        worker.deleteLater()
        self._update_actions()

    def can_leave(self):
        if self._busy:
            self._set_feedback("Espera a que termine la operación para salir de esta pantalla.")
            return False
        return True

    def closeEvent(self, event: QCloseEvent) -> None:
        if not self.can_leave():
            event.ignore()
            return
        super().closeEvent(event)
