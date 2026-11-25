from PySide6.QtCore import QThread, Signal
from yumekai_importer.storage.catalog_api import CatalogRequestError
from yumekai_importer.diagnostics import logger


class StoreLoadWorker(QThread):
    progress = Signal(int, int)

    def __init__(self, api, parent=None, *, sync=False):
        super().__init__(parent)
        self.api = api
        self.sync = sync
        self.products = None
        self.sync_result = None
        self.error = None

    def run(self):
        try:
            if self.sync:
                self.sync_result = self.api.sync_store()
            self.products = self.api.list_store_products(progress=self.progress.emit)
        except Exception as error:
            logger.exception("store.load_failed sync=%s", self.sync)
            self.error = str(error)


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
