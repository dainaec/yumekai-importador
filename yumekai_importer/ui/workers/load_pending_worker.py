from collections import Counter

from PySide6.QtCore import QThread, Signal

from yumekai_importer.diagnostics import logger


class LoadPendingWorker(QThread):
    stage = Signal(str)

    def __init__(self, api, parent=None):
        super().__init__(parent)
        self._api = api
        self.products_by_status = {}
        self.error = None

    def run(self):
        try:
            self.stage.emit("Cargando las fichas del importador…")
            self.products_by_status = {
                status: self._api.list_products(status)
                for status in ("pending_review", "ready_to_upload")
            }
        except Exception as error:
            logger.exception("pending.load_failed")
            self.error = str(error)


class StoreLinkWorker(QThread):
    stage = Signal(str)

    def __init__(self, api, isbns, parent=None):
        super().__init__(parent)
        self._api = api
        self._isbns = tuple(isbns)
        self.confirmed = []
        self.conflicts = []
        self.error = None

    def run(self):
        try:
            if not self._isbns:
                return

            self.stage.emit("Consultando los ISBN e ID de WooCommerce…")
            by_isbn, by_id = {}, {}

            for row in self._api.list_store_identifiers():
                isbn = row["isbn"]
                identity = row["woocommerce_id"]
                by_isbn.setdefault(isbn, set()).add(identity)
                by_id.setdefault(identity, set()).add(isbn)

            counts = Counter(self._isbns)
            pairs = []

            for isbn in sorted(counts):
                matches = by_isbn.get(isbn, set())

                if not matches:
                    continue

                if counts[isbn] > 1 or len(matches) != 1:
                    self.conflicts.append(isbn)
                    continue

                identity = next(iter(matches))

                if len(by_id[identity]) != 1:
                    self.conflicts.append(isbn)
                    continue

                pairs.append({
                    "isbn": isbn,
                    "woocommerce_id": identity,
                })

            for offset in range(0, len(pairs), 5000):
                self.stage.emit(
                    f"Guardando vínculos: {offset} de {len(pairs)} confirmados…"
                )
                result = self._api.sync_store(pairs[offset:offset + 5000])
                self.confirmed.extend(result["products"])

        except Exception as error:
            logger.exception("pending.manual_link_failed")
            self.error = str(error)