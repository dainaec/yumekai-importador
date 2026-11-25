from yumekai_importer.diagnostics import logger
from PySide6.QtCore import QThread

from yumekai_importer.catalog.product import Product
from yumekai_importer.storage.catalog_api import CatalogApi


class SaveImportWorker(QThread):
    def __init__(self, api: CatalogApi, products: list[Product], parent=None, *, approved_exceptions=frozenset()):
        super().__init__(parent)
        self._api = api
        self._products = products
        self._approved_exceptions = frozenset(approved_exceptions)
        self.skipped_exceptions = 0
        self.result: dict[str, int] | None = None
        self.error: str | None = None

    def run(self) -> None:
        try:
            kwargs = {"approved_exceptions": self._approved_exceptions} if self._approved_exceptions else {}
            self.result = self._api.create_products(self._products, **kwargs)
        except Exception as error:
            logger.exception("worker.failed name=save_import_worker")
            self.error = str(error)
