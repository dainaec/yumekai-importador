"""Collect Norma credentials inside the application, never in catalogue data."""
from PySide6.QtWidgets import (
    QCheckBox, QDialog, QDialogButtonBox, QFormLayout, QLabel, QLineEdit,
)

from yumekai_importer.importers.norma.zonalibros import NormaCredentials
from yumekai_importer.ui.widgets.presentation import review_dialog_layout, style_button_box


class NormaAccessDialog(QDialog):
    def __init__(self, credentials=None, parent=None, *, remember=False):
        super().__init__(parent)
        self.setWindowTitle("Acceso a Norma ZonaLibros")
        self.setMinimumWidth(440)
        self.credentials = None
        self.remember = False
        layout = review_dialog_layout(self)
        message = QLabel("Introduce el acceso que utilizas en norma.zonalibros.com. "
                         "Se usará para consultar las fichas que marques.")
        message.setWordWrap(True)
        layout.addWidget(message)
        form = QFormLayout()
        self.tax_id = QLineEdit(credentials.tax_id if credentials else "")
        self.username = QLineEdit(credentials.username if credentials else "")
        self.password = QLineEdit(credentials.password if credentials else "")
        self.password.setEchoMode(QLineEdit.EchoMode.Password)
        for label, editor in (("NIF / CIF", self.tax_id), ("Usuario", self.username),
                              ("Contraseña", self.password)):
            editor.setAccessibleName(label + " de Norma ZonaLibros")
            form.addRow(label, editor)
        layout.addLayout(form)
        self.remember_check = QCheckBox("Recordar acceso en este equipo")
        self.remember_check.setChecked(remember)
        self.remember_check.setToolTip("Se guardará en el almacén de credenciales del sistema después de confirmar el acceso.")
        layout.addWidget(self.remember_check)
        self.error = QLabel()
        self.error.setWordWrap(True)
        self.error.hide()
        layout.addWidget(self.error)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.button(QDialogButtonBox.StandardButton.Ok).setText("Usar este acceso")
        buttons.button(QDialogButtonBox.StandardButton.Cancel).setText("Cancelar")
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        style_button_box(buttons)
        layout.addWidget(buttons)

    def accept(self):
        if not all((self.tax_id.text().strip(), self.username.text().strip(), self.password.text())):
            self.error.setText("Completa el NIF/CIF, usuario y contraseña de Norma.")
            self.error.show()
            return
        self.credentials = NormaCredentials(self.tax_id.text().strip(), self.username.text().strip(), self.password.text())
        self.remember = self.remember_check.isChecked()
        super().accept()
