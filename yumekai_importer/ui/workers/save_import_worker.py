from PySide6.QtCore import QThread

from yumekai_importer.catalog.product import Product
from yumekai_importer.storage.catalog_api import CatalogApi


class SaveImportWorker(QThread):
    def __init__(self, api: CatalogApi, products: list[Product], parent=None):
        super().__init__(parent)
        self._api = api
        self._products = products
        self.result: dict[str, int] | None = None
        self.error: str | None = None

    def run(self) -> None:
        try:
            self.result = self._api.create_products(self._products)
        except Exception as error:
            self.error = str(error)