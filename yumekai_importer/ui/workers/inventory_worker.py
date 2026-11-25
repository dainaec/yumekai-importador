from yumekai_importer.diagnostics import logger
from PySide6.QtCore import QObject, QThread

from yumekai_importer.storage.catalog_api import CatalogApi


class InventoryWorker(QThread):
    def __init__(
        self,
        api: CatalogApi,
        *,
        sync: bool = False,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)

        self._api = api
        self.sync = sync

        self.products: list[dict[str, object]] | None = None
        self.sync_result: dict[str, object] | None = None
        self.error: str | None = None

    def run(self) -> None:
        try:
            if self.sync:
                self.sync_result = self._api.sync_store()

            self.products = self._api.list_inventory_products()

        except Exception as error:
            logger.exception("worker.failed name=inventory_worker")
            self.error = str(error)
