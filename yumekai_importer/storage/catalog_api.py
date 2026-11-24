import requests

from yumekai_importer.catalog.product import Product
from yumekai_importer.catalog.classification import canonical_demographic


class CatalogRequestError(ValueError):
    def __init__(self, message: str, status_code: int):
        super().__init__(message)
        self.status_code = status_code


def _product_payload(product: Product) -> dict[str, object]:
    price = product.retail_price
    work_type = (product.work_type or "").strip()
    demographic = canonical_demographic(product.demographic) or ""
    categories = list(product.categories)

    if work_type:
        categories.append(work_type)
        if work_type.casefold() == "manga" and demographic:
            categories.append(f"{work_type} > {demographic}")

    return {
        "isbn": product.isbn,
        "title": product.title,
        "retail_price": f"{price:.2f}" if price is not None else None,
        "author": product.author,
        "description": product.description,
        "categories": list(dict.fromkeys(categories)),
        "image_url": product.image_url,
        "publisher": product.publisher,
        "series": product.series,
        "volume": product.volume,
        "language": product.language,
        "book_format": product.book_format,
        "pages": product.pages,
        "work_type": work_type or None,
        "demographic": demographic or None,
        "yumekai_status": (
            product.yumekai_status.value
            if product.yumekai_status is not None
            else None
        ),
    }

class CatalogApi:
    def __init__(self, base_url: str, username: str, password: str):
        self._products_url = f"{base_url.rstrip('/')}/products.php"
        self._create_product_url = f"{base_url.rstrip('/')}/create_product.php"
        self._review_url = f"{base_url.rstrip('/')}/review_products.php"
        self._auth = (username, password)

    def list_pending_products(self) -> list[dict[str, object]]:
        return self.list_products("pending_review")

    def list_products(self, review_status: str) -> list[dict[str, object]]:
        response = requests.get(
            self._products_url,
            params={"review_status": review_status},
            auth=self._auth,
            timeout=(5, 60),
        )
        self._check_response(response, "products.php")

        rows = response.json()
        if not isinstance(rows, list) or any(not isinstance(row, dict) for row in rows):
            raise ValueError("La API no devolvió un listado de fichas.")

        return rows

    @staticmethod
    def _check_response(response, endpoint: str) -> None:
        if response.status_code == 401:
            raise ValueError("Comprueba el usuario y la contraseña de Hostalia.")
        if response.status_code == 404:
            raise ValueError(f"Falta subir {endpoint} a importer-api en Hostalia.")
        if not response.ok:
            try:
                body = response.json()
            except ValueError:
                body = {}
            message = body.get("message") if isinstance(body, dict) else None
            raise CatalogRequestError(message or f"Hostalia devolvió HTTP {response.status_code}.",
                                      response.status_code)

    def review_products(self, action: str, products: list[dict]) -> dict:
        if action not in {"save", "ready", "pending", "delete"} or not products:
            raise ValueError("Selecciona fichas y una acción válida.")
        try:
            response = requests.post(
                self._review_url, auth=self._auth,
                json={"action": action, "products": products}, timeout=(5, 60),
            )
        except requests.exceptions.RequestException as error:
            raise ValueError("Se interrumpió la conexión. Los cambios locales se conservan. "
                             "Recarga las fichas para comprobar el resultado antes de reintentar.") from error
        self._check_response(response, "review_products.php")
        body = response.json()
        expected = {entry["original_isbn"]: entry for entry in products}
        if not isinstance(body, dict) or len(expected) != len(products):
            raise ValueError("Respuesta de guardado inesperada. Recarga para comprobar el resultado.")
        if action == "delete":
            deleted = body.get("deleted")
            if (not isinstance(deleted, list) or any(not isinstance(key, str) for key in deleted)
                    or len(deleted) != len(expected) or set(deleted) != set(expected)):
                raise ValueError("No se pudo confirmar el borrado. Recarga para comprobar el resultado.")
            return body
        saved = body.get("saved")
        if not isinstance(saved, list):
            raise ValueError("Respuesta incompleta. Recarga para comprobar el resultado.")
        seen = set()
        for entry in saved:
            if not isinstance(entry, dict) or not isinstance(entry.get("original_isbn"), str):
                raise ValueError("Respuesta inesperada. Recarga para comprobar el resultado.")
            original = entry["original_isbn"]
            product = entry.get("product")
            if original not in expected or original in seen or not isinstance(product, dict):
                raise ValueError("Respuesta inesperada. Recarga para comprobar el resultado.")
            request = expected[original]
            isbn = request.get("changes", {}).get("isbn", original)
            target = ("ready_to_upload" if action == "ready" or
                      (action == "save" and request.get("ready_to_upload")) else "pending_review")
            if (product.get("isbn") != isbn or product.get("review_status") != target
                    or (target == "ready_to_upload" and product.get("sku") != f"YMK-{isbn}")):
                raise ValueError("Respuesta inesperada. Recarga para comprobar el resultado.")
            seen.add(original)
        if seen != set(expected):
            raise ValueError("Respuesta incompleta. Recarga para comprobar el resultado.")
        return body

    def create_products(self, products: list[Product]) -> dict[str, int]:
        if not products:
            return {"created": 0, "duplicates": 0}

        response = requests.post(
            self._create_product_url,
            json={"products": [_product_payload(product) for product in products]},
            auth=self._auth,
            timeout=(5, 60),
        )
        response.raise_for_status()

        counts = response.json()
        if not isinstance(counts, dict):
            raise ValueError("Hostalia no devolvió un resumen de guardado.")

        created = counts.get("created")
        duplicates = counts.get("duplicates")
        if (
            type(created) is not int
            or type(duplicates) is not int
            or created < 0
            or duplicates < 0
            or created + duplicates != len(products)
        ):
            raise ValueError("Hostalia devolvió un recuento de guardado inesperado.")

        return {"created": created, "duplicates": duplicates}
