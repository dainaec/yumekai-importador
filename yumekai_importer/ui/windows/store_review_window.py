"""Review live WooCommerce data and explicitly apply supplier suggestions."""
from yumekai_importer.ui.widgets.presentation import button_role
from datetime import datetime
from time import perf_counter
from uuid import uuid4
from PySide6.QtCore import Qt, QSignalBlocker, QTimer, QElapsedTimer, QUrl
from PySide6.QtGui import QBrush, QColor, QDesktopServices
from PySide6.QtWidgets import (QComboBox, QDialog, QLabel, QMenu, QMessageBox, QProgressBar, QPushButton, QWidget)

from yumekai_importer.catalog.sd_review import sd_review_changes
from yumekai_importer.catalog.norma_review import norma_review_changes
from yumekai_importer.catalog.store_review import store_changes
from yumekai_importer.catalog.suppliers import supplier_block_reason
from yumekai_importer.catalog.change_selection import confirm_change_selection
from yumekai_importer.diagnostics import logger
from yumekai_importer.ui.windows.inventory_window import InventoryWindow, INVENTORY_COLUMNS
from yumekai_importer.ui.widgets.change_review_dialog import review_changes
from yumekai_importer.ui.workers.sd_recheck_worker import SdRecheckWorker
from yumekai_importer.ui.workers.norma_recheck_worker import NormaRecheckWorker
from yumekai_importer.ui.widgets.norma_access_dialog import NormaAccessDialog
from yumekai_importer.storage.norma_credentials import load_norma_credentials, forget_norma_credentials
from yumekai_importer.ui.workers.store_workers import StoreLoadWorker, StoreSaveWorker, StoreCatalogWorker
from yumekai_importer.ui.widgets.store_product_dialog import StoreProductDialog
from yumekai_importer.storage.store_creation import PendingStoreCreation
from yumekai_importer.storage.review_draft_backup import ReviewDraftBackup


PUBLICATION_LABELS = {'publish': 'Publicado', 'draft': 'Borrador', 'pending': 'Pendiente', 'private': 'Privado'}


class StoreReviewWindow(InventoryWindow):
    columns = (*INVENTORY_COLUMNS[:2], ('publication_status', 'Publicación', 120),
               ('woocommerce_id', 'ID tienda', 90), *INVENTORY_COLUMNS[2:])

    @staticmethod
    def _key(product):
        return str(product['woocommerce_id'])

    def __init__(self, *, draft_backup=None):
        self._store_ready = False
        self._sd_worker = self._action_worker = None
        self._norma_worker = None
        self._norma_access = None
        self._norma_remember_access = False
        self._drafts, self._sd_results = {}, {}
        self._draft_backup = draft_backup
        self._must_reload = False
        self._loaded = False
        self._loaded_at = None
        self._loaded_status = 'publish'
        self._store_options = {}
        self._creation_backup = PendingStoreCreation()
        self._manual_backup = ReviewDraftBackup(self._creation_backup.path.with_name('store-edit-recovery.json'))
        self._manual_recovery = None
        self._load_clock = QElapsedTimer()
        self._load_counts = (0, 0)
        self._post_load_notice = ''
        super().__init__()
        header = self.layout().itemAt(0).layout()
        header.itemAt(0).widget().setText('Productos en tienda')
        self._sync_button.hide()
        self._publication_filter = QComboBox()
        for caption, value in [('Publicados', 'publish'), ('Borradores', 'draft'), ('Todo el catálogo', 'all')]:
            self._publication_filter.addItem(caption, value)
        self._publication_filter.setAccessibleName('Filtrar por publicación')
        self._publication_filter.currentIndexChanged.connect(self._publication_changed)
        self.layout().itemAt(1).layout().insertWidget(0, self._publication_filter)
        self._refresh_button.setText('Actualizar tienda')
        self._refresh_button.setToolTip('Volver a consultar WooCommerce para ver los cambios realizados en la web o desde otro equipo.')
        self._recover = QPushButton('Recuperar revisión sin guardar')
        self._recover.clicked.connect(self._restore_backup)
        self._recover.setToolTip('Recupera una revisión de proveedor que quedó sin aplicar. Solo aparece si hay una copia local.')
        header.insertWidget(2, self._recover)
        self._supplier = QPushButton('Recomprobar')
        self._supplier.setObjectName('reviewMenuButton')
        suppliers = QMenu(self)
        self._supplier.setMenu(suppliers)
        sd = suppliers.addMenu('SD Distribuciones')
        self._full_action = sd.addAction('Ficha completa y formato de sinopsis')
        self._stock_action = sd.addAction('Solo disponibilidad')
        self._full_action.triggered.connect(lambda _=False: self._recheck_sd())
        self._stock_action.triggered.connect(lambda _=False: self._recheck_sd(stock_only=True))
        norma = suppliers.addMenu('Norma Editorial')
        self._norma_full_action = norma.addAction('Recomprobar ficha completa')
        self._norma_stock_action = norma.addAction('Solo stock')
        self._norma_full_action.triggered.connect(lambda _=False: self._recheck_norma())
        self._norma_stock_action.triggered.connect(lambda _=False: self._recheck_norma(stock_only=True))
        norma.addSeparator()
        self._norma_access_action = norma.addAction('Acceso ZonaLibros…')
        self._norma_forget_action = norma.addAction('Olvidar acceso ZonaLibros')
        self._norma_access_action.triggered.connect(lambda _=False: self._configure_norma_access())
        self._norma_forget_action.triggered.connect(self._forget_norma_access)
        for name in ('Milky Way', 'Planeta'):
            suppliers.addAction(name + ' · Próximamente').setEnabled(False)
        self._stop = QPushButton('Detener consulta')
        self._stop.setObjectName('clearButton')
        self._stop.clicked.connect(self._stop_sd)
        self._stop.hide()
        header.insertWidget(3, self._supplier)
        header.addWidget(self._stop)
        self._cancel_load = QPushButton('Cancelar lectura')
        self._cancel_load.setObjectName('clearButton')
        self._cancel_load.clicked.connect(self._cancel_read)
        self._cancel_load.hide()
        header.addWidget(self._cancel_load)
        self._load_bar = QProgressBar()
        self._load_bar.setTextVisible(False)
        self._load_bar.setMaximumHeight(6)
        self._load_bar.hide()
        self.layout().insertWidget(7, self._load_bar)
        self._load_timer = QTimer(self)
        self._load_timer.setInterval(500)
        self._load_timer.timeout.connect(self._tick_load)
        self._apply = QPushButton('Revisar y aplicar en tienda')
        self._apply.clicked.connect(lambda _checked=False: self._save_proposals())
        actions = self.layout().itemAt(4).layout()
        self._new_product = QPushButton('Nuevo producto')
        self._new_product.clicked.connect(self._create_product)
        self._edit_product = QPushButton('Editar ficha')
        self._edit_product.clicked.connect(self._edit_selected)
        self._unpublish = QPushButton('Despublicar')
        self._unpublish.clicked.connect(lambda: self._change_publication('unpublish'))
        self._publish = QPushButton('Publicar')
        self._publish.clicked.connect(lambda: self._change_publication('publish'))
        for index, button in enumerate((self._new_product, self._edit_product, self._unpublish, self._publish), 1):
            button.setObjectName('clearButton')
            actions.insertWidget(index, button)
        self._open_web = QPushButton('Ver ficha web')
        self._open_web.clicked.connect(self._open_selected_web)
        self._open_web.setToolTip('Abre el enlace exacto del ID seleccionado, para distinguir tomos y ediciones.')
        actions.insertWidget(5, self._open_web)
        actions.addWidget(self._apply)
        button_role(self._supplier, 'soft')
        button_role(self._edit_product, 'secondary')
        button_role(self._open_web, 'quiet')
        button_role(self._unpublish, 'danger')
        button_role(self._clear_filters, 'quiet')
        hint = self.findChild(QLabel, 'reviewHint')
        hint.setText('Datos actuales de WooCommerce. Actualizar tienda vuelve a consultar la web. '
                     'Doble clic para editar una ficha o revisar las propuestas del proveedor. '
                     'Despublicar la pasa a Borradores; puedes volver a publicarla desde aquí.')
        self._table.doubleClicked.connect(self._review_one)
        self._store_ready = True
        self._update_actions()

    @property
    def _busy(self):
        return any(worker is not None for worker in (self._worker, self._sd_worker, self._norma_worker, self._action_worker))

    def showEvent(self, event):
        QWidget.showEvent(self, event)
        if not self._loaded and not self._drafts:
            self._load_inventory()

    def _current_products(self):
        return [dict(row) for row in self._products]

    def _set_feedback(self, message, *, error=False, success=False, warning=False):
        if message:
            logger.log(40 if error else 20, "store.feedback %s", message)
        self._feedback_banner.set_message(message, 'error' if error else 'warning' if warning else 'success' if success else 'info')

    def _fill_table(self):
        super()._fill_table()
        with QSignalBlocker(self._table):
            for index, product in enumerate(self._current_products()):
                key = self._key(product)
                draft = self._drafts.get(key)
                self._table.item(index, 2).setText(PUBLICATION_LABELS.get(product.get('publication_status'), str(product.get('publication_status', ''))))
                status_column = next(i for i, (field, _, _) in enumerate(self.columns) if field == 'yumekai_status')
                code = product.get('yumekai_status')
                self._table.item(index, status_column).setText(self._store_options.get('stock_statuses', {}).get(code, str(code or 'Sin valor')))
                if draft:
                    for column in range(self._table.columnCount()):
                        self._table.item(index, column).setBackground(QBrush(QColor('#FFF4CE')))
                note = self._table.item(index, self._table.columnCount() - 1)
                extra = self._sd_results.get(key, {}).get('note', '')
                if product.get('category_issue'):
                    extra = product['category_issue'] + (' · ' + extra if extra else '')
                if draft:
                    extra = ('Propuestas sin aplicar. ' + draft.get('save_error', '') + ' · ' + extra)
                note.setText(note.text() + (' · ' + extra if extra else ''))
                note.setToolTip(note.text())

    def _update_actions(self):
        super()._update_actions()
        if not self._store_ready:
            return
        self._refresh_button.setText('Actualizando…' if self._worker else 'Actualizar tienda')
        self._publication_filter.setEnabled(not self._busy)
        self._cancel_load.setVisible(self._worker is not None)
        self._cancel_load.setEnabled(self._worker is not None and not self._worker.stop_requested.is_set())
        self._new_product.setEnabled(not self._busy and bool(self._store_options) and not self._must_reload and not self._drafts)
        self._new_product.setText('Recuperar creación' if self._creation_backup.path.exists() else 'Nuevo producto')
        primary = 'publish' if any(p.get('publication_status') == 'draft' and self._key(p) in self._selected for p in self._products) else 'apply' if self._drafts else 'new'
        button_role(self._new_product, 'primary' if primary == 'new' else 'secondary')
        button_role(self._apply, 'primary' if primary == 'apply' else 'secondary')
        button_role(self._publish, 'primary' if primary == 'publish' else 'secondary')
        selected_rows = [p for p in self._products if self._key(p) in self._selected]
        safe = bool(selected_rows) and not self._busy and not self._must_reload and not any(self._key(p) in self._drafts for p in selected_rows)
        self._edit_product.setEnabled(safe and len(selected_rows) == 1 and selected_rows[0].get('product_type') == 'simple')
        self._unpublish.setEnabled(safe and all(p.get('publication_status') in ('publish', 'draft') for p in selected_rows))
        verifying_drafts = bool(selected_rows) and all(p.get('publication_status') == 'draft' for p in selected_rows)
        self._unpublish.setText('Comprobar retirada' if verifying_drafts else 'Despublicar')
        button_role(self._unpublish, 'secondary' if verifying_drafts else 'danger')
        self._publish.setEnabled(safe and all(p.get('publication_status') == 'draft' for p in selected_rows))
        self._unpublish.setToolTip('Pasa los productos marcados a borrador y los retira de la web. Se pueden volver a publicar.')
        self._open_web.setEnabled(len(selected_rows) == 1 and not self._busy and bool(selected_rows[0].get('product_url')))
        self._supplier.setEnabled(bool(self._selected) and not self._busy and not self._must_reload)
        self._supplier.setText(f'Recomprobar ({len(self._selected)})')
        selected = {self._key(p): p for p in self._current_products() if self._key(p) in self._selected}
        blocked = supplier_block_reason(selected, "sd")
        if any(p.get('publication_status') != 'publish' for p in selected.values()):
            blocked = 'La revisión SD en tienda requiere productos publicados. Puedes editar los borradores con Editar ficha.'
        for action in (self._full_action, self._stock_action):
            action.setEnabled(bool(selected) and not self._busy and not self._must_reload and not blocked)
            action.setToolTip(blocked or 'Consultar las fichas marcadas en SD Distribuciones.')
        norma_blocked = supplier_block_reason(selected, 'norma')
        if any(p.get('publication_status') != 'publish' for p in selected.values()):
            norma_blocked = 'La revisión Norma en tienda requiere productos publicados. Puedes editar los borradores con Editar ficha.'
        for action in (self._norma_full_action, self._norma_stock_action):
            action.setEnabled(bool(selected) and not self._busy and not self._must_reload and not norma_blocked)
            action.setToolTip(norma_blocked or 'Consultar las fichas marcadas en Norma ZonaLibros.')
        self._norma_access_action.setEnabled(not self._busy)
        self._norma_forget_action.setEnabled(not self._busy)
        self._supplier.menu().setToolTipsVisible(True)
        self._supplier.setToolTip('Volver a consultar y comparar las fichas marcadas por distribuidor.')
        if self._sd_worker:
            self._supplier.setText('Consultando SD…')
        if self._norma_worker:
            self._supplier.setText('Consultando Norma…')
        supplier_worker = self._norma_worker or self._sd_worker
        self._stop.setVisible(supplier_worker is not None)
        self._stop.setEnabled(supplier_worker is not None and not supplier_worker.stop_requested.is_set())
        keys = self._proposal_keys()
        self._apply.setText(f'Revisar y aplicar en tienda ({len(keys)})')
        self._apply.setEnabled(bool(keys) and not self._busy and not self._must_reload)
        self._recover.setVisible(not self._drafts and self._draft_backup is not None and self._draft_backup.exists())
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
            self._restore_publication_filter()
            return
        try:
            api = self._api()
        except Exception as error:
            self._restore_publication_filter()
            self._set_feedback(str(error), error=True)
            return
        self._worker = StoreLoadWorker(api, self, sync=sync, status=self._publication_filter.currentData())
        self._worker.discard_drafts = bool(self._drafts)
        self._worker.finished.connect(self._finish_load_store)
        self._worker.progress.connect(self._load_progress)
        self._update_actions()
        self._set_feedback('Sincronizando la copia del importador desde WooCommerce…' if sync else
                           'Leyendo los productos actuales de WooCommerce…')
        self._load_counts = (0, 0)
        self._load_clock.start()
        self._load_bar.setRange(0, 0)
        self._load_bar.show()
        self._cancel_load.setText('Cancelar lectura')
        self._load_timer.start()
        self._worker.start()

    def _restore_publication_filter(self):
        with QSignalBlocker(self._publication_filter):
            self._publication_filter.setCurrentIndex(max(0, self._publication_filter.findData(self._loaded_status)))

    def _publication_changed(self):
        self._load_inventory()

    def _cancel_read(self):
        if self._worker is not None:
            self._worker.stop_requested.set()
            self._cancel_load.setText('Cancelando…')
            self._cancel_load.setEnabled(False)
            self._set_feedback('Cancelando la lectura. Se espera a que termine la petición en curso (hasta 35 s sin respuesta). El listado anterior se conserva.')

    def _tick_load(self):
        if self._worker is None:
            return
        completed, total = self._load_counts
        elapsed = self._load_clock.elapsed() / 1000
        count = f'{completed}/{total} fichas' if total else 'esperando la primera respuesta'
        self._summary.setText(f'WooCommerce · {count} · {elapsed:.0f} s')

    def _load_progress(self, completed, total):
        if self._worker is None:
            return
        self._load_counts = (completed, total)
        self._load_bar.setRange(0, max(1, total))
        self._load_bar.setValue(completed)
        self._tick_load()

    def _finish_load_store(self):
        worker, self._worker = self._worker, None
        self._load_timer.stop()
        self._load_bar.hide()
        if worker.products is not None:
            self._products = worker.products
            self._store_options = worker.options
            self._loaded_status = worker.status
            self._drafts.clear()
            self._sd_results.clear()
            self._selected.clear()
            self._must_reload = False
            self._loaded = True
            self._loaded_at = datetime.now()
            self._checkpoint(clear=getattr(worker, 'discard_drafts', False))
            rendered = perf_counter()
            self._update_filter_options()
            self._fill_table()
            render_elapsed = perf_counter() - rendered
            logger.info('store.rendered products=%s elapsed=%.2fs', len(self._products), render_elapsed)
            message = f'{len(self._products)} fichas leídas de WooCommerce · consulta {worker.elapsed:.1f} s · tabla {render_elapsed:.1f} s.'
            if worker.sync_result is not None:
                result = worker.sync_result
                message += (f" Copia del importador: {result.get('updated', 0)} actualizadas · "
                            f"{result['linked']} nuevos vínculos · {result.get('missing', 0)} eliminadas · "
                            f"{result.get('unpublished', 0)} sin publicar · {result.get('conflicts', 0)} conflictos. "
                            'El cruce de fichas se actualiza al abrir Revisar pendientes.')
            self._set_feedback((self._post_load_notice + ' ' if self._post_load_notice else '') + message, success=True)
            self._post_load_notice = ''
        elif worker.cancelled:
            self._restore_publication_filter()
            self._set_feedback(f'Lectura cancelada tras {worker.elapsed:.1f} s. Se conserva el listado anterior.'
                               + (' La sincronización de la copia del importador ya había terminado.' if worker.sync_result is not None else ''))
        else:
            self._must_reload = True
            self._restore_publication_filter()
            self._set_feedback(self._post_load_notice + ('La copia se sincronizó, pero falló la lectura de la tienda. ' if worker.sync_result is not None
                                else 'No se pudo leer la tienda. ') + str(worker.error), error=True)
        worker.deleteLater()
        self._update_actions()

    def _recheck_sd(self, *, stock_only=False):
        if self._busy or not self._selected or self._must_reload:
            return
        products = {self._key(p): p for p in self._current_products() if self._key(p) in self._selected}
        blocked = supplier_block_reason(products, 'sd')
        if any(p.get('publication_status') != 'publish' for p in products.values()):
            blocked = 'La revisión SD requiere productos publicados.'
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
        worker = self._norma_worker or self._sd_worker
        if worker:
            worker.stop_requested.set()
            self._stop.setEnabled(False)
            self._stop.setText('Deteniendo…')

    def _progress(self, completed, total):
        name = 'Norma' if self._norma_worker is not None else 'SD'
        self._supplier.setText(f'{name} · {completed}/{total}')

    def _finish_sd(self):
        worker, self._sd_worker = self._sd_worker, None
        self._finish_supplier(worker, 'SD', sd_review_changes)

    def _finish_norma(self):
        worker, self._norma_worker = self._norma_worker, None
        self._finish_supplier(worker, 'Norma', norma_review_changes)

    def _finish_supplier(self, worker, supplier, compare):
        if worker is None:
            return
        changed = errors = 0
        changed_keys = []
        for key, result in worker.results.items():
            product = worker.products[key]
            suggestions, note = compare(product, result, stock_only=worker.stock_only)
            changes = store_changes(suggestions)
            if 'yumekai_status' in changes and changes['yumekai_status'] is None:
                changes.pop('yumekai_status')
                note += ' · Disponibilidad sin confirmar: se conserva el estado publicado.'
            if changes:
                self._drafts.setdefault(key, {'changes': {}, 'ready_to_upload': False})['changes'].update(changes)
                changed += 1
                changed_keys.append(key)
            errors += result.status in ('error', 'not_found')
            if any(field not in changes for field in suggestions):
                note += ' · Los campos sin actualización admitida en tienda se conservan.'
            self._sd_results[key] = {'note': note, 'url': result.url, 'result': result.status, 'supplier': supplier.casefold()}
        self._checkpoint()
        self._update_filter_options()
        self._fill_table()
        self._stop.setText('Detener consulta')
        self._set_feedback(f'{supplier}: {changed} ficha(s) con propuestas · {errors} con error o sin encontrar. '
                           + ('Revisa los campos que quieres aplicar.' if changed else 'No hay cambios nuevos que revisar.')
                           + (' ' + str(worker.error) if worker.error else ''), error=bool(worker.error))
        worker.deleteLater()
        self._update_actions()
        if changed_keys:
            if worker.stock_only:
                self._save_proposals(keys=changed_keys, fields={'yumekai_status'})
            else:
                self._save_proposals(keys=changed_keys)

    def _recheck_norma(self, *, stock_only=False):
        if self._busy or not self._selected or self._must_reload:
            return
        products = {self._key(p): p for p in self._current_products() if self._key(p) in self._selected}
        blocked = supplier_block_reason(products, 'norma')
        if any(p.get('publication_status') != 'publish' for p in products.values()):
            blocked = 'La revisión Norma requiere productos publicados.'
        if blocked:
            self._set_feedback(blocked, error=True)
            return
        if self._norma_access is None:
            try:
                self._norma_access = load_norma_credentials()
                self._norma_remember_access = self._norma_access is not None
            except Exception:
                self._norma_access = None
        if self._norma_access is None and not self._configure_norma_access():
            return
        self._norma_worker = NormaRecheckWorker(products, self, credentials=self._norma_access,
            remember_access=self._norma_remember_access, stock_only=stock_only)
        self._norma_worker.progress.connect(self._progress)
        self._norma_worker.finished.connect(self._finish_norma)
        self._set_feedback(('Consultando solo stock en Norma ZonaLibros, sin MangaUpdates. ' if stock_only else
                            'Recomprobando los datos actuales de Norma, incluidos los campos ya rellenados. ') +
                           'Las diferencias se revisarán antes de aplicarlas en tienda.')
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
                    self._set_feedback('No se pudo olvidar el acceso anterior de Norma en este equipo.', error=True)
                    dialog.deleteLater()
                    return False
            self._norma_access, self._norma_remember_access = dialog.credentials, dialog.remember
        dialog.deleteLater()
        return accepted

    def _forget_norma_access(self):
        if self._busy:
            return
        self._norma_access, self._norma_remember_access = None, False
        try:
            forget_norma_credentials()
            self._set_feedback('Acceso de Norma olvidado en este equipo.')
        except Exception:
            self._set_feedback('No se pudo borrar el acceso guardado de Norma en este equipo.', error=True)

    def _review_one(self, index):
        if not index.isValid() or self._busy:
            return
        key = self._table.item(index.row(), 0).data(Qt.ItemDataRole.UserRole)
        if key in self._drafts:
            self._save_proposals(keys=[key])
        else:
            self._edit_store_product(key)

    def _edit_selected(self):
        if len(self._selected) == 1:
            self._edit_store_product(next(iter(self._selected)))

    def _edit_store_product(self, key):
        if self._busy or self._must_reload or not self._store_options:
            return
        product = next((p for p in self._products if self._key(p) == key), None)
        if product is None:
            return
        if product.get('product_type') != 'simple':
            self._set_feedback('El editor admite productos simples. Edita las variaciones y otros tipos desde WooCommerce.')
            return
        try:
            self._load_manual_recovery()
        except (OSError, ValueError) as error:
            self._set_feedback(str(error), error=True)
            return
        recovered = self._manual_recovery['drafts'].get(key, {}).get('changes')
        dialog = StoreProductDialog(product, self._store_options, self, recovered_changes=recovered)
        accepted = dialog.exec() == QDialog.DialogCode.Accepted
        changes, discard_recovered = dialog.changes, dialog.discard_recovered
        dialog.deleteLater()
        if discard_recovered or (accepted and not changes):
            self._manual_recovery['products'].pop(key, None)
            self._manual_recovery['drafts'].pop(key, None)
            try:
                self._save_manual_recovery()
                if discard_recovered:
                    self._set_feedback('Edición local descartada. Se conservan los valores de WooCommerce.')
            except OSError as error:
                self._set_feedback(str(error), error=True)
            return
        if accepted and changes:
            self._manual_recovery['products'][key] = product
            self._manual_recovery['drafts'][key] = {'changes': changes, 'ready_to_upload': False}
            try:
                self._save_manual_recovery()
            except OSError as error:
                self._set_feedback('No se pudo guardar la copia de la edición; no se ha enviado. ' + str(error), error=True)
                return
            self._start_catalog_action('update', entries=[{'id': product['woocommerce_id'],
                'expected_revision': product['_store_revision'], 'changes': changes}])

    def _load_manual_recovery(self):
        if self._manual_recovery is None:
            self._manual_recovery = self._manual_backup.load() or {'products': {}, 'drafts': {}, 'sd_results': {}}

    def _save_manual_recovery(self):
        if self._manual_recovery['drafts']:
            self._manual_backup.save(self._manual_recovery['products'], self._manual_recovery['drafts'], {})
        else:
            self._manual_backup.clear()

    def _create_product(self):
        if self._busy or self._must_reload or not self._store_options:
            return
        try:
            pending = self._creation_backup.load()
            if pending and not pending.get('rejected'):
                if QMessageBox.question(self, 'Creación pendiente',
                        'Hay una creación cuyo resultado no se confirmó. ¿Comprobarla y completar la misma solicitud? '
                        'El identificador guardado evita crear otro producto al reintentar.',
                        QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel,
                        QMessageBox.StandardButton.Cancel) != QMessageBox.StandardButton.Yes:
                    return
            else:
                dialog = StoreProductDialog(None, self._store_options, self,
                                            recovered_changes=pending['fields'] if pending else None)
                accepted = dialog.exec() == QDialog.DialogCode.Accepted
                fields, discarded = dialog.changes, dialog.discard_recovered
                dialog.deleteLater()
                if discarded:
                    self._creation_backup.clear()
                    self._set_feedback('Creación local descartada.')
                    self._update_actions()
                    return
                if not accepted:
                    return
                pending = {'fields': fields, 'request_id': uuid4().hex}
                # Save the token before sending; recover it even after restarting the application.
                self._creation_backup.save(pending)
            self._start_catalog_action('create', fields=pending['fields'], request_id=pending['request_id'])
        except (OSError, ValueError) as error:
            self._set_feedback(str(error), error=True)

    def _open_selected_web(self):
        if self._busy or len(self._selected) != 1:
            return
        product = next((p for p in self._products if self._key(p) in self._selected), None)
        url = QUrl(str(product.get('product_url') or '')) if product else QUrl()
        if url.scheme() in ('https', 'http') and url.host():
            QDesktopServices.openUrl(url)

    def _change_publication(self, action):
        if self._busy or self._must_reload:
            return
        products = [p for p in self._products if self._key(p) in self._selected]
        required = ('publish', 'draft') if action == 'unpublish' else ('draft',)
        if not products or any(p.get('publication_status') not in required or self._key(p) in self._drafts for p in products):
            return
        already_draft = action == 'unpublish' and all(p.get('publication_status') == 'draft' for p in products)
        title = 'Comprobar retirada de la web' if already_draft else 'Despublicar productos' if action == 'unpublish' else 'Publicar productos'
        explanation = ('Se retirarán de la web y pasarán a Borradores. Podrás volver a publicarlos.' if action == 'unpublish'
                       else 'Estos borradores aparecerán en la web con sus datos actuales.')
        if already_draft:
            explanation = 'Estos productos figuran como borrador. Se comprobará su estado guardado y se renovará la ficha pública para completar su retirada.'
        names = '\n'.join(f"ID {p['woocommerce_id']} · {p.get('title', '')} · ISBN {p.get('isbn') or 'sin código'}" for p in products[:8])
        if len(products) > 8:
            names += f'\n… y {len(products) - 8} más'
        if QMessageBox.question(self, title, f'{explanation}\n\n{len(products)} producto(s):\n{names}',
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel,
                QMessageBox.StandardButton.Cancel) != QMessageBox.StandardButton.Yes:
            return
        self._start_catalog_action(action, entries=[{'id': p['woocommerce_id'],
                                    'expected_revision': p['_store_revision']} for p in products])

    def _start_catalog_action(self, action, **kwargs):
        try:
            api = self._api()
        except Exception as error:
            self._set_feedback(str(error), error=True)
            return
        self._action_worker = StoreCatalogWorker(api, action, parent=self, **kwargs)
        self._action_worker.finished.connect(self._finish_catalog_action)
        self._set_feedback('Creando el borrador en WooCommerce…' if action == 'create' else 'Guardando en WooCommerce…')
        self._update_actions()
        self._action_worker.start()

    def _finish_catalog_action(self):
        worker, self._action_worker = self._action_worker, None
        stored = {self._key(p): p for p in self._products}
        rows = worker.result['saved']
        clear_error = ''
        if worker.created:
            rows = [worker.created]
            try:
                self._creation_backup.clear()
            except OSError:
                clear_error = ' Se mantiene la confirmación local; al recuperar no se creará un duplicado.'
        elif worker.action == 'create' and worker.definite_rejection:
            try:
                self._creation_backup.save({'fields': worker.fields, 'request_id': worker.request_id, 'rejected': True})
            except OSError:
                clear_error = ' No se pudo actualizar la copia local de creación.'
        for row in rows:
            key = str(row['id'])
            if worker.action == 'update' and self._manual_recovery is not None:
                self._manual_recovery['products'].pop(key, None)
                self._manual_recovery['drafts'].pop(key, None)
            product = row['product']
            if self._loaded_status == 'all' or product.get('publication_status') == self._loaded_status:
                stored[key] = product
            else:
                stored.pop(key, None)
            self._selected.discard(key)
        if worker.action == 'update' and self._manual_recovery is not None:
            try:
                self._save_manual_recovery()
            except OSError:
                clear_error += ' No se pudo actualizar la copia local de la edición.'
        self._products = list(stored.values())
        self._must_reload = bool(worker.error and not worker.definite_rejection) or any(row['status_code'] == 409 for row in worker.result['failed'])
        self._update_filter_options()
        self._fill_table()
        if worker.created:
            self._post_load_notice = f"Creación confirmada · ID {worker.created['id']}. " + (
                'Guardado como borrador; revisa la ficha antes de publicarla. ' if worker.created['product'].get('publication_status') == 'draft'
                else 'Se han recuperado los datos actuales de ese producto. ') + clear_error
            self._set_feedback(self._post_load_notice, success=True)
        else:
            count, failed = len(rows), len(worker.result['failed'])
            details = '\n'.join(f"ID {row['id']}: {row['message']}" for row in worker.result['failed'][:6])
            message = f'{count} producto(s) guardados · {failed} con incidencias.'
            if worker.action == 'unpublish' and count:
                message += ' Pasaron a Borradores: ' + '; '.join(f"ID {r['id']} · {r['product'].get('title', '')}" for r in rows[:4]) + '. Puedes volver a publicarlos.'
            warnings = [warning for r in rows for warning in r.get('warnings', [])]
            if warnings:
                message += ' ' + ' '.join(warnings)
            if worker.error:
                message += ' ' + worker.error
                if worker.action == 'create':
                    message += (' Usa Recuperar creación para corregir los datos conservados.' if worker.definite_rejection else
                                ' Recarga y usa Recuperar creación para comprobar la misma solicitud.')
            if worker.action == 'update' and (failed or worker.error):
                message += ' Tu edición local se conserva y se recuperará al abrir la ficha de nuevo.'
            self._set_feedback(message + clear_error + ('\n' + details if details else ''),
                               error=bool(failed or worker.error), success=not (failed or worker.error), warning=bool(warnings))
        worker.deleteLater()
        self._update_actions()
        if worker.created:
            with QSignalBlocker(self._publication_filter):
                self._publication_filter.setCurrentIndex(self._publication_filter.findData(
                    worker.created['product'].get('publication_status') if worker.created['product'].get('publication_status') in ('publish', 'draft') else 'all'))
            self._load_inventory()

    def _save_proposals(self, *, keys=None, fields=None):
        if self._busy or self._must_reload:
            return
        keys = self._proposal_keys() if keys is None else keys
        stored = {self._key(p): p for p in self._products}
        rows = {key: {'product': stored[key], 'changes': dict(self._drafts[key]['changes'])}
                for key in keys if key in self._drafts}
        if fields is not None:
            for row in rows.values():
                row['changes'] = {field: value for field, value in row['changes'].items() if field in fields}
            rows = {key: row for key, row in rows.items() if row['changes']}
        if not rows:
            return
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
