from copy import deepcopy
from threading import Barrier, Event
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
import requests
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QDialog, QMessageBox

from yumekai_importer.storage.catalog_api import CatalogApi, StoreLoadCancelled
from yumekai_importer.storage.store_creation import PendingStoreCreation
from yumekai_importer.ui.widgets.store_product_dialog import StoreProductDialog
from yumekai_importer.ui.windows.store_review_window import StoreReviewWindow
from yumekai_importer.ui.workers.store_workers import StoreCatalogWorker, StoreLoadWorker


OPTIONS = {'categories': [
    {'id': 1, 'name': 'Manga', 'slug': 'manga', 'parent': 0},
    {'id': 20, 'name': 'Manwha/Manhua', 'slug': 'manwha-manhua', 'parent': 0},
    {'id': 30, 'name': 'Manwha', 'slug': 'manwha', 'parent': 20}],
    'stock_statuses': {'instock': 'Hay existencias', 'outofstock': 'Sin existencias', 'onbackorder': 'Se puede reservar'},
    'tax_classes': [{'slug': '', 'name': 'Estándar'}, {'slug': 'tasa-reducida', 'name': 'Tasa reducida'}]}


def row(identity=2532, status='publish'):
    return {'woocommerce_id': identity, 'title': 'TOWER OF GOD 01', 'isbn': '9788413349992',
            'review_status': 'in_store', '_store_revision': 'a' * 64, 'publication_status': status,
            'product_type': 'simple', 'retail_price': '15.00', 'sale_price': '14.25', 'sku': 'YMK-9788413349992',
            'work_type': 'Manhwa', 'categories': ['Manwha/Manhua', 'Manwha'], 'category_ids': [20, 30],
            'description': '<p>Sinopsis <strong>original</strong></p>', 'short_description': '<p>Corta</p>',
            'yumekai_status': 'outofstock', 'tax_class': 'tasa-reducida', 'is_featured': 0, 'pages': '288',
            'volume': '1', 'publisher': 'PANINI COMICS'}


class Response:
    status_code = 200
    ok = True
    def __init__(self, data):
        self.data = {'api_version': 3, **data} if isinstance(data, dict) else data
    def json(self):
        return self.data


def page(number=1, total=3, ids=None, pages=3, status='publish'):
    return {'page': number, 'total': total, 'pages': pages, 'status': status,
            'products': [row(i, 'draft' if status == 'draft' else 'publish') for i in (ids if ids is not None else [number])],
            'options': deepcopy(OPTIONS) if number == 1 else None, 'timing': {'bootstrap_ms': 500, 'query_ms': 20}}


def api():
    return CatalogApi('https://example.test/importer-api', 'test', 'test-password')


def test_pages_parallel_order_progress_and_metrics():
    client = api()
    barrier = Barrier(2)
    def read(method, url, params, **kwargs):
        assert method == 'GET' and url.endswith('/store_catalog.php')
        assert params['per_page'] == 200 and params['status'] == 'publish'
        assert kwargs['timeout'] == (5, 35)
        if params['page'] > 1:
            barrier.wait(timeout=5)
        return Response(page(params['page']))
    client._request = read
    progress = []
    assert [p['woocommerce_id'] for p in client.list_store_products(progress=lambda d, t: progress.append((d, t)))] == [1, 2, 3]
    assert progress[-1] == (3, 3)
    assert client.last_load_metrics['pages'] == 3 and client.last_load_metrics['elapsed'] >= 0
    assert client.store_options == OPTIONS


@pytest.mark.parametrize('broken', [page(2, total=4), page(2, ids=[1]), page(2, ids=[]), page(2, pages=2), page(2, status='draft')])
def test_partial_or_changed_catalog_is_never_returned(broken):
    client = api()
    client._request = lambda *a, params, **k: Response(broken if params['page'] == 2 else page(params['page']))
    with pytest.raises(ValueError):
        client.list_store_products()


def test_empty_catalog_and_drafts_filter():
    client = api()
    client._request = lambda *a, **k: Response(page(1, total=0, ids=[], pages=0, status='draft'))
    assert client.list_store_products(status='draft') == []


def test_cancel_prevents_request():
    client = api()
    client._request = Mock()
    stop = Event()
    stop.set()
    with pytest.raises(StoreLoadCancelled):
        client.list_store_products(cancel_event=stop)
    client._request.assert_not_called()


def test_cancel_during_first_page_discards_result():
    client, stop = api(), Event()
    def read(*a, **k):
        stop.set()
        return Response(page())
    client._request = read
    with pytest.raises(StoreLoadCancelled):
        client.list_store_products(cancel_event=stop)
    assert client.store_options == {}


def test_create_timeout_is_not_retried():
    client = api()
    client._request = Mock(side_effect=requests.Timeout('timeout'))
    with pytest.raises(ValueError, match='no se puede confirmar'):
        client.create_store_product({'title': 'Nuevo'}, 'b' * 32)
    assert client._request.call_count == 1


@pytest.mark.parametrize('body', [
    {'saved': [], 'failed': []},
    {'saved': [{'id': 2532, 'product': row(2533)}], 'failed': []},
    {'saved': [{'id': 2532, 'product': row()}], 'failed': [{'id': 2532, 'message': 'x', 'status_code': 409}]},
])
def test_catalog_receipts_require_every_id_once(body):
    client = api()
    client._request = Mock(return_value=Response(body))
    with pytest.raises(ValueError):
        client.store_catalog_action('unpublish', [{'id': 2532, 'expected_revision': 'a' * 64}])


def test_unpublish_receipt_contains_confirmed_draft():
    client = api()
    client._request = Mock(return_value=Response({'saved': [{'id': 2532, 'product': row(status='draft')}], 'failed': []}))
    result = client.store_catalog_action('unpublish', [{'id': 2532, 'expected_revision': 'a' * 64}])
    assert result['saved'][0]['product']['publication_status'] == 'draft'
    assert client._request.call_args.kwargs['json']['action'] == 'unpublish'


def test_ambiguous_catalog_batch_stops_following_batches(app):
    client = Mock()
    client.store_catalog_action.side_effect = ValueError('Sin confirmar')
    worker = StoreCatalogWorker(client, 'unpublish', entries=[{'id': n} for n in range(42)])
    worker.run()
    assert client.store_catalog_action.call_count == 1 and worker.error


def test_load_worker_cancelled_does_not_expose_partial_products(app):
    client = Mock()
    client.list_store_products.side_effect = StoreLoadCancelled()
    worker = StoreLoadWorker(client)
    worker.run()
    assert worker.cancelled and worker.products is None and worker.error is None
    assert worker.elapsed >= 0


def test_manual_edit_omits_unmodified_fields_and_preserves_html(app):
    original = row()
    dialog = StoreProductDialog(original, OPTIONS)
    dialog.editors['title'].setText('Nuevo título')
    dialog.accept()
    assert dialog.result() == QDialog.DialogCode.Accepted
    assert dialog.changes == {'title': 'Nuevo título'}
    assert original['description'] == '<p>Sinopsis <strong>original</strong></p>'


def test_manual_prices_independent_and_clear_discount(app):
    dialog = StoreProductDialog(row(), OPTIONS)
    dialog.editors['retail_price'].setText('20,00')
    assert dialog.editors['sale_price'].text() == '14,25'
    dialog.editors['sale_price'].clear()
    dialog.accept()
    assert dialog.changes == {'retail_price': '20.00', 'sale_price': None}


@pytest.mark.parametrize('field,value', [('retail_price', 'abc'), ('pages', '0'), ('volume', '5-1'), ('sale_price', '99,00')])
def test_editor_rejects_invalid_numbers(app, field, value):
    dialog = StoreProductDialog(row(), OPTIONS)
    dialog.editors[field].setText(value)
    dialog.accept()
    assert dialog.result() != QDialog.DialogCode.Accepted and dialog.error.text()


def test_new_product_requires_explicit_tax_and_is_a_draft_form(app):
    dialog = StoreProductDialog(None, OPTIONS)
    dialog.editors['title'].setText('Producto nuevo')
    dialog.editors['isbn'].setText('9788413349992')
    assert dialog.editors['sku'].text() == 'YMK-9788413349992'
    dialog.accept()
    assert 'impuesto' in dialog.error.text()
    dialog.editors['tax_class'].setCurrentIndex(dialog.editors['tax_class'].findData('tasa-reducida'))
    dialog.accept()
    assert dialog.result() == QDialog.DialogCode.Accepted
    assert dialog.changes['yumekai_status'] == 'outofstock'
    assert 'publication_status' not in dialog.changes


def test_categories_send_real_term_ids(app):
    dialog = StoreProductDialog(row(), OPTIONS)
    dialog._category_items[20].setCheckState(0, Qt.CheckState.Unchecked)
    dialog._category_items[30].setCheckState(0, Qt.CheckState.Unchecked)
    dialog._category_items[1].setCheckState(0, Qt.CheckState.Checked)
    dialog.accept()
    assert dialog.changes == {'category_ids': [1]}


def test_pending_creation_survives_restart_with_same_token(tmp_path):
    path = tmp_path / 'creation.json'
    pending = {'request_id': 'a' * 32, 'fields': {'title': 'Nuevo'}}
    PendingStoreCreation(path).save(pending)
    assert PendingStoreCreation(path).load() == pending
    PendingStoreCreation(path).clear()
    assert PendingStoreCreation(path).load() is None


def store_window():
    window = StoreReviewWindow()
    window._products = [row()]
    window._store_options = OPTIONS
    window._loaded = True
    window._fill_table()
    return window


def test_table_shows_woo_values_while_sd_proposals_stay_separate(app):
    window = store_window()
    window._drafts = {'2532': {'changes': {'title': 'Propuesta', 'work_type': 'Manga'}, 'ready_to_upload': False}}
    window._fill_table()
    assert window._table.item(0, 1).text() == 'TOWER OF GOD 01'
    assert window._current_products()[0]['work_type'] == 'Manhwa'
    assert window._table.item(0, 2).text() == 'Publicado'
    assert window._table.item(0, 3).text() == '2532'


def test_failed_load_keeps_old_data_and_restores_filter(app):
    window = store_window()
    with __import__('PySide6.QtCore', fromlist=['QSignalBlocker']).QSignalBlocker(window._publication_filter):
        window._publication_filter.setCurrentIndex(1)
    before = deepcopy(window._products)
    window._worker = SimpleNamespace(products=None, sync_result=None, cancelled=False, error='Timeout', deleteLater=lambda: None)
    window._finish_load_store()
    assert window._products == before and window._publication_filter.currentData() == 'publish'
    assert 'Timeout' in window._feedback.text()


def test_unpublish_removes_only_successful_rows_from_published_view(app):
    window = store_window()
    window._products.append(row(2534))
    window._action_worker = SimpleNamespace(action='unpublish', created=None, error=None, definite_rejection=False,
        result={'saved': [{'id': 2532, 'product': row(status='draft')}],
                'failed': [{'id': 2534, 'message': 'Otra edición', 'status_code': 409}]}, deleteLater=lambda: None)
    window._finish_catalog_action()
    assert [p['woocommerce_id'] for p in window._products] == [2534]
    assert 'Borradores' in window._feedback.text() and '2534' in window._feedback.text()
    assert window._must_reload


def test_sd_controls_disabled_for_drafts(app):
    window = store_window()
    window._products = [row(status='draft')]
    window._selected = {'2532'}
    window._update_actions()
    assert not window._full_action.isEnabled() and window._publish.isEnabled()


def test_create_confirmation_loads_drafts_without_relabeling_partial_catalog(app, tmp_path):
    window = store_window()
    window._creation_backup = PendingStoreCreation(tmp_path / 'create.json')
    window._creation_backup.save({'fields': {'title': 'Nuevo'}, 'request_id': 'a' * 32})
    window._load_inventory = Mock()
    window._action_worker = SimpleNamespace(action='create', created={'id': 2533, 'product': row(2533, 'draft')},
        error=None, definite_rejection=False, result={'saved': [], 'failed': []}, deleteLater=lambda: None)
    window._finish_catalog_action()
    assert window._loaded_status == 'publish' and window._publication_filter.currentData() == 'draft'
    assert window._products == [row()]
    assert not window._creation_backup.path.exists()
    window._load_inventory.assert_called_once()
    assert '2533' in window._post_load_notice


def test_manual_recovery_prefills_changes_against_actual_new_snapshot(app):
    original = row()
    original['title'] = 'Título cambiado en WooCommerce'
    dialog = StoreProductDialog(original, OPTIONS, recovered_changes={'description': '<p>Mi texto sin confirmar</p>'})
    dialog.accept()
    assert dialog.changes == {'description': '<p>Mi texto sin confirmar</p>'}
    assert dialog.product['title'] == 'Título cambiado en WooCommerce'


def test_manual_edit_backup_retained_on_rejection_and_cleared_on_success(app, tmp_path):
    from yumekai_importer.storage.review_draft_backup import ReviewDraftBackup
    window = store_window()
    window._manual_backup = ReviewDraftBackup(tmp_path / 'edit.json')
    window._load_manual_recovery()
    window._manual_recovery['products']['2532'] = row()
    window._manual_recovery['drafts']['2532'] = {'changes': {'description': 'Texto pendiente'}, 'ready_to_upload': False}
    window._save_manual_recovery()
    window._action_worker = SimpleNamespace(action='update', created=None, error=None, definite_rejection=False,
        result={'saved': [], 'failed': [{'id': 2532, 'status_code': 409, 'message': 'Conflicto'}]}, deleteLater=lambda: None)
    window._finish_catalog_action()
    assert window._manual_backup.load()['drafts']['2532']['changes'] == {'description': 'Texto pendiente'}
    assert 'se conserva' in window._feedback.text()
    updated = {**row(), 'description': 'Texto pendiente', '_store_revision': 'b' * 64}
    window._action_worker = SimpleNamespace(action='update', created=None, error=None, definite_rejection=False,
        result={'saved': [{'id': 2532, 'product': updated}], 'failed': []}, deleteLater=lambda: None)
    window._finish_catalog_action()
    assert not window._manual_backup.exists()
    assert window._products[0]['description'] == 'Texto pendiente'


def test_rejected_creation_retains_fields_for_correction(app, tmp_path):
    window = store_window()
    window._creation_backup = PendingStoreCreation(tmp_path / 'create.json')
    fields = {'title': 'Mi producto', 'sku': 'SKU-repetido', 'description': '<p>Texto largo</p>'}
    window._action_worker = SimpleNamespace(action='create', created=None, error='SKU repetido', definite_rejection=True,
        fields=fields, request_id='a' * 32, result={'saved': [], 'failed': []}, deleteLater=lambda: None)
    window._finish_catalog_action()
    recovered = window._creation_backup.load()
    assert recovered['rejected'] and recovered['fields'] == fields
    assert not window._must_reload


def test_recovered_edit_can_be_discarded_explicitly(app):
    dialog = StoreProductDialog(row(), OPTIONS, recovered_changes={'description': 'Texto sin guardar'})
    dialog._discard_recovered()
    assert dialog.discard_recovered and dialog.result() == QDialog.DialogCode.Rejected


def test_new_desktop_rejects_old_server_before_enabling_store_management():
    client = api()
    client._request = Mock(return_value=Response({**page(), 'api_version': None}))
    with pytest.raises(ValueError, match='0.3.1'):
        client.list_store_products()
    assert not client.store_options


def test_catalog_receipt_rejects_contradictory_database_confirmation():
    client = api()
    body = {'saved': [{'id': 2532, 'product': row(status='draft'),
                      'verification': {'database_status': 'publish'}}], 'failed': []}
    client._request = Mock(return_value=Response(body))
    with pytest.raises(ValueError, match='confirmación'):
        client.store_catalog_action('unpublish', [{'id': 2532, 'expected_revision': 'a'*64}])
