"""Application-owned light palette, independent of the operating system theme."""

from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QPalette


def apply_light_theme(app) -> None:
    app.setStyle("Fusion")
    hints = app.styleHints()
    if hasattr(hints, "setColorScheme"):
        hints.setColorScheme(Qt.ColorScheme.Light)

    palette = QPalette()
    colors = {
        "Window": "#FFFFFF", "WindowText": "#201A22", "Base": "#FFFFFF",
        "AlternateBase": "#F7F5F8", "Text": "#201A22", "Button": "#F7F5F8",
        "ButtonText": "#201A22", "BrightText": "#FFFFFF", "Highlight": "#ECD7E8",
        "HighlightedText": "#201A22", "ToolTipBase": "#FFFFFF", "ToolTipText": "#201A22",
        "PlaceholderText": "#695D6E", "Link": "#3568B0", "LinkVisited": "#6B4AA5",
        "Light": "#FFFFFF", "Midlight": "#ECE7ED", "Mid": "#CDC5D0",
        "Dark": "#A1849D", "Shadow": "#645866", "Accent": "#896B84",
    }
    for name, color in colors.items():
        role = getattr(QPalette.ColorRole, name, None)
        if role is not None:
            palette.setColor(QPalette.ColorGroup.All, role, QColor(color))
    for name in ("WindowText", "Text", "ButtonText", "PlaceholderText"):
        palette.setColor(QPalette.ColorGroup.Disabled, getattr(QPalette.ColorRole, name), QColor("#807584"))
    palette.setColor(QPalette.ColorGroup.Disabled, QPalette.ColorRole.Base, QColor("#F3F0F4"))
    palette.setColor(QPalette.ColorGroup.Disabled, QPalette.ColorRole.Button, QColor("#F4F2F4"))
    app.setPalette(palette)

    directory = Path(__file__).resolve().parent
    stylesheet = (directory / "yumekai.qss").read_text(encoding="utf-8")
    stylesheet = stylesheet.replace("@THEME_ICON_DIR@", (directory / "icons").as_posix())
    app.setStyleSheet(stylesheet)
    from yumekai_importer.ui.widgets.presentation import install_dialog_presentation
    install_dialog_presentation(app)




    from yumekai_importer.ui.styles.theme_switcher import theme_manager
    theme_manager(app)