from PySide6.QtCore import QObject, QThread

from yumekai_importer.storage.catalog_api import CatalogApi


class LoadPendingWorker(QThread):
    def __init__(self, api: CatalogApi, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._api = api
        self.products_by_status: dict[str, list[dict[str, object]]] = {}
        self.error: str | None = None

    def run(self) -> None:
        try:
            self.products_by_status = {
                "pending_review": self._api.list_products("pending_review"),
                "ready_to_upload": self._api.list_products("ready_to_upload"),
            }
        except Exception as error:
            self.error = str(error)