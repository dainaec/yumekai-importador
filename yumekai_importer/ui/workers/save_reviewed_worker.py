import requests
from PySide6.QtCore import QThread


class SaveReviewedWorker(QThread):
    def __init__(
        self,
        base_url: str,
        credentials: tuple[str, str],
        updates: list[dict[str, object]],
        parent=None,
    ) -> None:
        super().__init__(parent)
        self._url = f"{base_url.rstrip('/')}/save_reviewed.php"
        self._credentials = credentials
        self._updates = updates
        self.saved: dict[str, dict[str, object]] = {}
        self.error: str | None = None

    def run(self) -> None:
        try:
            response = requests.post(
                self._url,
                auth=self._credentials,
                json={"products": self._updates},
                timeout=(5, 60),
            )
            if response.status_code == 401:
                raise ValueError("Comprueba el usuario y la contraseña de Hostalia.")
            if response.status_code == 404:
                raise ValueError("Falta subir save_reviewed.php a importer-api en Hostalia.")
            if not response.ok:
                try:
                    body = response.json()
                except ValueError:
                    body = {}
                message = body.get("message") if isinstance(body, dict) else None
                raise ValueError(message or f"Hostalia devolvió HTTP {response.status_code}.")

            body = response.json()
            rows = body.get("saved") if isinstance(body, dict) else None
            if not isinstance(rows, list):
                raise ValueError("La respuesta de guardado de Hostalia está incompleta.")

            expected = {
                entry["original_isbn"]: entry["changes"].get("isbn", entry["original_isbn"])
                for entry in self._updates
            }
            saved = {}
            for row in rows:
                if not isinstance(row, dict) or not isinstance(row.get("original_isbn"), str):
                    raise ValueError("Hostalia devolvió un resultado de guardado inesperado.")
                original = row["original_isbn"]
                product = row.get("product")
                if (
                    not isinstance(product, dict)
                    or original not in expected
                    or product.get("isbn") != expected[original]
                    or product.get("sku") != f"YMK-{expected[original]}"
                    or product.get("review_status") != "ready_to_upload"
                    or original in saved
                ):
                    raise ValueError("Hostalia devolvió un resultado de guardado inesperado.")
                saved[original] = product

            if saved.keys() != expected.keys():
                raise ValueError("La respuesta de guardado de Hostalia está incompleta.")
            self.saved = saved

        except requests.exceptions.RequestException:
            self.error = "Se interrumpió la conexión. Recarga las fichas para comprobar el resultado."
        except (TypeError, ValueError) as error:
            self.error = str(error)
