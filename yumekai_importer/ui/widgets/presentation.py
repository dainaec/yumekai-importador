"""Shared visual roles for actions and review dialogs."""
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QDialogButtonBox, QLabel, QVBoxLayout


def button_role(button, role='secondary'):
    if role not in {'primary', 'secondary', 'soft', 'danger', 'quiet'}:
        raise ValueError('Unknown button role: ' + role)
    if button.property('variant') != role:
        button.setProperty('variant', role)
        button.style().unpolish(button)
        button.style().polish(button)
        button.update()
    button.setCursor(Qt.CursorShape.PointingHandCursor)
    return button


def style_button_box(box):
    for button in box.buttons():
        role = box.buttonRole(button)
        button_role(button, 'primary' if role in (QDialogButtonBox.ButtonRole.AcceptRole,
                    QDialogButtonBox.ButtonRole.YesRole) else 'danger' if role == QDialogButtonBox.ButtonRole.DestructiveRole
                    else 'quiet' if role in (QDialogButtonBox.ButtonRole.ResetRole, QDialogButtonBox.ButtonRole.HelpRole)
                    else 'secondary')


def review_dialog_layout(dialog):
    dialog.setProperty('reviewDialog', True)
    layout = QVBoxLayout(dialog)
    layout.setContentsMargins(22, 20, 22, 18)
    layout.setSpacing(14)
    title = QLabel(dialog.windowTitle())
    title.setObjectName('dialogTitle')
    title.setTextFormat(Qt.TextFormat.PlainText)
    title.setWordWrap(True)
    layout.addWidget(title)
    return layout


def install_dialog_presentation(app):
    """Include file dialogs and message boxes in the same action hierarchy."""
    from PySide6.QtCore import QEvent, QObject
    from PySide6.QtWidgets import QDialog, QMessageBox

    class DialogPresentation(QObject):
        def eventFilter(self, watched, event):
            if event.type() == QEvent.Type.Show and isinstance(watched, QDialog):
                for box in watched.findChildren(QDialogButtonBox):
                    style_button_box(box)
                if isinstance(watched, QMessageBox):
                    translations = {
                        QMessageBox.StandardButton.Yes: 'Sí', QMessageBox.StandardButton.No: 'No',
                        QMessageBox.StandardButton.Ok: 'Aceptar', QMessageBox.StandardButton.Cancel: 'Cancelar',
                        QMessageBox.StandardButton.Close: 'Cerrar', QMessageBox.StandardButton.Discard: 'Descartar',
                    }
                    for button in watched.buttons():
                        standard = watched.standardButton(button)
                        if standard in translations:
                            button.setText(translations[standard])
                        role = watched.buttonRole(button).name
                        button_role(button, 'danger' if role == 'DestructiveRole' else
                                    'primary' if role in ('AcceptRole', 'YesRole') else 'secondary')
            return False

    if not hasattr(app, '_yumekai_dialog_presentation'):
        app._yumekai_dialog_presentation = DialogPresentation(app)
        app.installEventFilter(app._yumekai_dialog_presentation)
