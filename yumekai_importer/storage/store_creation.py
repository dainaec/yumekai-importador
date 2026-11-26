"""Persist one pending creation token before contacting WooCommerce."""
import json
import os
import re
from pathlib import Path
from tempfile import NamedTemporaryFile

from PySide6.QtCore import QStandardPaths


class PendingStoreCreation:
    def __init__(self, path=None):
        self.path = Path(path) if path is not None else Path(
            QStandardPaths.writableLocation(QStandardPaths.StandardLocation.AppLocalDataLocation)
        ) / 'store-creation.json'

    def load(self):
        if not self.path.exists():
            return None
        data = json.loads(self.path.read_text(encoding='utf-8'))
        if (not isinstance(data, dict) or not isinstance(data.get('fields'), dict)
                or not re.fullmatch('[0-9a-f]{32}', data.get('request_id', ''))):
            raise ValueError('La creación pendiente no se puede leer. Revisa store-creation.json en la carpeta de datos.')
        return data

    def save(self, data):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = None
        try:
            with NamedTemporaryFile(dir=self.path.parent, prefix='.create-', delete=False) as stream:
                temporary = Path(stream.name)
                stream.write(json.dumps(data, ensure_ascii=False, allow_nan=False).encode('utf-8'))
            os.replace(temporary, self.path)
        finally:
            if temporary is not None:
                temporary.unlink(missing_ok=True)

    def clear(self):
        self.path.unlink(missing_ok=True)
