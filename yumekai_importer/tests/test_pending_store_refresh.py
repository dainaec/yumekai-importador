from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QDialog, QMessageBox

from yumekai_importer.ui.workers.load_pending_worker import LoadPendingWorker
from yumekai_importer.ui.widgets.change_review_dialog import ChangeReviewDialog
from yumekai_importer.ui.widgets.title_review_dialog import TitleReviewDialog
from yumekai_importer.ui.windows.pending_review_window import PendingReviewWindow
from yumekai_importer.ui.windows.store_review_window import StoreReviewWindow
from yumekai_importer.storage.review_draft_backup import ReviewDraftBackup


def test_pending_refresh_loads_first_then_checks_and_refreshes_queues(app):
    calls = []
    api = Mock()
    api.sync_store.side_effect = lambda: (calls.append('sync') or {'linked': 1})
    api.list_products.side_effect = lambda status: (calls.append(status) or [{'isbn': 'remaining', 'review_status': status}])
    worker = LoadPendingWorker(api)
    worker.run()
    assert calls == ['pending_review', 'ready_to_upload', 'sync', 'pending_review', 'ready_to_upload']
    assert worker.sync_result == {'linked': 1} and worker.error is None
    assert set(worker.products_by_status) == {'pending_review', 'ready_to_upload'}


def test_failed_shop_check_still_returns_both_importer_queues(app):
    api = Mock()
    api.sync_store.side_effect = ValueError('No se pudo comprobar WooCommerce')
    api.list_products.side_effect = lambda status: [{'isbn': '9788411504898', 'review_status': status}]
    worker = LoadPendingWorker(api)
    delivered = []
    worker.data_ready.connect(lambda data: delivered.append(data))
    worker.run()
    assert worker.error is None and worker.sync_error
    assert len(worker.products_by_status['pending_review']) == 1
    assert len(worker.products_by_status['ready_to_upload']) == 1
    assert delivered == [worker.products_by_status]
    assert api.list_products.call_count == 2


def test_failed_refresh_keeps_drafts_and_blocks_export_until_verified(app, product, tmp_path):
    window = PendingReviewWindow(draft_backup=ReviewDraftBackup(tmp_path / 'pending.json'))
    ready = {**product, 'review_status': 'ready_to_upload'}
    window._products['ready_to_upload'] = {product['isbn']: ready}
    window._drafts = {product['isbn']: {'changes': {'description': 'Mi texto'}, 'ready_to_upload': True}}
    window._worker = SimpleNamespace(error='Sin conexión', sync_result=None, deleteLater=lambda: None)
    window._finish_load()
    assert window._products['ready_to_upload'][product['isbn']] == ready
    assert window._drafts[product['isbn']]['changes']['description'] == 'Mi texto'
    assert window._store_check_failed and not window._export_button.isEnabled()


def test_collection_review_uses_field_selection_and_validates_edited_volume(app):
    products = {'9788411504898': {'isbn': '9788411504898', 'title': 'AFRO SAMURAI 01', 'series': 'OTRA COLECCIÓN', 'volume': '3'}}
    dialog = TitleReviewDialog(products)
    assert isinstance(dialog, ChangeReviewDialog)
    assert [dialog.table.horizontalHeaderItem(i).text() for i in range(5)] == ['Aplicar', 'Producto', 'Campo', 'Actual', 'Propuesto']
    volume_row = next(r for r in range(dialog.table.rowCount())
                      if dialog.table.item(r, 0).data(Qt.ItemDataRole.UserRole)[1] == 'volume')
    dialog.table.item(volume_row, 4).setText('5-1')
    dialog.accept()
    assert dialog.result() != QDialog.DialogCode.Accepted and dialog.error.text()
    dialog.table.item(volume_row, 4).setText('2')
    for r in range(dialog.table.rowCount()):
        dialog.table.item(r, 0).setCheckState(Qt.CheckState.Checked if r == volume_row else Qt.CheckState.Unchecked)
    dialog.accept()
    assert dialog.changes == {'9788411504898': {'volume': '2'}}


def test_collection_review_sends_only_accepted_fields_and_avoids_second_review(app, product, tmp_path, monkeypatch):
    key = product['isbn']
    page = PendingReviewWindow(draft_backup=ReviewDraftBackup(tmp_path / 'pending.json'))
    page._products['pending_review'] = {key: product}
    page._selected = {key}
    page._drafts = {key: {'changes': {'description': 'Sinopsis sin revisar'}, 'ready_to_upload': False}}
    dialog = SimpleNamespace(changes={key: {'series': 'COLECCIÓN CORRECTA'}}, exec=lambda: QDialog.DialogCode.Accepted, deleteLater=lambda: None)
    monkeypatch.setattr('yumekai_importer.ui.windows.pending_review_window.TitleReviewDialog', lambda *a, **k: dialog)
    page._start_action = Mock()
    page._retry_drafts = Mock()
    page._review_titles()
    action, entries = page._start_action.call_args.args
    assert action == 'save' and entries[0]['changes'] == {'series': 'COLECCIÓN CORRECTA'}
    assert page._drafts[key]['changes']['description'] == 'Sinopsis sin revisar'
    assert not page._selected
    page._retry_drafts.assert_not_called()


def test_unpublish_confirmation_identifies_id_isbn_and_edition(app, monkeypatch):
    page = StoreReviewWindow()
    page._products = [{'woocommerce_id': 407, '_store_revision': 'a'*64, 'title': 'AFRO SAMURAI: EDICION COMPLETA',
                       'isbn': '9788411504898', 'publication_status': 'publish'}]
    page._selected = {'407'}
    question = Mock(return_value=QMessageBox.StandardButton.Cancel)
    monkeypatch.setattr(QMessageBox, 'question', question)
    page._start_catalog_action = Mock()
    page._change_publication('unpublish')
    text = question.call_args.args[2]
    assert 'ID 407' in text and '9788411504898' in text and 'EDICION COMPLETA' in text
    page._start_catalog_action.assert_not_called()


def test_open_web_uses_exact_product_link_instead_of_title_search(app, monkeypatch):
    page = StoreReviewWindow()
    page._products = [{'woocommerce_id': 407, 'title': 'AFRO SAMURAI: EDICION COMPLETA',
                       'product_url': 'https://yumekai.es/producto/afro-samurai-edicion-completa/'}]
    page._selected = {'407'}
    opened = Mock()
    monkeypatch.setattr('yumekai_importer.ui.windows.store_review_window.QDesktopServices.openUrl', opened)
    page._open_selected_web()
    assert opened.call_args.args[0].toString() == 'https://yumekai.es/producto/afro-samurai-edicion-completa/'


def test_recovery_does_not_resurrect_products_removed_from_pending_after_shop_check(app, product, tmp_path):
    backup = ReviewDraftBackup(tmp_path / 'pending.json')
    key = product['isbn']
    backup.save({key: product}, {key: {'changes': {'description': 'Texto anterior'}, 'ready_to_upload': False}}, {})
    page = PendingReviewWindow(draft_backup=backup)
    page._loaded = True  # Successful refresh has left no pending product with that ISBN.
    page._restore_draft_backup()
    assert not page._drafts and all(not rows for rows in page._products.values())
    assert not backup.exists()
    archived = ReviewDraftBackup(tmp_path / 'revisiones-fuera-de-pendientes.json').load()
    assert archived['drafts'][key]['changes'] == {'description': 'Texto anterior'}


def test_first_open_shows_pending_products_when_shop_sync_fails(app, product, tmp_path):
    api = Mock()
    api.list_products.side_effect = lambda status: [product] if status == 'pending_review' else []
    api.sync_store.side_effect = ValueError('HTTP 500 del cruce')
    worker = LoadPendingWorker(api)
    worker.run()
    page = PendingReviewWindow(draft_backup=ReviewDraftBackup(tmp_path / 'pending.json'))
    page._worker = worker
    page._finish_load()
    assert product['isbn'] in page._products['pending_review']
    assert page._tables['pending_review'].rowCount() == 1
    assert page._loaded and page._store_check_failed
    page._selected = {product['isbn']}
    page._update_actions()
    assert page._ready_button.isEnabled() and page._sd_button.isEnabled()
    assert page._export_button.isHidden()  # CSV belongs to the Ready tab.
    assert 'Fichas del importador cargadas' in page._feedback.text()


def test_failed_post_sync_refresh_retains_first_complete_queue_snapshot(app, product):
    api = Mock()
    api.list_products.side_effect = [[product], [], ValueError('Fallo al releer')]
    api.sync_store.return_value = {'linked': 1}
    worker = LoadPendingWorker(api)
    worker.run()
    assert worker.error is None and worker.sync_error
    assert worker.products_by_status == {'pending_review': [product], 'ready_to_upload': []}


def test_importer_read_failure_does_not_attempt_shop_sync(app):
    api = Mock()
    api.list_products.side_effect = ValueError('No se pudo leer el importador')
    worker = LoadPendingWorker(api)
    worker.run()
    assert worker.error and not worker.products_by_status
    api.sync_store.assert_not_called()


def test_shop_failure_does_not_block_csv_of_locally_loaded_ready_products(app, product, tmp_path):
    page = PendingReviewWindow(draft_backup=ReviewDraftBackup(tmp_path / 'pending.json'))
    ready = {**product, 'review_status': 'ready_to_upload', 'sku': 'YMK-' + product['isbn']}
    page._worker = SimpleNamespace(error=None, sync_error='WooCommerce no disponible', sync_result=None,
        products_by_status={'pending_review': [], 'ready_to_upload': [ready]}, deleteLater=lambda: None)
    page._finish_load()
    page._tabs.setCurrentWidget(page._tables['ready_to_upload'])
    page._update_actions()
    assert page._export_button.isEnabled()
    assert page._tables['ready_to_upload'].rowCount() == 1
    assert 'Si generas un CSV' in page._feedback.text()
