from threading import Event
from time import perf_counter

from PySide6.QtCore import QThread, Signal
from yumekai_importer.storage.catalog_api import CatalogRequestError, StoreLoadCancelled
from yumekai_importer.diagnostics import logger


class StoreLoadWorker(QThread):
    progress = Signal(int, int)

    def __init__(self, api, parent=None, *, sync=False, status="publish"):
        super().__init__(parent)
        self.api = api
        self.sync = sync
        self.status = status
        self.stop_requested = Event()
        self.cancelled = False
        self.options = {}
        self.metrics = {}
        self.elapsed = 0.0
        self.products = None
        self.sync_result = None
        self.error = None

    def run(self):
        started = perf_counter()
        try:
            if self.sync:
                self.sync_result = self.api.sync_store()
            products = self.api.list_store_products(progress=self.progress.emit, status=self.status,
                                                    cancel_event=self.stop_requested)
            if self.stop_requested.is_set():
                raise StoreLoadCancelled()
            self.products = products
            self.options = self.api.store_options
            self.metrics = self.api.last_load_metrics
        except StoreLoadCancelled:
            self.cancelled = True
            logger.info("store.load_cancelled")
        except Exception as error:
            logger.exception("store.load_failed sync=%s", self.sync)
            self.error = str(error)
        finally:
            self.elapsed = perf_counter() - started


class StoreSaveWorker(QThread):
    BATCH_SIZE = 20
    def __init__(self, api, entries, parent=None):
        super().__init__(parent)
        self.api, self.entries = api, entries
        self.result = {'saved': [], 'failed': []}
        self.error = None

    def _send(self, entries):
        try:
            result = self.api.update_store_products(entries)
        except CatalogRequestError as error:
            if error.status_code not in (400, 409, 422):
                raise
            if len(entries) > 1:
                middle = len(entries) // 2
                self._send(entries[:middle])
                self._send(entries[middle:])
                return
            self.result['failed'].append({'id': entries[0]['id'], 'message': str(error), 'status_code': error.status_code})
            return
        self.result['saved'].extend(result['saved'])
        self.result['failed'].extend(result['failed'])
        if any(failure['status_code'] >= 500 for failure in result['failed']):
            raise ValueError('El envío se detuvo tras un resultado sin confirmar. Recarga antes de reintentar.')

    def run(self):
        try:
            for offset in range(0, len(self.entries), self.BATCH_SIZE):
                self._send(self.entries[offset:offset + self.BATCH_SIZE])
        except Exception as error:
            logger.exception("store.save_failed products=%s", len(self.entries))
            self.error = str(error)


class StoreCatalogWorker(QThread):
    """Catalog operations use a separate endpoint from the validated SD save flow."""
    def __init__(self, api, action, *, entries=None, fields=None, request_id=None, parent=None):
        super().__init__(parent)
        self.api, self.action = api, action
        self.entries, self.fields, self.request_id = entries or [], fields, request_id
        self.result = {'saved': [], 'failed': []}
        self.created = None
        self.error = None
        self.definite_rejection = False

    def run(self):
        try:
            if self.action == 'create':
                self.created = self.api.create_store_product(self.fields, self.request_id)
            else:
                for offset in range(0, len(self.entries), 20):
                    result = self.api.store_catalog_action(self.action, self.entries[offset:offset + 20])
                    self.result['saved'].extend(result['saved'])
                    self.result['failed'].extend(result['failed'])
                    if any(row['status_code'] >= 500 for row in result['failed']):
                        raise ValueError('La operación se detuvo. Recarga antes de volver a enviarla.')
        except Exception as error:
            self.error = str(error)
            self.definite_rejection = isinstance(error, CatalogRequestError) and error.status_code in (400, 409, 422)
            logger.exception('store.catalog_failed action=%s', self.action)
