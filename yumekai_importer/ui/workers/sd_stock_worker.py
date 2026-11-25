from yumekai_importer.diagnostics import logger
from threading import Event
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait

from PySide6.QtCore import QThread, Signal
from yumekai_importer.importers.sd.details import SdDetails, read_sd_details
from yumekai_importer.importers.sd.stock import read_sd_stock_batches


class SdStockWorker(QThread):
    stock_progress = Signal(str, int, int, int)
    detail_progress = Signal(int, int)
    DETAIL_WORKERS = 4

    def __init__(
        self,
        references: dict[str, str],
        parent=None,
        *,
        detail_isbns: set[str] | None = None,
    ) -> None:
        super().__init__(parent)
        self._references = references.copy()
        self.requested_isbns = set(references)
        self._detail_isbns = set(detail_isbns or ())
        self.stop_requested = Event()
        self.result: dict[str, bool] = {}
        self.statuses: dict[str, str] = {}
        self.details: dict[str, SdDetails] = {}
        self.error: str | None = None

    def run(self) -> None:
        urls: dict[str, str] = {}
        try:
            self.result, errors = read_sd_stock_batches(
                self._references,
                detail_urls=urls,
                stop_requested=self.stop_requested,
                progress=self.stock_progress.emit,
            )
        except Exception as error:
            logger.exception("worker.failed name=sd_stock_worker")
            self.error = str(error) or "No se pudo consultar SD."
            return

        self.statuses = {isbn: "yk_on_demand" if available else "outofstock"
                         for isbn, available in self.result.items()}
        # A negative list flag can hide a future release marked "Consultar disponibilidad".
        # Read its product page/date even when all the other data is already complete.
        articles = [(isbn, url) for isbn, url in urls.items()
                    if isbn in self._detail_isbns or self.result.get(isbn) is not True]
        failed = 0
        first_error = None

        completed = 0
        remaining = iter(articles)
        self.detail_progress.emit(0, len(articles))
        with ThreadPoolExecutor(max_workers=self.DETAIL_WORKERS) as executor:
            pending = {}
            while True:
                # Bound in-flight work, including when the user presses Stop.
                while len(pending) < self.DETAIL_WORKERS and not self.stop_requested.is_set():
                    article = next(remaining, None)
                    if article is None:
                        break
                    isbn, url = article
                    pending[executor.submit(read_sd_details, url, isbn)] = isbn
                if not pending:
                    break
                done, _ = wait(pending, timeout=0.1, return_when=FIRST_COMPLETED)
                for future in done:
                    isbn = pending.pop(future)
                    try:
                        details = future.result()
                        self.details[isbn] = details
                        if details.stock_info is not None and details.stock_info.kind is not None:
                            status = details.stock_info.yumekai_status
                            if status is not None:
                                self.statuses[isbn] = status
                            else:
                                self.statuses.pop(isbn, None)
                            if details.stock_info.available is not None:
                                self.result[isbn] = details.stock_info.available
                            else:
                                self.result.pop(isbn, None)
                    except Exception as error:
                        logger.exception("worker.failed name=sd_stock_worker")
                        if self.result.get(isbn) is not True:
                            self.statuses.pop(isbn, None)
                        failed += 1
                        if first_error is None:
                            first_error = f"{isbn}: {error}"
                    completed += 1
                    self.detail_progress.emit(completed, len(articles))

        if first_error is not None:
            errors.append(f"Fichas con error: {failed}. Primer aviso: {first_error}")

        self.error = "\n".join(errors) or None
