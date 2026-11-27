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


class StoreLoadCancelled(Exception):
    pass


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
    STORE_PAGE_WORKERS = 2
    STORE_PAGE_SIZE = 200

    def __init__(self, base_url: str, username: str, password: str):
        self._products_url = f"{base_url.rstrip('/')}/products.php"
        self._create_product_url = f"{base_url.rstrip('/')}/create_product.php"
        self._review_url = f"{base_url.rstrip('/')}/review_products.php"
        self._manual_completion_url = f"{base_url.rstrip('/')}/manual_completion.php"
        self._sync_store_url = f"{base_url.rstrip('/')}/sync_store.php"
        self._store_catalog_url = f"{base_url.rstrip('/')}/store_catalog.php"
        self._store_products_url = f"{base_url.rstrip('/')}/store_products.php"
        self.store_options = {}
        self.last_load_metrics = {}
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

    def list_store_identifiers(self) -> list[dict]:
        try:
            response = self._request(
                "GET", self._store_products_url,
                auth=self._auth, timeout=(5, 60),
            )
        except requests.exceptions.RequestException as error:
            raise ValueError(
                "No se pudieron consultar los identificadores de WooCommerce."
            ) from error

        self._check_response(response, "store_products.php")

        try:
            rows = response.json()
        except ValueError as error:
            raise ValueError(
                "La consulta de identificadores no devolvió JSON válido."
            ) from error

        if not isinstance(rows, list) or any(
            not isinstance(row, dict)
            or not isinstance(row.get("isbn"), str)
            or not row["isbn"].strip()
            or type(row.get("woocommerce_id")) is not int
            or row["woocommerce_id"] < 1
            for row in rows
        ):
            raise ValueError(
                "La API no devolvió un listado válido de ISBN e ID."
            )

        return [
            {
                "isbn": row["isbn"],
                "woocommerce_id": row["woocommerce_id"],
            }
            for row in rows
        ]

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

    def list_manual_completion(self):
        response = self._request("GET", self._manual_completion_url, auth=self._auth, timeout=(5, 60))
        self._check_response(response, "manual_completion.php")
        body = response.json()
        isbns = body.get("complete_isbns") if isinstance(body, dict) else None
        if not isinstance(isbns, list) or any(not isinstance(isbn, str) or not isbn for isbn in isbns):
            raise ValueError("No se pudieron leer las marcas de ficha completa. Actualiza la lista.")
        return set(isbns)

    def set_manual_completion(self, isbns, complete):
        isbns = list(isbns)
        if type(complete) is not bool or not isbns or len(isbns) > 5000 or any(
            not isinstance(isbn, str) or not isbn for isbn in isbns
        ) or len(set(isbns)) != len(isbns):
            raise ValueError("Selecciona las fichas cuya marca quieres cambiar.")
        response = self._request("POST", self._manual_completion_url, auth=self._auth,
                                 json={"isbns": isbns, "complete": complete}, timeout=(5, 60))
        self._check_response(response, "manual_completion.php")
        body = response.json()
        received = body.get("isbns") if isinstance(body, dict) else None
        if (not isinstance(body, dict) or body.get("complete") is not complete
                or not isinstance(received, list) or any(not isinstance(isbn, str) for isbn in received)
                or len(received) != len(isbns) or set(received) != set(isbns)):
            raise ValueError("No se pudo confirmar la marca de ficha completa. Actualiza la lista para comprobarla.")
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

    def list_store_products(self, *, progress=None, status='publish', cancel_event=None):
        if status not in {'publish', 'draft', 'pending', 'private', 'all'}:
            raise ValueError('Filtro de publicación no válido.')
        started = perf_counter()

        def check_cancel():
            if cancel_event is not None and cancel_event.is_set():
                raise StoreLoadCancelled()

        def read_page(page):
            check_cancel()
            response = self._request('GET', self._store_catalog_url,
                                     params={'page': page, 'per_page': self.STORE_PAGE_SIZE, 'status': status},
                                     auth=self._auth, timeout=(5, 35))
            check_cancel()
            self._check_response(response, 'store_catalog.php')
            body = response.json()
            if not isinstance(body, dict) or body.get('api_version') != 3:
                raise ValueError('Actualiza los PHP de importer-api a Yumekai 0.3.1 antes de consultar o editar la tienda.')
            if (not isinstance(body, dict) or type(body.get('page')) is not int or body['page'] != page
                    or type(body.get('pages')) is not int or not 0 <= body['pages'] <= 10000
                    or type(body.get('total')) is not int or body['total'] < 0
                    or body.get('status') != status or not isinstance(body.get('products'), list)):
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
                        check_cancel()
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
        check_cancel()
        products, seen = [], set()
        allowed = {'publish', 'draft', 'pending', 'private'} if status == 'all' else {status}
        for page in sorted(pages):
            body = pages[page]
            for product in body['products']:
                if (not self._valid_store_product(product) or product['woocommerce_id'] in seen
                        or product.get('publication_status') not in allowed):
                    raise ValueError('El listado de WooCommerce cambió o contiene fichas inesperadas. Recarga para comprobarlo.')
                seen.add(product['woocommerce_id'])
                products.append(product)
            if not body['products'] and first['total']:
                raise ValueError('El listado de WooCommerce quedó incompleto. Recarga para comprobarlo.')
        if len(products) != first['total']:
            raise ValueError('El listado de WooCommerce quedó incompleto. Se conserva el listado anterior; recarga para comprobarlo.')
        options = first.get('options')
        if not isinstance(options, dict) or not all(isinstance(options.get(key), kind) for key, kind in
                [('categories', list), ('stock_statuses', dict), ('tax_classes', list)]):
            raise ValueError('Faltan las categorías y los estados reales de la tienda. Actualiza store_catalog.php.')
        self.store_options = options
        self.last_load_metrics = {'elapsed': perf_counter() - started, 'pages': len(pages),
                                  'server': [page.get('timing', {}) for page in pages.values()]}
        logger.info('store.loaded products=%s pages=%s elapsed=%.2fs server=%s', len(products),
                    len(pages), self.last_load_metrics['elapsed'], self.last_load_metrics['server'])
        return products

    def create_store_product(self, fields, request_id):
        body = self._catalog_post({'action': 'create', 'fields': fields, 'request_id': request_id})
        if (not isinstance(body, dict) or body.get('request_id') != request_id
                or not self._valid_store_product(body.get('product'))
                or type(body.get('id')) is not int or body.get('id') != body['product']['woocommerce_id']):
            raise ValueError('No se pudo confirmar la creación. Comprueba el catálogo antes de crear otra ficha.')
        return body

    def store_catalog_action(self, action, entries):
        if action not in {'update', 'publish', 'unpublish'} or not 1 <= len(entries) <= 20:
            raise ValueError('Selecciona entre 1 y 20 productos y una acción válida.')
        body = self._catalog_post({'action': action, 'products': entries})
        body = self._validate_store_receipt(body, entries)
        expected_status = {'unpublish': 'draft', 'publish': 'publish'}.get(action)
        if expected_status and any(row['product'].get('publication_status') != expected_status for row in body['saved']):
            raise ValueError('No se pudo confirmar el estado de publicación. Recarga antes de reintentar.')
        return body

    def _catalog_post(self, payload):
        try:
            response = self._request('POST', self._store_catalog_url, auth=self._auth,
                                     json=payload, timeout=(5, 60))
        except requests.exceptions.RequestException as error:
            raise ValueError('Se interrumpió la conexión y no se puede confirmar el resultado. '
                             'Recarga la tienda antes de repetir la operación.') from error
        self._check_response(response, 'store_catalog.php')
        try:
            body = response.json()
        except ValueError as error:
            raise ValueError('Respuesta sin confirmar. Recarga para comprobar el resultado.') from error
        if not isinstance(body, dict) or body.get('api_version') != 3:
            raise ValueError('No se pudo confirmar la operación con la API actual. Actualiza los PHP a Yumekai 0.3.1 y comprueba el resultado antes de reintentar.')
        return body

    @classmethod
    def _validate_store_receipt(cls, body, entries):
        expected = {entry['id'] for entry in entries}
        if (len(expected) != len(entries) or not isinstance(body, dict)
                or not isinstance(body.get('saved'), list) or not isinstance(body.get('failed'), list)):
            raise ValueError('No se pudo confirmar la actualización en tienda. Recarga antes de reintentar.')
        seen = set()
        for saved in body['saved']:
            if (not isinstance(saved, dict) or type(saved.get('id')) is not int or saved['id'] not in expected
                    or saved['id'] in seen or not cls._valid_store_product(saved.get('product'))
                    or saved['product']['woocommerce_id'] != saved['id']):
                raise ValueError('Respuesta de actualización inesperada. Recarga la tienda para comprobarla.')
            warnings = saved.get('warnings', [])
            verification = saved.get('verification')
            if not isinstance(warnings, list) or any(not isinstance(warning, str) for warning in warnings):
                raise ValueError('El resultado de publicación contiene avisos incompletos. Actualiza la tienda para comprobarlo.')
            if verification is not None and (not isinstance(verification, dict)
                    or verification.get('database_status') != saved['product'].get('publication_status')):
                raise ValueError('La confirmación de publicación no coincide con los datos guardados. Actualiza la tienda.')
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

    def sync_store(self, products: list[dict]) -> dict:
        if not isinstance(products, list) or len(products) > 5000:
            raise ValueError("Envía una lista de hasta 5000 coincidencias.")

        expected, ids, entries = {}, set(), []

        for row in products:
            if (
                not isinstance(row, dict)
                or not isinstance(row.get("isbn"), str)
                or not row["isbn"].strip()
                or type(row.get("woocommerce_id")) is not int
                or row["woocommerce_id"] < 1
            ):
                raise ValueError(
                    "Hay un ISBN o ID no válido entre las coincidencias."
                )

            isbn = row["isbn"]
            identity = row["woocommerce_id"]

            if isbn in expected or identity in ids:
                raise ValueError(
                    "Hay ISBN o ID repetidos entre las coincidencias."
                )

            expected[isbn] = identity
            ids.add(identity)
            entries.append({
                "isbn": isbn,
                "woocommerce_id": identity,
            })

        if not entries:
            return {
                "sync_version": 3,
                "linked": 0,
                "already_linked": 0,
                "products": [],
            }

        try:
            response = self._request(
                "POST", self._sync_store_url,
                json={"action": "link", "products": entries},
                auth=self._auth, timeout=(5, 120),
            )
        except requests.exceptions.RequestException as error:
            raise ValueError(
                "No se pudo confirmar el guardado de los vínculos. "
                "Pulsa Actualizar lista antes de reintentar."
            ) from error

        self._check_response(response, "sync_store.php")

        invalid = (
            "La respuesta no confirma todos los vínculos. "
            "Pulsa Actualizar lista antes de reintentar."
        )

        try:
            result = response.json()
        except ValueError as error:
            raise ValueError(invalid) from error

        if (
            not isinstance(result, dict)
            or type(result.get("sync_version")) is not int
            or result["sync_version"] != 3
            or any(
                type(result.get(key)) is not int or result[key] < 0
                for key in ("linked", "already_linked")
            )
            or result["linked"] + result["already_linked"] != len(entries)
            or not isinstance(result.get("products"), list)
            or len(result["products"]) != len(entries)
        ):
            raise ValueError(invalid)

        confirmed = {}

        for row in result["products"]:
            if (
                not isinstance(row, dict)
                or not isinstance(row.get("isbn"), str)
                or row["isbn"] in confirmed
                or type(row.get("woocommerce_id")) is not int
                or expected.get(row["isbn"]) != row["woocommerce_id"]
            ):
                raise ValueError(invalid)

            confirmed[row["isbn"]] = row["woocommerce_id"]

        if confirmed != expected:
            raise ValueError(invalid)

        return result
