"""Application themes and a persistent, presentation-only theme switch."""

from pathlib import Path

from PySide6.QtCore import QObject, QSettings, QSignalBlocker, Qt, Signal, Slot
from PySide6.QtGui import QColor, QPalette
from PySide6.QtWidgets import QApplication, QPushButton

from yumekai_importer.ui.styles.theme_colors import theme_color, theme_stylesheet


_LIGHT_PALETTE = {
    "Window": "#FFFFFF", "WindowText": "#201A22", "Base": "#FFFFFF",
    "AlternateBase": "#F7F5F8", "Text": "#201A22", "Button": "#F7F5F8",
    "ButtonText": "#201A22", "BrightText": "#FFFFFF", "Highlight": "#ECD7E8",
    "HighlightedText": "#201A22", "ToolTipBase": "#FFFFFF", "ToolTipText": "#201A22",
    "PlaceholderText": "#695D6E", "Link": "#3568B0", "LinkVisited": "#6B4AA5",
    "Light": "#FFFFFF", "Midlight": "#ECE7ED", "Mid": "#CDC5D0",
    "Dark": "#A1849D", "Shadow": "#645866", "Accent": "#896B84",
}

_DARK_OVERRIDES = """
/* Yellow brand accents retain dark text in both themes. */
QPushButton[variant="primary"], QPushButton#homePrimaryAction,
QTabBar::tab:selected { color: #382B18; }
QPushButton[variant="primary"]:disabled { color: #968A9F; }
QPushButton#themeToggleButton:checked { background: #584058; border-color: #B99AB9; }
/* Keep the original logo legible without recolouring the artwork. */
QWidget#homeBrandLogo { background: #FFFFFF; border-radius: 12px; }

/* Fondo general igual al del inicio. */
QWidget#catalogWindow,
QWidget#importWindow,
QWidget#pendingReviewWindow,
QWidget#inventoryWindow,
QStackedWidget,
QTabWidget::pane,
QTabBar {
    background-color: #19151E;
}
"""


class _ThemeManager(QObject):
    changed = Signal(str)

    def __init__(self, app):
        super().__init__(app)
        self.app = app
        self.settings = QSettings("Yumekai", "Catalogo")
        saved = self.settings.value("appearance/theme", "light")
        self.current = saved if saved in ("light", "dark") else "light"
        self.app.setStyle("Fusion")

    def apply(self, mode, *, persist=True):
        if mode not in ("light", "dark"):
            raise ValueError("Unknown theme: " + str(mode))
        self.current = mode
        self.app.setProperty("yumekaiTheme", mode)
        hints = self.app.styleHints()
        if hasattr(hints, "setColorScheme"):
            hints.setColorScheme(Qt.ColorScheme.Dark if mode == "dark" else Qt.ColorScheme.Light)

        palette = QPalette()
        for name, color in _LIGHT_PALETTE.items():
            role = getattr(QPalette.ColorRole, name, None)
            if role is not None:
                value = QColor("#FFFFFF") if name == "BrightText" else theme_color(color)
                palette.setColor(QPalette.ColorGroup.All, role, value)
        for name in ("WindowText", "Text", "ButtonText", "PlaceholderText"):
            palette.setColor(QPalette.ColorGroup.Disabled, getattr(QPalette.ColorRole, name), theme_color("#807584"))
        palette.setColor(QPalette.ColorGroup.Disabled, QPalette.ColorRole.Base, theme_color("#F3F0F4"))
        palette.setColor(QPalette.ColorGroup.Disabled, QPalette.ColorRole.Button, theme_color("#F4F2F4"))
        self.app.setPalette(palette)

        directory = Path(__file__).resolve().parent
        stylesheet = (directory / "yumekai.qss").read_text(encoding="utf-8")
        stylesheet = theme_stylesheet(stylesheet)
        if mode == "dark":
            for name in ("check", "chevron-down", "chevron-up"):
                stylesheet = stylesheet.replace(f"/{name}.svg", f"/{name}-dark.svg")
            stylesheet += _DARK_OVERRIDES
        stylesheet = stylesheet.replace("@THEME_ICON_DIR@", (directory / "icons").as_posix())
        self.app.setStyleSheet(stylesheet)
        from yumekai_importer.ui.widgets.presentation import install_dialog_presentation
        install_dialog_presentation(self.app)
        if persist:
            self.settings.setValue("appearance/theme", mode)
            self.settings.sync()
        self.changed.emit(mode)


def theme_manager(app=None):
    app = app if app is not None else QApplication.instance()
    if app is None:
        raise RuntimeError("A QApplication is required before applying a theme")
    if not hasattr(app, "_yumekai_theme_manager"):
        manager = _ThemeManager(app)
        app._yumekai_theme_manager = manager
        manager.apply(manager.current, persist=False)
    return app._yumekai_theme_manager


def apply_light_theme(app) -> None:
    """Legacy startup entry point: restore the saved theme, defaulting to light.

    Kept so the existing application entry point needs no changes.
    """
    theme_manager(app)


class _ThemeStylesheet(QObject):
    def __init__(self, widget, stylesheet):
        super().__init__(widget)
        self.widget = widget
        self.stylesheet = stylesheet
        theme_manager().changed.connect(self.refresh)
        self.refresh()

    @Slot()
    @Slot(str)
    def refresh(self, _mode=None):
        self.widget.setStyleSheet(theme_stylesheet(self.stylesheet))


def set_theme_stylesheet(widget, stylesheet):
    """Refresh a widget's existing local stylesheet when the theme changes."""
    binding = getattr(widget, "_yumekai_theme_stylesheet", None)
    if binding is None:
        widget._yumekai_theme_stylesheet = _ThemeStylesheet(widget, stylesheet)
    else:
        binding.stylesheet = stylesheet
        binding.refresh()


class ThemeToggleButton(QPushButton):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("themeToggleButton")
        self.setCheckable(True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self._manager = theme_manager()
        self._manager.changed.connect(self._sync)
        self.clicked.connect(self._toggle)
        self._sync(self._manager.current)

    @Slot(bool)
    def _toggle(self, checked):
        self._manager.apply("dark" if checked else "light")

    @Slot(str)
    def _sync(self, mode):
        with QSignalBlocker(self):
            self.setChecked(mode == "dark")
        self.setText("Tema claro" if mode == "dark" else "Tema oscuro")
        self.setToolTip("Activar el tema claro" if mode == "dark" else "Activar el tema oscuro")
        self.setAccessibleName(self.toolTip())
