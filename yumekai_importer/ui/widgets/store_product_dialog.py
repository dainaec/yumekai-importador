"""Edit actual WooCommerce fields without applying importer defaults to existing products."""
from yumekai_importer.ui.widgets.presentation import review_dialog_layout, style_button_box, button_role
import json
from decimal import Decimal

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QDialog, QDialogButtonBox, QFormLayout, QGridLayout, QLabel, QLineEdit,
    QPlainTextEdit, QScrollArea, QTabWidget, QTreeWidget, QTreeWidgetItem, QVBoxLayout, QWidget,
)

from yumekai_importer.catalog.review_fields import normalize_pages, normalize_price, normalize_volume


class StoreProductDialog(QDialog):
    def __init__(self, product, options, parent=None, *, recovered_changes=None):
        super().__init__(parent)
        self.product = product
        self.creating = product is None
        product = product or {}
        self.setWindowTitle('Nuevo producto en WooCommerce' if self.creating else f"Editar · {product.get('title', '')}")
        self.resize(880, 660)
        self.changes = {}
        self.discard_recovered = False
        self.editors = {}
        self._initial = {}
        layout = review_dialog_layout(self)
        note = QLabel('Se creará como borrador. Revisa sus datos y pulsa Publicar cuando esté preparado.' if self.creating else
                      'Guardar actualiza WooCommerce. Los precios se editan por separado y se conservan los campos que no cambies.')
        if recovered_changes:
            note.setText('Se han recuperado los datos de la creación rechazada. Corrígelos antes de crear el borrador.' if self.creating else
                         'Se han recuperado tus cambios locales sin confirmar. Revísalos antes de guardar. '
                         'Datos recibidos muestra la versión actual de WooCommerce.')
        note.setWordWrap(True)
        layout.addWidget(note)
        tabs = QTabWidget()
        layout.addWidget(tabs, 1)
        fields = QWidget()
        grid = QGridLayout(fields)
        definitions = [
            ('title', 'Título'), ('isbn', 'ISBN / referencia'), ('sku', 'SKU'),
            ('author', 'Autoría'), ('publisher', 'Editorial'), ('series', 'Colección'),
            ('volume', 'Tomo'), ('language', 'Idioma'), ('book_format', 'Formato'), ('pages', 'Páginas'),
            ('retail_price', 'PVP'), ('sale_price', 'Precio rebajado (opcional)'),
            ('yumekai_status', 'Disponibilidad'), ('tax_class', 'Clase de impuesto'), ('is_featured', 'Destacado'),
        ]
        for index, (field, caption) in enumerate(definitions):
            value = product.get(field)
            if field in {'yumekai_status', 'tax_class', 'is_featured'}:
                editor = QComboBox()
                if field == 'yumekai_status':
                    choices = list(options['stock_statuses'].items())
                    value = value if not self.creating else 'outofstock'
                elif field == 'tax_class':
                    choices = [(row['slug'], row['name']) for row in options['tax_classes']]
                    if self.creating:
                        choices.insert(0, (None, 'Selecciona el impuesto'))
                else:
                    choices = [(0, 'No'), (1, 'Sí')]
                    value = int(bool(value))
                for code, label in choices:
                    editor.addItem(label, code)
                found = editor.findData(value)
                if found < 0:
                    editor.addItem(str(value or 'Sin valor'), value)
                    found = editor.count() - 1
                editor.setCurrentIndex(found)
            else:
                editor = QLineEdit('' if value is None else str(value))
                if field in {'retail_price', 'sale_price'}:
                    editor.setText(editor.text().replace('.', ','))
                if field in {'isbn', 'sku'}:
                    editor.setMaxLength(128)
            if not self.creating and field == 'yumekai_status' and product.get('manage_stock'):
                editor.setEnabled(False)
                editor.setToolTip('Esta ficha gestiona unidades. Su disponibilidad se mantiene; revisa las unidades desde WooCommerce.')
            self.editors[field] = editor
            self._initial[field] = self._value(editor)
            cell = QVBoxLayout()
            label = QLabel(caption)
            label.setBuddy(editor)
            cell.addWidget(label)
            cell.addWidget(editor)
            if field == 'isbn' and not self.creating:
                editor.setReadOnly(True)
                self._unlock_isbn = QCheckBox('Permitir cambiar ISBN / referencia')
                self._unlock_isbn.setToolTip('Cambiar el código puede provocar un conflicto con la copia del importador; revisa el vínculo después de guardar.')
                self._unlock_isbn.toggled.connect(lambda enabled, control=editor: control.setReadOnly(not enabled))
                cell.addWidget(self._unlock_isbn)
            grid.addLayout(cell, index // 2, index % 2)
        if self.creating:
            self._sku_suggested = ''
            self.editors['isbn'].textChanged.connect(self._suggest_sku)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(fields)
        tabs.addTab(scroll, 'Ficha y precios')
        category_page = QWidget()
        category_layout = QVBoxLayout(category_page)
        category_layout.addWidget(QLabel('Selecciona las categorías de la tienda. El tipo de obra se obtiene de estas categorías.'))
        self.categories = QTreeWidget()
        self.categories.setHeaderLabels(['Categorías de WooCommerce'])
        self._category_items = {}
        selected = set(product.get('category_ids', []))
        for row in options['categories']:
            item = QTreeWidgetItem([row['name']])
            item.setData(0, Qt.ItemDataRole.UserRole, row['id'])
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            item.setCheckState(0, Qt.CheckState.Checked if row['id'] in selected else Qt.CheckState.Unchecked)
            self._category_items[row['id']] = item
        for row in options['categories']:
            item = self._category_items[row['id']]
            # Guard against a malformed parent cycle in third-party category data.
            parent = self._category_items.get(row['parent'])
            ancestors, parent_id = {row['id']}, row['parent']
            by_id = {r['id']: r for r in options['categories']}
            cycle = False
            while parent_id in by_id:
                if parent_id in ancestors:
                    cycle = True
                    break
                ancestors.add(parent_id)
                parent_id = by_id[parent_id]['parent']
            if parent is not None and not cycle:
                parent.addChild(item)
            else:
                self.categories.addTopLevelItem(item)
        self.categories.expandAll()
        self._initial_categories = sorted(selected)
        self._missing_categories = selected - self._category_items.keys()
        category_layout.addWidget(self.categories)
        tabs.addTab(category_page, 'Categorías')
        texts = QWidget()
        form = QFormLayout(texts)
        for field, caption in [('description', 'Sinopsis / descripción larga'), ('short_description', 'Descripción corta')]:
            editor = QPlainTextEdit(str(product.get(field) or ''))
            editor.setPlaceholderText('Texto o HTML de WooCommerce')
            self.editors[field] = editor
            self._initial[field] = editor.toPlainText()
            form.addRow(caption, editor)
        tabs.addTab(texts, 'Descripciones')
        if not self.creating:
            raw = QPlainTextEdit(json.dumps(product, ensure_ascii=False, indent=2))
            raw.setReadOnly(True)
            tabs.addTab(raw, 'Datos recibidos')
        if recovered_changes:
            for field, value in recovered_changes.items():
                if field == 'category_ids':
                    for identity, item in self._category_items.items():
                        item.setCheckState(0, Qt.CheckState.Checked if identity in value else Qt.CheckState.Unchecked)
                elif field in self.editors:
                    editor = self.editors[field]
                    if isinstance(editor, QComboBox):
                        index = editor.findData(value)
                        if index >= 0:
                            editor.setCurrentIndex(index)
                    elif isinstance(editor, QPlainTextEdit):
                        editor.setPlainText(str(value or ''))
                    else:
                        text = '' if value is None else str(value)
                        editor.setText(text.replace('.', ',') if field in {'retail_price', 'sale_price'} else text)
        self.error = QLabel()
        self.error.setTextFormat(Qt.TextFormat.PlainText)
        self.error.setWordWrap(True)
        self.error.setStyleSheet('color: #991B1B;')
        layout.addWidget(self.error)
        buttons = QDialogButtonBox()
        if recovered_changes:
            discard = buttons.addButton('Descartar copia local', QDialogButtonBox.ButtonRole.ResetRole)
            discard.clicked.connect(self._discard_recovered)
        buttons.addButton('Crear borrador' if self.creating else 'Guardar en WooCommerce', QDialogButtonBox.ButtonRole.AcceptRole)
        cancel = buttons.addButton('Cancelar', QDialogButtonBox.ButtonRole.RejectRole)
        cancel.setObjectName('clearButton')
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        style_button_box(buttons)
        layout.addWidget(buttons)

    def _discard_recovered(self):
        self.discard_recovered = True
        self.reject()

    def _suggest_sku(self, value):
        sku = self.editors['sku']
        if not sku.text() or sku.text() == self._sku_suggested:
            self._sku_suggested = 'YMK-' + value.strip() if value.strip() else ''
            sku.setText(self._sku_suggested)

    @staticmethod
    def _value(editor):
        if isinstance(editor, QComboBox):
            return editor.currentData()
        if isinstance(editor, QPlainTextEdit):
            return editor.toPlainText()
        return editor.text()

    def accept(self):
        changes = {}
        try:
            for field, editor in self.editors.items():
                value = self._value(editor)
                if not self.creating and (value == self._initial[field] or not editor.isEnabled()):
                    continue
                if field in {'retail_price', 'sale_price'}:
                    value = normalize_price(value.strip())
                elif field == 'pages':
                    value = normalize_pages(value.strip())
                    value = str(value) if value is not None else None
                elif field == 'volume':
                    value = normalize_volume(value.strip())
                elif field == 'tax_class' and value is None:
                    raise ValueError('Selecciona la clase de impuesto de este producto.')
                elif isinstance(value, str) and field not in {'description', 'short_description'}:
                    value = value.strip()
                changes[field] = value
            if not str(changes.get('title', (self.product or {}).get('title', ''))).strip():
                raise ValueError('Escribe el título del producto.')
            if self.creating and not changes.get('sku'):
                raise ValueError('Escribe un SKU único. Si introduces el ISBN / referencia se propone YMK-código.')
            regular = changes.get('retail_price', (self.product or {}).get('retail_price'))
            sale = changes.get('sale_price', (self.product or {}).get('sale_price'))
            if sale not in (None, '') and (regular in (None, '') or Decimal(str(sale)) > Decimal(str(regular))):
                raise ValueError('El precio rebajado no puede superar el PVP ni existir sin PVP.')
            category_ids = sorted(key for key, item in self._category_items.items()
                                  if item.checkState(0) == Qt.CheckState.Checked)
            # Preserve any category missing from options unless the user actually changes the selection.
            visible_initial = sorted(set(self._initial_categories) - self._missing_categories)
            if self.creating or category_ids != visible_initial:
                changes['category_ids'] = category_ids
            self.changes = changes
            super().accept()
        except ValueError as error:
            self.error.setText(str(error))
