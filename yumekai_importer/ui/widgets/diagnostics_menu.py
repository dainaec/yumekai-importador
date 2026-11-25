"""Support actions available both from home and from review tools."""
from PySide6.QtCore import QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import QFileDialog, QMessageBox

from yumekai_importer.diagnostics import export_diagnostics, log_directory, logger


def add_diagnostics_actions(menu, parent):
    menu.addSeparator()

    def open_folder():
        try:
            folder = log_directory()
            folder.mkdir(parents=True, exist_ok=True)
            if not QDesktopServices.openUrl(QUrl.fromLocalFile(str(folder))):
                raise OSError(f"No se pudo abrir {folder}")
            logger.info("diagnostics.open_folder")
        except OSError as error:
            logger.exception("diagnostics.open_failed")
            QMessageBox.warning(parent, "Registros", str(error))

    def export():
        path, _ = QFileDialog.getSaveFileName(parent, "Guardar diagnóstico", "yumekai-diagnostico.zip", "ZIP (*.zip)")
        if not path:
            return
        try:
            export_diagnostics(path)
            QMessageBox.information(parent, "Diagnóstico guardado", "Puedes enviar este ZIP para revisar lo sucedido.")
        except OSError as error:
            logger.exception("diagnostics.export_failed")
            QMessageBox.warning(parent, "No se pudo guardar", str(error))

    menu.addAction("Abrir carpeta de registros").triggered.connect(open_folder)
    menu.addAction("Exportar diagnóstico…").triggered.connect(export)
