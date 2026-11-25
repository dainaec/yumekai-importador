"""Review live WooCommerce data and explicitly apply supplier suggestions."""
from datetime import datetime
from PySide6.QtCore import Qt, QSignalBlocker
from PySide6.QtGui import QAction, QBrush, QColor
from PySide6.QtWidgets import QLabel, QMenu, QMessageBox, QPushButton, QWidget

from yumekai_importer.catalog.sd_review import sd_review_changes
from yumekai_importer.catalog.store_review import store_changes
from yumekai_importer.catalog.review_fields import sale_price_preview
from yumekai_importer.catalog.suppliers import supplier_block_reason
from yumekai_importer.catalog.change_selection import confirm_change_selection
from yumekai_importer.diagnostics import logger
from yumekai_importer.ui.widgets.diagnostics_menu import add_diagnostics_actions
from yumekai_importer.ui.windows.inventory_window import InventoryWindow
from yumekai_importer.ui.widgets.change_review_dialog import review_changes
from yumekai_importer.ui.workers.sd_recheck_worker import SdRecheckWorker
from yumekai_importer.ui.workers.store_workers import StoreLoadWorker, StoreSaveWorker


class StoreReviewWindow(InventoryWindow):
    @staticmethod
    def _key(product):
        return str(product['woocommerce_id'])

    def __init__(self, *, draft_backup=None):
        self._store_ready = False
        self._sd_worker = self._action_worker = None
        self._drafts, self._sd_results = {}, {}
        self._draft_backup = draft_backup
        self._must_reload = False
        self._loaded = False
        self._last_sync_result = None
        self._loaded_at = None
        super().__init__()
        header = self.layout().itemAt(0).layout()
        header.itemAt(0).widget().setText('Productos en tienda')
        self._sync_button.hide()
        self._refresh_button.hide()
        self._tools = QPushButton('Herramientas')
        self._tools.setObjectName('reviewMenuButton')
        tools = QMenu(self)
        self._tools.setMenu(tools)
        refresh = tools.addAction('Recargar desde WooCommerce')
        refresh.triggered.connect(self._load_inventory)
        sync = tools.addAction('Sincronizar copia del importador desde WooCommerce')
        sync.triggered.connect(lambda _checked=False: self._load_inventory(sync=True))
        tools.addAction('Ver última sincronización').triggered.connect(self._show_sync_report)
        self._recover = tools.addAction('Recuperar propuestas locales')
        self._recover.triggered.connect(self._restore_backup)
        add_diagnostics_actions(tools, self)
        self._supplier = QPushButton('Recomprobar')
        self._supplier.setObjectName('reviewMenuButton')
        suppliers = QMenu(self)
        self._supplier.setMenu(suppliers)
        sd = suppliers.addMenu('SD Distribuciones')
        self._full_action = sd.addAction('Ficha completa y formato de sinopsis')
        self._stock_action = sd.addAction('Solo disponibilidad')
        self._full_action.triggered.connect(lambda _=False: self._recheck_sd())
        self._stock_action.triggered.connect(lambda _=False: self._recheck_sd(stock_only=True))
        for name in ('Norma Editorial', 'Milky Way', 'Planeta'):
            suppliers.addAction(name + ' · Próximamente').setEnabled(False)
        self._stop = QPushButton('Detener consulta')
        self._stop.setObjectName('clearButton')
        self._stop.clicked.connect(self._stop_sd)
        self._stop.hide()
        header.insertWidget(2, self._tools)
        header.insertWidget(3, self._supplier)
        header.addWidget(self._stop)
        self._apply = QPushButton('Revisar y aplicar en tienda')
        self._apply.clicked.connect(lambda _checked=False: self._save_proposals())
        self.layout().itemAt(4).layout().addWidget(self._apply)
        hint = self.findChild(QLabel, 'reviewHint')
        hint.setText('Datos leídos de WooCommerce. Usa Herramientas → Recargar desde WooCommerce para actualizarlos. '
                     'Marca fichas y recomprueba SD; '
                     'revisa los valores actuales y propuestos antes de aplicarlos. Doble clic para revisar propuestas de una ficha.')
        self._table.doubleClicked.connect(self._review_one)
        self._store_ready = True
        self._update_actions()

    @property
    def _busy(self):
        return self._worker is not None or self._sd_worker is not None or self._action_worker is not None

    def showEvent(self, event):
        QWidget.showEvent(self, event)
        if not self._loaded and not self._drafts:
            self._load_inventory()

    def _current_products(self):
        return [{**row, **self._drafts.get(self._key(row), {}).get('changes', {})} for row in self._products]

    def _set_feedback(self, message, *, error=False, success=False):
        if message:
            logger.log(40 if error else 20, "store.feedback %s", message)
        color, background, border = ('#991B1B', '#FEF2F2', '#F0B9B9') if error else (
            ('#166534', '#EFFAF2', '#ADD8B9') if success else ('#24538C', '#EFF6FF', '#B8D1EF'))
        self._feedback.setStyleSheet(f'color: {color}; background: {background}; border: 1px solid {border}; '
                                    'border-radius: 7px; padding: 10px 12px;')
        self._feedback.setText(message)
        self._feedback.setVisible(bool(message))

    def _fill_table(self):
        super()._fill_table()
        with QSignalBlocker(self._table):
            for index, product in enumerate(self._visible_products()):
                key = self._key(product)
                draft = self._drafts.get(key)
                if draft:
                    for column in range(self._table.columnCount()):
                        self._table.item(index, column).setBackground(QBrush(QColor('#FFF4CE')))
                note = self._table.item(index, self._table.columnCount() - 1)
                extra = self._sd_results.get(key, {}).get('note', '')
                if draft:
                    extra = ('Propuestas sin aplicar. ' + draft.get('save_error', '') + ' · ' + extra)
                note.setText(note.text() + (' · ' + extra if extra else ''))
                note.setToolTip(note.text())

    def _update_actions(self):
        super()._update_actions()
        if not self._store_ready:
            return
        self._tools.setEnabled(not self._busy)
        self._supplier.setEnabled(bool(self._selected) and not self._busy and not self._must_reload)
        self._supplier.setText(f'Recomprobar ({len(self._selected)})')
        selected = {self._key(p): p for p in self._current_products() if self._key(p) in self._selected}
        blocked = supplier_block_reason(selected, "sd")
        for action in (self._full_action, self._stock_action):
            action.setEnabled(bool(selected) and not self._busy and not self._must_reload and not blocked)
            action.setToolTip(blocked or 'Consultar las fichas marcadas en SD Distribuciones.')
        self._supplier.menu().setToolTipsVisible(True)
        self._supplier.setToolTip(blocked or 'Consultar las fichas marcadas por distribuidor.')
        if self._sd_worker:
            self._supplier.setText('Consultando SD…')
        self._stop.setVisible(self._sd_worker is not None)
        self._stop.setEnabled(self._sd_worker is not None and not self._sd_worker.stop_requested.is_set())
        keys = self._proposal_keys()
        self._apply.setText(f'Revisar y aplicar en tienda ({len(keys)})')
        self._apply.setEnabled(bool(keys) and not self._busy and not self._must_reload)
        self._recover.setEnabled(not self._busy and not self._drafts and self._draft_backup is not None
                                 and self._draft_backup.exists())
        self._summary.setText(self._summary.text() + (f' · {len(self._drafts)} con propuestas' if self._drafts else ''))
        if self._loaded_at is not None:
            self._summary.setText(self._summary.text() + ' · Leído: ' + self._loaded_at.strftime('%d/%m/%Y %H:%M'))

    def _proposal_keys(self):
        return sorted(self._selected & self._drafts.keys() if self._selected else self._drafts.keys())

    def _checkpoint(self, *, clear=False):
        if self._draft_backup is None:
            return
        try:
            if self._drafts:
                self._draft_backup.save({self._key(p): p for p in self._products if self._key(p) in self._drafts},
                                        self._drafts, self._sd_results)
            elif clear:
                self._draft_backup.clear()
        except (OSError, ValueError) as error:
            self._set_feedback('No se pudo guardar la copia local de las propuestas: ' + str(error), error=True)

    def _restore_backup(self):
        if self._busy or self._drafts or self._draft_backup is None:
            return
        try:
            saved = self._draft_backup.load()
            if not saved:
                return
            if any(p.get('review_status') != 'in_store' for p in saved['products'].values()):
                raise ValueError('La copia no corresponde a la revisión de tienda.')
            existing = {self._key(p): p for p in self._products}
            existing.update(saved['products'])
            self._products = list(existing.values())
            self._drafts = saved['drafts']
            self._sd_results = saved['sd_results']
            self._must_reload = False
            self._update_filter_options()
            self._fill_table()
            self._set_feedback('Propuestas recuperadas. Se conserva su versión original para comprobar cambios en WooCommerce.')
        except (OSError, ValueError) as error:
            self._set_feedback(str(error), error=True)

    def _load_inventory(self, *, sync=False):
        if self._busy:
            return
        if self._drafts and QMessageBox.question(self, 'Propuestas pendientes',
                'Hay propuestas sin aplicar. ¿Descartarlas de esta pantalla y cargar los datos actuales de WooCommerce?',
                QMessageBox.StandardButton.Discard | QMessageBox.StandardButton.Cancel,
                QMessageBox.StandardButton.Cancel) != QMessageBox.StandardButton.Discard:
            return
        try:
            api = self._api()
        except Exception as error:
            self._set_feedback(str(error), error=True)
            return
        self._worker = StoreLoadWorker(api, self, sync=sync)
        self._worker.discard_drafts = bool(self._drafts)
        self._worker.finished.connect(self._finish_load_store)
        self._worker.progress.connect(self._load_progress)
        self._update_actions()
        self._set_feedback('Sincronizando la copia del importador desde WooCommerce…' if sync else
                           'Leyendo los productos actuales de WooCommerce…')
        self._worker.start()

    def _load_progress(self, completed, total):
        self._summary.setText(f'Leyendo WooCommerce · {completed}/{total} fichas')

    def _show_sync_report(self):
        result = self._last_sync_result
        if result is None:
            self._set_feedback('Usa Herramientas → Sincronizar copia del importador desde WooCommerce para actualizarla.')
            return
        from PySide6.QtWidgets import QDialog, QDialogButtonBox, QPlainTextEdit, QVBoxLayout
        dialog = QDialog(self)
        dialog.setWindowTitle('Resultado de sincronización con WooCommerce')
        dialog.resize(820, 480)
        layout = QVBoxLayout(dialog)
        text = QPlainTextEdit()
        text.setReadOnly(True)
        lines = [f"Nuevos vínculos: {result['linked']} · Copias actualizadas: {result.get('updated', 0)}",
                 f"Sin cambios: {result.get('unchanged', 0)} · Sin ficha en el importador: {result['not_in_importer']}",
                 f"Eliminadas: {result.get('missing', 0)} · Sin publicar: {result.get('unpublished', 0)}",
                 f"Conflictos de vínculo o ISBN: {result.get('conflicts', 0)}",
                 'Las fichas eliminadas o sin publicar conservan su última copia y vínculo; no vuelven a pendientes.', '']
        lines.extend(f"ID {row['woocommerce_id']} · {row['isbn']} · {row['status']} · {row.get('message', '')}"
                     for row in result.get('issues', []))
        text.setPlainText('\n'.join(lines))
        layout.addWidget(text)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        buttons.button(QDialogButtonBox.StandardButton.Close).setText('Cerrar')
        buttons.rejected.connect(dialog.reject)
        layout.addWidget(buttons)
        dialog.exec()
        dialog.deleteLater()

    def _finish_load_store(self):
        worker, self._worker = self._worker, None
        if worker.sync_result is not None:
            self._last_sync_result = worker.sync_result
        if worker.products is not None:
            self._products = worker.products
            self._drafts.clear()
            self._sd_results.clear()
            self._selected.clear()
            self._must_reload = False
            self._loaded = True
            self._loaded_at = datetime.now()
            self._checkpoint(clear=getattr(worker, 'discard_drafts', False))
            self._update_filter_options()
            self._fill_table()
            message = f'{len(self._products)} fichas leídas de WooCommerce.'
            if worker.sync_result is not None:
                result = worker.sync_result
                message += (f" Copia del importador: {result.get('updated', 0)} actualizadas · "
                            f"{result['linked']} nuevos vínculos · {result.get('missing', 0)} eliminadas · "
                            f"{result.get('unpublished', 0)} sin publicar · {result.get('conflicts', 0)} conflictos. "
                            'Puedes ver el detalle en Herramientas → Ver última sincronización.')
            self._set_feedback(message, success=True)
        else:
            self._set_feedback(('La copia se sincronizó, pero falló la lectura de la tienda. ' if worker.sync_result is not None
                                else 'No se pudo leer la tienda. ') + str(worker.error), error=True)
        worker.deleteLater()
        self._update_actions()

    def _recheck_sd(self, *, stock_only=False):
        if self._busy or not self._selected or self._must_reload:
            return
        products = {self._key(p): p for p in self._current_products() if self._key(p) in self._selected}
        blocked = supplier_block_reason(products, 'sd')
        if blocked:
            self._set_feedback(blocked, error=True)
            return
        self._sd_worker = SdRecheckWorker(products, self, stock_only=stock_only)
        self._sd_worker.progress.connect(self._progress)
        self._sd_worker.finished.connect(self._finish_sd)
        self._set_feedback('Consultando solo disponibilidad SD…' if stock_only else
                           'Consultando SD y preparando el formato de sinopsis. Las propuestas quedarán sin aplicar.')
        self._update_actions()
        self._sd_worker.start()

    def _stop_sd(self):
        if self._sd_worker:
            self._sd_worker.stop_requested.set()
            self._stop.setEnabled(False)
            self._stop.setText('Deteniendo…')

    def _progress(self, completed, total):
        self._supplier.setText(f'SD · {completed}/{total}')

    def _finish_sd(self):
        worker, self._sd_worker = self._sd_worker, None
        changed = errors = 0
        changed_keys = []
        for key, result in worker.results.items():
            product = worker.products[key]
            suggestions, note = sd_review_changes(product, result, stock_only=worker.stock_only)
            changes = store_changes(suggestions)
            if 'retail_price' in changes and not product.get('sale_price'):
                changes['sale_price'] = sale_price_preview(changes['retail_price'])
            if changes:
                self._drafts.setdefault(key, {'changes': {}, 'ready_to_upload': False})['changes'].update(changes)
                changed += 1
                changed_keys.append(key)
            errors += result.status in ('error', 'not_found')
            if any(field not in changes for field in suggestions):
                note += ' · Portada y categorías se conservan; esta actualización aplica datos de ficha y disponibilidad.'
            self._sd_results[key] = {'note': note, 'url': result.url, 'result': result.status}
        self._checkpoint()
        self._update_filter_options()
        self._fill_table()
        self._stop.setText('Detener consulta')
        self._set_feedback(f'SD: {changed} ficha(s) con propuestas · {errors} con error o sin encontrar. '
                           + ('Revisa los campos que quieres aplicar.' if changed else 'No hay cambios nuevos que revisar.')
                           + (' ' + str(worker.error) if worker.error else ''), error=bool(worker.error))
        worker.deleteLater()
        self._update_actions()
        if changed_keys:
            self._save_proposals(keys=changed_keys)

    def _review_one(self, index):
        if not index.isValid() or self._busy:
            return
        key = self._table.item(index.row(), 0).data(Qt.ItemDataRole.UserRole)
        if key in self._drafts:
            self._save_proposals(keys=[key])

    def _save_proposals(self, *, keys=None):
        if self._busy or self._must_reload:
            return
        keys = self._proposal_keys() if keys is None else keys
        stored = {self._key(p): p for p in self._products}
        rows = {key: {'product': stored[key], 'changes': dict(self._drafts[key]['changes'])}
                for key in keys if key in self._drafts}
        selected = review_changes(rows, store=True, parent=self)
        if selected is None:
            return
        discarded = confirm_change_selection(self._drafts, rows, selected, self._selected)
        for key in rows:
            if key not in self._drafts:
                self._sd_results.pop(key, None)
        self._checkpoint(clear=True)
        self._fill_table()
        if not selected:
            self._set_feedback(f'{discarded} cambio(s) descartados. Se conservan los valores de WooCommerce.')
            return
        try:
            api = self._api()
        except Exception as error:
            self._set_feedback(str(error), error=True)
            return
        entries = [{'id': stored[key]['woocommerce_id'], 'expected_revision': stored[key]['_store_revision'],
                    'changes': changes} for key, changes in selected.items()]
        self._checkpoint()
        self._action_worker = StoreSaveWorker(api, entries, self)
        self._action_worker.finished.connect(self._finish_save_store)
        self._set_feedback('Aplicando los campos aceptados en WooCommerce…')
        self._update_actions()
        self._action_worker.start()

    def _finish_save_store(self):
        worker, self._action_worker = self._action_worker, None
        stored = {self._key(p): p for p in self._products}
        requested = {str(entry['id']): entry['changes'] for entry in worker.entries}
        for row in worker.result['saved']:
            key = str(row['id'])
            stored[key] = row['product']
            draft = self._drafts.get(key)
            if draft:
                rest = {field: value for field, value in draft['changes'].items() if field not in requested[key]}
                if rest:
                    self._drafts[key] = {'changes': rest, 'ready_to_upload': False}
                else:
                    self._drafts.pop(key, None)
            self._selected.discard(key)
        for row in worker.result['failed']:
            key = str(row['id'])
            if key in self._drafts:
                self._drafts[key]['save_error'] = row['message']
        self._products = list(stored.values())
        self._must_reload = worker.error is not None
        self._checkpoint(clear=bool(worker.result['saved']))
        self._update_filter_options()
        self._fill_table()
        saved, failed = len(worker.result['saved']), len(worker.result['failed'])
        details = '\n'.join(f"ID {row['id']}: {row['message']}" for row in worker.result['failed'][:6])
        self._set_feedback(f'{saved} ficha(s) actualizadas en tienda · {failed} pendientes con incidencias. '
                           + ('Las propuestas no confirmadas se conservan. ' if self._drafts else '')
                           + (str(worker.error) if worker.error else '') + ('\n' + details if details else ''),
                           error=bool(failed or worker.error), success=not (failed or worker.error))
        worker.deleteLater()
        self._update_actions()

    def can_leave(self):
        if self._busy:
            self._set_feedback('Espera a que termine la consulta o el guardado antes de salir.')
            return False
        self._checkpoint()
        return True
