import os
from pathlib import Path
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PySide6.QtWidgets import QApplication
from yumekai_importer.ui.styles.application_icon import load_application_icon


class ApplicationIconTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_static_icon_loads_independently_of_the_current_directory(self):
        original = Path.cwd()
        try:
            os.chdir(original.parent)
            self.assertFalse(load_application_icon().pixmap(32, 32).isNull())
        finally:
            os.chdir(original)
