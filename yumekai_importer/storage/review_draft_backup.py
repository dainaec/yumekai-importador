"""Local recovery copy of a review, including its original concurrency tokens."""
import json
import os
from pathlib import Path
from tempfile import NamedTemporaryFile

from PySide6.QtCore import QStandardPaths


class ReviewDraftBackup:
    def __init__(self, path=None):
        self.path = Path(path) if path is not None else Path(
            QStandardPaths.writableLocation(QStandardPaths.StandardLocation.AppLocalDataLocation)
        ) / "review-recovery.json"

    def exists(self):
        return self.path.is_file()

    def save(self, products, drafts, sd_results):
        data = {"version": 1, "products": products, "drafts": drafts, "sd_results": sd_results}
        content = json.dumps(data, ensure_ascii=False, allow_nan=False).encode("utf-8")
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = None
        try:
            with NamedTemporaryFile(dir=self.path.parent, prefix=".review-", delete=False) as stream:
                temporary = Path(stream.name)
                stream.write(content)
            os.replace(temporary, self.path)
        finally:
            if temporary is not None:
                temporary.unlink(missing_ok=True)

    def load(self):
        if not self.exists():
            return None
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
            if (not isinstance(data, dict) or data.get("version") != 1
                    or not all(isinstance(data.get(field), dict) for field in ("products", "drafts", "sd_results"))):
                raise ValueError
            for key, draft in data["drafts"].items():
                product = data["products"].get(key)
                if (not isinstance(product, dict) or product.get("isbn") != key
                        or product.get("review_status") not in ("pending_review", "ready_to_upload")
                        or not isinstance(draft, dict) or not isinstance(draft.get("changes"), dict)
                        or not isinstance(draft.get("ready_to_upload"), bool)):
                    raise ValueError
            return data
        except (ValueError, TypeError, KeyError) as error:
            raise ValueError("La copia local de revisión no tiene un formato válido.") from error

    def clear(self):
        self.path.unlink(missing_ok=True)
