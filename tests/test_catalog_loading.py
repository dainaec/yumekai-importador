from threading import Barrier
from unittest.mock import Mock
import pytest

from yumekai_importer.storage.catalog_api import CatalogApi
from yumekai_importer.ui.workers.store_workers import StoreLoadWorker, StoreSaveWorker


def page(number, total=4, *, ids=None, pages=4):
    rows = ids if ids is not None else [number]
    return {"page": number, "pages": pages, "total": total,
            "products": [{"woocommerce_id": identity, "review_status": "in_store", "_store_revision": "a" * 64}
                         for identity in rows]}


def response(body):
    return SimpleResponse(body)


class SimpleResponse:
    status_code = 200
    ok = True
    def __init__(self, body):
        self.body = body
    def json(self):
        return self.body


def test_pages_read_concurrently_and_return_in_order():
    api = CatalogApi("https://example.test", "test", "fake-password")
    barrier = Barrier(3)
    requests = []

    def request(_method, _url, *, params, **kwargs):
        number = params["page"]
        requests.append(number)
        if number > 1:
            barrier.wait(timeout=5)
        return response(page(number))

    api._request = request
    progress = []
    result = api.list_store_products(progress=lambda done, total: progress.append((done, total)))
    assert [row["woocommerce_id"] for row in result] == [1, 2, 3, 4]
    assert sorted(requests) == [1, 2, 3, 4]
    assert progress[-1] == (4, 4)


@pytest.mark.parametrize("broken", [
    page(2, total=5), page(2, ids=[1]), page(2, ids=[]), page(2, pages=3),
])
def test_catalog_change_or_missing_page_is_rejected(broken):
    api = CatalogApi("https://example.test", "test", "fake-password")
    api._request = lambda *a, params, **k: response(broken if params["page"] == 2 else page(params["page"]))
    with pytest.raises(ValueError):
        api.list_store_products()


def test_empty_store_is_valid():
    api = CatalogApi("https://example.test", "test", "fake-password")
    api._request = lambda *a, **k: response(page(1, total=0, ids=[], pages=0))
    assert api.list_store_products() == []


def test_worker_keeps_sync_receipt_if_read_fails(app):
    api = Mock()
    api.sync_store.return_value = {"linked": 1}
    api.list_store_products.side_effect = ValueError("Lectura interrumpida")
    worker = StoreLoadWorker(api, sync=True)
    worker.run()
    assert worker.sync_result == {"linked": 1}
    assert worker.products is None
    assert "interrumpida" in worker.error


def test_ambiguous_write_stops_following_batches(app):
    api = Mock()
    api.update_store_products.side_effect = ValueError("Sin respuesta")
    worker = StoreSaveWorker(api, [{"id": n} for n in range(45)])
    worker.run()
    api.update_store_products.assert_called_once()
    assert worker.error == "Sin respuesta"


def test_unconfirmed_server_result_stops_following_batches(app):
    api = Mock()
    api.update_store_products.return_value = {"saved": [], "failed": [{"id": 1, "message": "Sin confirmar", "status_code": 500}]}
    worker = StoreSaveWorker(api, [{"id": n} for n in range(45)])
    worker.run()
    api.update_store_products.assert_called_once()
    assert worker.error


def sync_result():
    return {'sync_version': 2, 'store_isbns': 1, 'linked': 0, 'already_linked': 1,
            'not_in_importer': 0, 'invalid_store_isbns': 0, 'conflicting_store_isbns': 0,
            'updated': 1, 'unchanged': 0, 'missing': 0, 'unpublished': 0, 'conflicts': 0,
            'products': [], 'issues': []}


def test_sync_receipt_is_validated():
    api = CatalogApi('https://example.test', 'test', 'fake-password')
    api._request = lambda *a, **k: response(sync_result())
    assert api.sync_store()['updated'] == 1


@pytest.mark.parametrize('changes', [
    {'updated': -1}, {'linked': 3}, {'conflicting_store_isbns': 'uno'},
    {'issues': [{'isbn': 'a', 'status': 'deleted'}]}, {'products': None},
])
def test_malformed_sync_receipt_cannot_be_reported_as_success(changes):
    api = CatalogApi('https://example.test', 'test', 'fake-password')
    api._request = lambda *a, **k: response({**sync_result(), **changes})
    with pytest.raises(ValueError):
        api.sync_store()


def test_old_sync_endpoint_prompts_upload_of_updated_files():
    api = CatalogApi('https://example.test', 'test', 'fake-password')
    body = sync_result()
    body.pop('sync_version')
    api._request = lambda *a, **k: response(body)
    with pytest.raises(ValueError, match='Actualiza sync_store.php'):
        api.sync_store()
