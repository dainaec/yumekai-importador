"""Static application assets, resolved relative to the package."""
from pathlib import Path
import sys

from PySide6.QtGui import QIcon


def assets_directory() -> Path:
    return Path(__file__).resolve().parents[2] / "assets"


def configure_windows_app_id() -> None:
    if sys.platform != "win32":
        return
    try:
        import ctypes
        set_app_id = ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID
        set_app_id.argtypes = [ctypes.c_wchar_p]
        set_app_id.restype = ctypes.c_long
        set_app_id("Yumekai.Catalogo.Importador")
    except (AttributeError, OSError):
        pass  # The window icon still works if Windows grouping is unavailable.



def load_application_icon() -> QIcon:
    return QIcon(str(assets_directory() / "app-icon.png"))
