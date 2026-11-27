"""Cache public series metadata, separately from inventory and credentials."""
import json
import math
import os
from pathlib import Path
from tempfile import NamedTemporaryFile
import time


class MangaUpdatesCache:
    VERSION = 1
    MAX_ENTRIES = 5000

    def __init__(self, path=None):
        if path is None:
            from PySide6.QtCore import QStandardPaths
            path = Path(QStandardPaths.writableLocation(
                QStandardPaths.StandardLocation.AppLocalDataLocation)) / "mangaupdates-metadata.json"
        self.path = Path(path)
        self.entries = {}
        self.dirty = False
        self.warning = ""
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
            if payload.get("version") == self.VERSION and isinstance(payload.get("entries"), dict):
                self.entries = {key: entry for key, entry in payload["entries"].items()
                    if isinstance(entry, dict) and isinstance(entry.get("saved_at"), (int, float))
                    and math.isfinite(entry["saved_at"])}
        except FileNotFoundError:
            pass
        except (OSError, ValueError, TypeError, AttributeError):
            self.warning = "No se pudo leer la caché de clasificación; se consultará MangaUpdates cuando haga falta."

    def get(self, key, max_age):
        entry = self.entries.get(key)
        if not isinstance(entry, dict) or not isinstance(entry.get("saved_at"), (int, float)):
            return None
        age = time.time() - entry["saved_at"]
        return entry.get("value") if 0 <= age <= max_age else None

    def put(self, key, value):
        self.entries[key] = {"saved_at": time.time(), "value": value}
        self.dirty = True
        if len(self.entries) > self.MAX_ENTRIES:
            newest = sorted(self.entries, key=lambda item: self.entries[item].get("saved_at", 0), reverse=True)
            self.entries = {key: self.entries[key] for key in newest[:self.MAX_ENTRIES]}

    def flush(self):
        if not self.dirty:
            return
        temporary = None
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            content = json.dumps({"version": self.VERSION, "entries": self.entries},
                                 ensure_ascii=False, allow_nan=False)
            with NamedTemporaryFile(dir=self.path.parent, prefix=".mangaupdates-", delete=False,
                                    mode="w", encoding="utf-8") as stream:
                stream.write(content)
                temporary = Path(stream.name)
            os.replace(temporary, self.path)
            self.dirty = False
        except (OSError, ValueError, TypeError):
            self.warning = "No se pudo guardar la caché de MangaUpdates. Las propuestas de las fichas se conservan."
        finally:
            if temporary is not None:
                try:
                    temporary.unlink(missing_ok=True)
                except OSError:
                    pass
