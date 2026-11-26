from yumekai_importer.ui.widgets.presentation import review_dialog_layout, style_button_box, button_role
from PySide6.QtCore import QModelIndex, QSignalBlocker, Qt, Signal
from PySide6.QtGui import QBrush, QCloseEvent, QColor
from PySide6.QtWidgets import (
    QAbstractItemView, QDialog, QHBoxLayout, QLabel, QLineEdit, QPushButton, QVBoxLayout,
)

from yumekai_importer.catalog.duplicate_titles import duplicate_title_key, find_duplicate_titles
from yumekai_importer.ui.widgets.review_check_delegate import ReviewCheckDelegate
from yumekai_importer.ui.widgets.tables import make_table, set_rows


class DuplicateTitlesDialog(QDialog):
    editRequested = Signal(str)
    deleteRequested = Signal(list)
    saveRequested = Signal()

    def __init__(self, products, columns, display_value, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Títulos duplicados")
        self._products = {}
        self._groups = ()
        self._keys = []
        self._selected = set()
        self._draft_keys = set()
        self._busy = False
        self._has_drafts = False
        self._display_value = display_value
        fields = {column[0]: column for column in columns}
        priority = {"title", "isbn", "publisher", "book_format", "retail_price"}
        self._columns = (("selected", "Marcar", 75), fields["title"], fields["isbn"],
                         ("review_status", "Lista", 155), fields["publisher"], fields["book_format"],
                         fields["retail_price"], ("matches", "Coincidencias", 120),
                         *(column for column in columns if column[0] not in priority),
                         ("draft", "Cambios pendientes", 185))
        screen = self.screen()
        available = screen.availableGeometry() if screen is not None else None
        self.resize(min(1450, available.width() - 40) if available else 1200,
                    min(780, available.height() - 60) if available else 650)

        layout = review_dialog_layout(self)
        description = QLabel("Coincidencias por título completo, aunque el ISBN sea distinto. "
                             "Se comparan Por revisar y Listas para subir, sin los filtros de la pantalla anterior. "
                             "Compara los datos para decidir qué fichas conservar.")
        description.setWordWrap(True)
        layout.addWidget(description)
        self._search = QLineEdit()
        self._search.setPlaceholderText("Buscar un título entre los duplicados…")
        self._search.setClearButtonEnabled(True)
        self._search.setAccessibleName("Buscar entre títulos duplicados")
        self._search.textChanged.connect(self._search_changed)
        layout.addWidget(self._search)
        self._summary = QLabel()
        self._summary.setObjectName("reviewSummary")
        layout.addWidget(self._summary)

        actions = QHBoxLayout()
        self._select_button = QPushButton("Marcar todas")
        self._select_button.setObjectName("clearButton")
        self._select_button.clicked.connect(self._toggle_visible)
        self._edit_button = button_role(QPushButton("Editar fila actual"), "secondary")
        self._edit_button.clicked.connect(self._edit_current)
        self._save_button = button_role(QPushButton("Guardar cambios pendientes"), "primary")
        self._save_button.clicked.connect(self.saveRequested.emit)
        self._delete_button = QPushButton("Borrar selección (0)")
        self._delete_button.setObjectName("deleteReviewButton")
        self._delete_button.clicked.connect(self._delete_selected)
        for button in (self._select_button, self._edit_button, self._save_button):
            actions.addWidget(button)
        actions.addStretch()
        actions.addWidget(self._delete_button)
        layout.addLayout(actions)
        help_text = QLabel("Doble clic en cualquier celda para editar. Marca las casillas para borrar varias fichas. "
                           "El borrado siempre pide confirmación. Las coincidencias se actualizan con los cambios.")
        help_text.setWordWrap(True)
        layout.addWidget(help_text)

        self.table = make_table([caption for _, caption, _ in self._columns], stretch_column=None,
                                column_widths={i: width for i, (_, _, width) in enumerate(self._columns)},
                                freeze_title=True, frozen_columns=2)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.table.setWordWrap(False)
        self.table.setAlternatingRowColors(False)
        self.table.pin_title(2)
        self.table.set_frozen_column_delegate(0, ReviewCheckDelegate)
        self.table.itemChanged.connect(self._selection_changed)
        self.table.currentCellChanged.connect(self._update_actions)
        self.table.doubleClicked.connect(self._edit_index)
        layout.addWidget(self.table, 1)
        self._feedback = QLabel()
        self._feedback.setWordWrap(True)
        self._feedback.setTextFormat(Qt.TextFormat.PlainText)
        self._feedback.hide()
        layout.addWidget(self._feedback)
        self._close_button = button_role(QPushButton("Cerrar"))
        self._close_button.clicked.connect(self.reject)
        footer = QHBoxLayout()
        footer.addStretch()
        footer.addWidget(self._close_button)
        layout.addLayout(footer)
        self.set_products(products)

    def set_products(self, products, draft_keys=()):
        self._products = products
        self._groups = find_duplicate_titles(products)
        self._draft_keys = set(draft_keys)
        self._fill_table()

    def _search_changed(self, *_):
        self._selected.clear()
        self._fill_table()

    def _fill_table(self):
        previous = self._keys[self.table.currentRow()] if 0 <= self.table.currentRow() < len(self._keys) else None
        query = duplicate_title_key(self._search.text())
        groups = [group for group in self._groups if query in group.title_key]
        self._keys = [key for group in groups for key in group.keys]
        self._selected.intersection_update(self._keys)
        rows = []
        backgrounds = []
        for number, group in enumerate(groups):
            for key in group.keys:
                product = self._products[key]
                row = []
                for field, _, _ in self._columns:
                    if field == "selected":
                        text = ""
                    elif field == "review_status":
                        text = {"pending_review": "Por revisar", "ready_to_upload": "Listas para subir"}.get(
                            product.get(field), str(product.get(field) or ""))
                    elif field == "matches":
                        text = str(len(group.keys))
                    elif field == "draft":
                        text = "Cambios sin guardar" if key in self._draft_keys else "—"
                    else:
                        text = self._display_value(product, field)
                    row.append(text)
                rows.append(tuple(row))
                backgrounds.append("#FFF4CE" if key in self._draft_keys else
                                   "#F3EDF4" if number % 2 else "#FFFFFF")
        with QSignalBlocker(self.table):
            set_rows(self.table, rows)
            for row, key in enumerate(self._keys):
                mark = self.table.item(row, 0)
                mark.setData(Qt.ItemDataRole.UserRole, key)
                mark.setFlags(mark.flags() | Qt.ItemFlag.ItemIsUserCheckable)
                mark.setCheckState(Qt.CheckState.Checked if key in self._selected else Qt.CheckState.Unchecked)
                for column in range(self.table.columnCount()):
                    self.table.item(row, column).setBackground(QBrush(QColor(backgrounds[row])))
            if previous in self._keys:
                self.table.setCurrentCell(self._keys.index(previous), 1)
            else:
                self.table.setCurrentCell(-1, -1)
                self.table.clearSelection()
        self.table.fit_title_rows()
        total = sum(len(group.keys) for group in self._groups)
        self._summary.setText(f"{len(groups)} de {len(self._groups)} títulos duplicados · "
                              f"{len(self._keys)} de {total} fichas")
        if not self._groups:
            self._summary.setText("No hay títulos duplicados en Por revisar y Listas para subir.")
        self._update_actions()

    def _selection_changed(self, item):
        if item.column() != 0:
            return
        key = item.data(Qt.ItemDataRole.UserRole)
        if key is None:
            return
        if item.checkState() == Qt.CheckState.Checked:
            self._selected.add(key)
        else:
            self._selected.discard(key)
        self._update_actions()

    def _toggle_visible(self):
        keys = set(self._keys)
        if keys and keys <= self._selected:
            self._selected.difference_update(keys)
        else:
            self._selected.update(keys)
        self._fill_table()

    def _edit_index(self, index: QModelIndex):
        if not self._busy and index.isValid() and 0 <= index.row() < len(self._keys):
            self.editRequested.emit(self._keys[index.row()])

    def _edit_current(self):
        self._edit_index(self.table.currentIndex())

    def _delete_selected(self):
        if not self._busy and self._selected:
            self.deleteRequested.emit(sorted(self._selected))

    def set_busy(self, busy, *, has_drafts=False):
        self._busy = busy
        self._has_drafts = has_drafts
        self._update_actions()

    def set_feedback(self, message):
        self._feedback.setText(message)
        self._feedback.setVisible(bool(message))

    def _update_actions(self, *_):
        self._delete_button.setText(f"Borrar selección ({len(self._selected)})")
        self._delete_button.setEnabled(bool(self._selected) and not self._busy)
        self._select_button.setEnabled(bool(self._keys) and not self._busy)
        self._select_button.setText("Desmarcar todas" if self._keys and set(self._keys) <= self._selected
                                    else "Marcar todas")
        self._edit_button.setEnabled(self.table.currentRow() >= 0 and not self._busy)
        self._save_button.setVisible(self._has_drafts)
        self._save_button.setEnabled(self._has_drafts and not self._busy)
        for widget in (self._search, self.table, self._close_button):
            widget.setEnabled(not self._busy)

    def reject(self):
        if not self._busy:
            super().reject()

    def closeEvent(self, event: QCloseEvent):
        if self._busy:
            event.ignore()
        else:
            super().closeEvent(event)
