import requests
import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from threading import local
from time import perf_counter
from urllib.parse import urlsplit
from uuid import uuid4

from yumekai_importer.catalog.product import Product
from yumekai_importer.catalog.classification import canonical_demographic
from yumekai_importer.diagnostics import logger, register_secret
from yumekai_importer.version import APP_VERSION


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
    STORE_PAGE_WORKERS = 3

    def __init__(self, base_url: str, username: str, password: str):
        self._products_url = f"{base_url.rstrip('/')}/products.php"
        self._create_product_url = f"{base_url.rstrip('/')}/create_product.php"
        self._review_url = f"{base_url.rstrip('/')}/review_products.php"
        self._sync_store_url = f"{base_url.rstrip('/')}/sync_store.php"
        self._store_review_url = f"{base_url.rstrip('/')}/store_review.php"
        self._inventory_products_url = (
            f"{base_url.rstrip('/')}/inventory_products.php"
        )
        self._auth = (username, password)
        self._sessions = local()
        register_secret(password)

    def _request(self, method, url, **kwargs):
        session = getattr(self._sessions, 'http', None)
        if session is None:
            session = self._sessions.http = requests.Session()
            session.headers['X-Yumekai-Version'] = APP_VERSION
        endpoint = urlsplit(url).path.rsplit('/', 1)[-1]
        payload = kwargs.get('json', {})
        if isinstance(payload, dict) and 'products' in payload:
            logger.info('api.operation endpoint=%s action=%s products=%s', endpoint,
                        payload.get('action', 'save'), len(payload['products']))
        request_id = uuid4().hex[:16]
        kwargs['headers'] = {**kwargs.get('headers', {}), 'X-Yumekai-Request-Id': request_id}
        started = perf_counter()
        logger.info('api.request id=%s method=%s endpoint=%s', request_id, method, endpoint)
        try:
            response = session.request(method, url, **kwargs)
        except requests.exceptions.RequestException:
            logger.exception('api.connection_failed method=%s endpoint=%s elapsed=%.2fs',
                             method, endpoint, perf_counter() - started)
            raise
        logger.log(40 if not response.ok else 20, 'api.response id=%s method=%s endpoint=%s status=%s elapsed=%.2fs',
                   request_id, method, endpoint, response.status_code, perf_counter() - started)
        return response

    def list_pending_products(self) -> list[dict[str, object]]:
        return self.list_products("pending_review")

    def list_products(self, review_status: str) -> list[dict[str, object]]:
        response = self._request('GET',
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
        for product in products:
            logger.info('catalog.review_requested action=%s isbn=%s fields=%s', action,
                        product.get('original_isbn'), sorted(product.get('changes', {})))
        try:
            response = self._request('POST',
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

    def create_products(self, products: list[Product], *, approved_exceptions=frozenset()) -> dict[str, int]:
        if not products:
            return {"created": 0, "duplicates": 0}

        payloads = []
        for product in products:
            payload = _product_payload(product)
            if product.isbn in approved_exceptions:
                payload["exceptions_confirmed"] = True
            payloads.append(payload)
        response = self._request('POST',
            self._create_product_url,
            json={"products": payloads},
            auth=self._auth,
            timeout=(5, 60),
        )
        self._check_response(response, "create_product.php")

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

    def list_inventory_products(self) -> list[dict[str, object]]:
        response = self._request('GET',
            self._inventory_products_url,
            auth=self._auth,
            timeout=(5, 60),
        )

        self._check_response(response, "inventory_products.php")

        products = response.json()

        if (
            not isinstance(products, list)
            or any(
                not isinstance(product, dict)
                or type(product.get("woocommerce_id")) is not int
                or product["woocommerce_id"] < 1
                for product in products
            )
        ):
            raise ValueError(
                "La API no devolvió un listado válido del inventario."
            )

        return products

    @staticmethod
    def _valid_store_product(product):
        return (isinstance(product, dict) and type(product.get('woocommerce_id')) is int
                and product['woocommerce_id'] > 0 and product.get('review_status') == 'in_store'
                and isinstance(product.get('_store_revision'), str)
                and re.fullmatch('[0-9a-f]{64}', product['_store_revision']) is not None)

    def list_store_products(self, *, progress=None):
        started = perf_counter()

        def read_page(page):
            response = self._request('GET', self._store_review_url, params={'page': page}, auth=self._auth, timeout=(5, 60))
            self._check_response(response, 'store_review.php')
            body = response.json()
            if (not isinstance(body, dict) or type(body.get('page')) is not int or body['page'] != page
                    or type(body.get('pages')) is not int or not 0 <= body['pages'] <= 10000
                    or type(body.get('total')) is not int or body['total'] < 0
                    or not isinstance(body.get('products'), list)):
                raise ValueError('La API no devolvió una página válida de WooCommerce.')
            return body

        first = read_page(1)
        pages = {1: first}
        if progress:
            progress(len(first['products']), first['total'])
        if first['pages'] > 1:
            with ThreadPoolExecutor(max_workers=self.STORE_PAGE_WORKERS) as executor:
                jobs = {executor.submit(read_page, page): page for page in range(2, first['pages'] + 1)}
                completed = len(first['products'])
                try:
                    for job in as_completed(jobs):
                        body = job.result()
                        if body['total'] != first['total'] or body['pages'] != first['pages']:
                            raise ValueError('El catálogo cambió durante la lectura. Recarga para obtener una lista completa.')
                        pages[body['page']] = body
                        completed += len(body['products'])
                        if progress:
                            progress(completed, first['total'])
                except Exception:
                    for job in jobs:
                        job.cancel()
                    raise
        products, seen = [], set()
        for page in sorted(pages):
            body = pages[page]
            for product in body['products']:
                if not self._valid_store_product(product) or product['woocommerce_id'] in seen:
                    raise ValueError('El listado de WooCommerce cambió o contiene fichas inesperadas. Recarga para comprobarlo.')
                seen.add(product['woocommerce_id'])
                products.append(product)
            if not body['products'] and first['total']:
                raise ValueError('El listado de WooCommerce quedó incompleto. Recarga para comprobarlo.')
        if len(products) != first['total']:
            raise ValueError('El listado de WooCommerce quedó incompleto. Se conserva el listado anterior; recarga para comprobarlo.')
        logger.info('store.loaded products=%s pages=%s elapsed=%.2fs', len(products), len(pages), perf_counter() - started)
        return products

    def update_store_products(self, entries):
        if not entries or len(entries) > 100:
            raise ValueError('Selecciona entre 1 y 100 fichas por envío a la tienda.')
        for entry in entries:
            logger.info('store.update_requested id=%s fields=%s', entry['id'], sorted(entry.get('changes', {})))
        try:
            response = self._request('POST', self._store_review_url, auth=self._auth,
                                     json={'products': entries}, timeout=(5, 120))
        except requests.exceptions.RequestException as error:
            raise ValueError('Conexión interrumpida con WooCommerce. Las propuestas se conservan; '
                             'recarga para comprobar qué se guardó antes de reintentar.') from error
        self._check_response(response, 'store_review.php')
        body = response.json()
        expected = {entry['id'] for entry in entries}
        if (len(expected) != len(entries) or not isinstance(body, dict)
                or not isinstance(body.get('saved'), list) or not isinstance(body.get('failed'), list)):
            raise ValueError('No se pudo confirmar la actualización en tienda. Recarga antes de reintentar.')
        seen = set()
        for saved in body['saved']:
            if (not isinstance(saved, dict) or type(saved.get('id')) is not int or saved['id'] not in expected
                    or saved['id'] in seen or not self._valid_store_product(saved.get('product'))
                    or saved['product']['woocommerce_id'] != saved['id']):
                raise ValueError('Respuesta de actualización inesperada. Recarga la tienda para comprobarla.')
            seen.add(saved['id'])
        for failed in body['failed']:
            if (not isinstance(failed, dict) or type(failed.get('id')) is not int
                    or failed['id'] not in expected or failed['id'] in seen
                    or not isinstance(failed.get('message'), str) or type(failed.get('status_code')) is not int):
                raise ValueError('Respuesta de actualización incompleta. Recarga la tienda para comprobarla.')
            seen.add(failed['id'])
        if seen != expected:
            raise ValueError('Faltan resultados de WooCommerce. Recarga antes de reintentar.')
        return body

    def sync_store(self) -> dict[str, object]:
        try:
            response = self._request('POST',
                self._sync_store_url,
                json={"action": "sync"},
                auth=self._auth,
                timeout=(5, 120),
            )
        except requests.exceptions.RequestException as error:
            raise ValueError(
                "No se pudo confirmar la sincronización. Recarga las fichas "
                "para comprobar el resultado antes de reintentar."
            ) from error

        self._check_response(response, "sync_store.php")

        try:
            result = response.json()
        except ValueError as error:
            raise ValueError(
                "Respuesta inesperada. Recarga las fichas para comprobar el resultado."
            ) from error

        if isinstance(result, dict) and result.get('sync_version') != 2:
            raise ValueError('Actualiza sync_store.php y sus archivos de apoyo a Yumekai 0.2.0 para sincronizar las copias.')

        counters = (
            "store_isbns",
            "linked",
            "already_linked",
            "not_in_importer",
            "invalid_store_isbns",
            "conflicting_store_isbns",
        )

        if (
            not isinstance(result, dict)
            or any(
                type(result.get(key)) is not int or result[key] < 0
                for key in counters
            )
            or result["linked"]
            + result["already_linked"]
            + result["not_in_importer"] + result['conflicting_store_isbns'] != result["store_isbns"]
            or not isinstance(result.get("products"), list)
            or len(result["products"]) != result["linked"]
        ):
            raise ValueError(
                "Respuesta incompleta. Recarga las fichas para comprobar el resultado."
            )
        for field in ('updated', 'unchanged', 'missing', 'unpublished', 'conflicts', 'conflicting_store_isbns'):
            if type(result.get(field)) is not int or result[field] < 0:
                raise ValueError('La sincronización devolvió un recuento incompleto. Recarga antes de reintentar.')
        issues = result.get('issues')
        if not isinstance(issues, list) or any(not isinstance(issue, dict)
                or not isinstance(issue.get('isbn'), str) or type(issue.get('woocommerce_id')) is not int
                or not isinstance(issue.get('status'), str) or not isinstance(issue.get('message'), str)
                for issue in issues):
            raise ValueError('El resultado de sincronización está incompleto. Recarga antes de reintentar.')
        logger.info('store.sync_result counts=%s', {key: value for key, value in result.items()
                    if type(value) is int})
        for issue in issues:
            logger.warning('store.sync_issue id=%s isbn=%s status=%s message=%s', issue['woocommerce_id'],
                           issue['isbn'], issue['status'], issue['message'])
        return result
