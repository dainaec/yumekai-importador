"""Rotating local diagnostics, with credentials removed before writing."""
import logging
from logging.handlers import RotatingFileHandler
import platform
import re
import sys
import threading
from pathlib import Path
from uuid import uuid4
from zipfile import ZipFile, ZIP_DEFLATED

from PySide6.QtCore import QStandardPaths
from yumekai_importer.version import APP_VERSION

logger = logging.getLogger("yumekai")
_secrets = set()
_lock = threading.RLock()
_log_path = None


def register_secret(value):
    if value:
        from urllib.parse import quote
        with _lock:
            _secrets.update((str(value), quote(str(value), safe="")))


def redact(text):
    with _lock:
        for secret in sorted(_secrets, key=len, reverse=True):
            text = text.replace(secret, "[OCULTO]")
    text = re.sub(r"(?i)(https?://)[^\s/@:]+:[^\s/@]+@", r"\1[OCULTO]@", text)
    text = re.sub(r"(?i)(authorization\s*[:=]\s*)(?:basic|bearer)\s+\S+", r"\1[OCULTO]", text)
    text = re.sub(r'''(?i)((?:password|passwd|contraseña|token|consumer_secret|api_key)["']?\s*[:=]\s*)["']?[^\s,;"']+''',
                  r"\1[OCULTO]", text)
    return text


class RedactingFormatter(logging.Formatter):
    def format(self, record):
        return redact(super().format(record))


def log_directory():
    return Path(QStandardPaths.writableLocation(
        QStandardPaths.StandardLocation.AppLocalDataLocation)) / "logs"


def configure_logging(directory=None):
    global _log_path
    if any(isinstance(handler, RotatingFileHandler) for handler in logger.handlers):
        return _log_path
    folder = Path(directory) if directory is not None else log_directory()
    folder.mkdir(parents=True, exist_ok=True)
    _log_path = folder / "yumekai.log"
    handler = RotatingFileHandler(_log_path, maxBytes=2 * 1024 * 1024, backupCount=5,
                                  encoding="utf-8", delay=False)
    handler.setFormatter(RedactingFormatter("%(asctime)s %(levelname)s [%(threadName)s] %(message)s",
                                            datefmt="%Y-%m-%dT%H:%M:%S%z"))
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)
    logger.propagate = False
    logger.info("application.start version=%s python=%s os=%s session=%s",
                APP_VERSION, platform.python_version(), platform.system(), uuid4().hex[:12])
    return _log_path


def install_exception_hooks():
    original = sys.excepthook

    def unhandled(kind, value, traceback):
        if not issubclass(kind, KeyboardInterrupt):
            logger.critical("application.unhandled_exception", exc_info=(kind, value, traceback))
        original(kind, value, traceback)

    sys.excepthook = unhandled

    def thread_error(args):
        logger.critical("thread.unhandled_exception", exc_info=(args.exc_type, args.exc_value, args.exc_traceback))

    threading.excepthook = thread_error


def export_diagnostics(destination):
    for handler in logger.handlers:
        handler.flush()
    folder = _log_path.parent if _log_path is not None else log_directory()
    with ZipFile(destination, "w", ZIP_DEFLATED) as archive:
        archive.writestr("version.txt", f"Yumekai {APP_VERSION}\nPython {platform.python_version()}\n{platform.system()}\n")
        for path in sorted(folder.glob("yumekai.log*")):
            if path.is_file():
                archive.writestr(path.name, redact(path.read_text(encoding="utf-8", errors="replace")))
    logger.info("diagnostics.exported")
