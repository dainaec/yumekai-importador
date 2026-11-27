"""Save only a user's manual completion choice, without reviewing product data."""
from PySide6.QtCore import QThread

from yumekai_importer.diagnostics import logger


class ManualCompletionWorker(QThread):
    def __init__(self, api, isbns, complete, parent=None):
        super().__init__(parent)
        self._api = api
        self.isbns = tuple(isbns)
        self.complete = complete
        self.result = None
        self.error = None

    def run(self):
        try:
            self.result = self._api.set_manual_completion(self.isbns, self.complete)
        except Exception as error:
            logger.exception("pending.manual_completion_failed")
            self.error = str(error)
