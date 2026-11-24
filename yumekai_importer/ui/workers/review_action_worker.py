from PySide6.QtCore import QThread


class ReviewActionWorker(QThread):
    def __init__(self, api, action: str, products: list[dict], parent=None):
        super().__init__(parent)
        self._api = api
        self.action = action
        self.products = products
        self.result = None
        self.error = None

    def run(self):
        try:
            self.result = self._api.review_products(self.action, self.products)
        except Exception as error:
            self.error = str(error)
