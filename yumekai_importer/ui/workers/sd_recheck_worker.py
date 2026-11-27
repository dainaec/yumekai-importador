from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
from threading import Event

from PySide6.QtCore import QThread, Signal

from yumekai_importer.importers.sd.lookup import SdLookupCancelled, SdLookupResult, lookup_sd_isbn
from yumekai_importer.catalog.suppliers import supplier_block_reason
from yumekai_importer.diagnostics import logger


class SdRecheckWorker(QThread):
    progress = Signal(int, int)
    MAX_WORKERS = 4

    def __init__(self, products: dict[str, dict], parent=None, *, stock_only=False):
        super().__init__(parent)
        self.products = {key: dict(value) for key, value in products.items()}
        self.stock_only = stock_only
        self.stop_requested = Event()
        self.results = {}
        self.error = None

    def run(self):
        blocked = supplier_block_reason(self.products, "sd")
        if blocked:
            self.error = blocked
            self.results = {key: SdLookupResult(str(product.get("isbn") or ""), "blocked", message=blocked)
                            for key, product in self.products.items()}
            logger.warning("supplier.sd.blocked products=%s reason=%s", len(self.products), blocked)
            return
        logger.info("supplier.sd.start products=%s stock_only=%s", len(self.products), self.stock_only)
        remaining = iter(self.products.items())
        self.progress.emit(0, len(self.products))
        try:
            with ThreadPoolExecutor(max_workers=self.MAX_WORKERS) as executor:
                pending = {}
                while True:
                    while len(pending) < self.MAX_WORKERS and not self.stop_requested.is_set():
                        entry = next(remaining, None)
                        if entry is None:
                            break
                        key, product = entry
                        pending[executor.submit(
                            lookup_sd_isbn,
                            str(product.get("isbn") or ""),
                            self.stop_requested,
                            title=str(product.get("title") or ""),
                            stock_only=self.stock_only,
                        )] = key
                    if not pending:
                        break
                    done, _ = wait(pending, timeout=0.1, return_when=FIRST_COMPLETED)
                    for future in done:
                        key = pending.pop(future)
                        isbn = str(self.products[key].get('isbn') or '')
                        try:
                            self.results[key] = future.result()
                        except SdLookupCancelled:
                            self.results[key] = SdLookupResult(isbn, 'cancelled', message='Sin completar: consulta detenida.')
                        except Exception as error:
                            logger.exception("supplier.sd.error isbn=%s", isbn)
                            self.results[key] = SdLookupResult(isbn, 'error', message=str(error) or 'Error al consultar SD.')
                        self.progress.emit(len(self.results), len(self.products))
                        logger.info("supplier.sd.result isbn=%s status=%s", isbn, self.results[key].status)
        except Exception as error:
            logger.exception("supplier.sd.failed")
            self.error = str(error) or 'No se pudo completar la consulta SD.'
        for key, product in self.products.items():
            if key not in self.results:
                self.results[key] = SdLookupResult(str(product.get('isbn') or ''), 'cancelled',
                    message='Sin consultar: proceso detenido.' if self.stop_requested.is_set() else 'Sin consultar por un error.')
        logger.info("supplier.sd.finished products=%s cancelled=%s", len(self.results), self.stop_requested.is_set())
