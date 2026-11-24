import sys
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication

from yumekai_importer.ui.styles.theme import apply_light_theme
from yumekai_importer.ui.styles.application_icon import configure_windows_app_id, load_application_icon
from yumekai_importer.ui.windows.catalog_window import CatalogWindow

def main() -> int:
    configure_windows_app_id()
    QApplication.setAttribute(Qt.ApplicationAttribute.AA_DontUseNativeDialogs, True)
    app = QApplication(sys.argv)
    app.setApplicationName("Yumekai")
    icon = load_application_icon()
    if not icon.isNull():
        app.setWindowIcon(icon)
    apply_light_theme(app)
    window = CatalogWindow()
    window.showMaximized()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
