from copy import deepcopy
from types import SimpleNamespace
from unittest.mock import Mock
import pytest
from PySide6.QtCore import QPoint, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QAbstractItemView

from yumekai_importer.storage.review_draft_backup import ReviewDraftBackup
from yumekai_importer.ui.widgets.change_review_dialog import ChangeReviewDialog
from yumekai_importer.ui.windows.pending_review_window import PendingReviewWindow
from yumekai_importer.ui.windows.store_review_window import StoreReviewWindow
from yumekai_importer.ui.windows.catalog_window import CatalogWindow


def pending(product, path):
    page = PendingReviewWindow(draft_backup=ReviewDraftBackup(path))
    page._products["pending_review"] = {product["isbn"]: product}
    page._drafts = {product["isbn"]: {"changes": {"description": "Propuesta", "author": "Otro autor"},
                                      "ready_to_upload": False}}
    page._selected.add(product["isbn"])
    page._fill_tables()
    return page, product["isbn"]


def store(product, path):
    page = StoreReviewWindow(draft_backup=ReviewDraftBackup(path))
    page._products = [{**product, "review_status": "in_store"}]
    page._drafts = {"21": {"changes": {"description": "Propuesta", "author": "Otro autor"}, "ready_to_upload": False}}
    page._selected = {"21"}
    page._fill_table()
    return page, "21"


@pytest.mark.parametrize("factory,method,module", [
    (pending, "_retry_drafts", "pending_review_window"),
    (store, "_save_proposals", "store_review_window"),
])
def test_confirm_all_unchecked_clears_marks_drafts_and_backup(app, product, tmp_path, monkeypatch, factory, method, module):
    page, key = factory(product, tmp_path / "drafts.json")
    backup = page._draft_backup
    backup.save({key: page._current_product(key) if factory is pending else page._products[0]}, page._drafts, {})
    monkeypatch.setattr(f"yumekai_importer.ui.windows.{module}.review_changes", lambda *a, **k: {})
    getattr(page, method)()
    assert page._drafts == {}
    assert page._selected == set()
    assert not backup.exists()
    assert page._action_worker is None


@pytest.mark.parametrize("factory,method,module", [
    (pending, "_retry_drafts", "pending_review_window"),
    (store, "_save_proposals", "store_review_window"),
])
def test_cancel_keeps_all_proposals_and_selection(app, product, tmp_path, monkeypatch, factory, method, module):
    page, _ = factory(product, tmp_path / "drafts.json")
    before = deepcopy(page._drafts), set(page._selected)
    monkeypatch.setattr(f"yumekai_importer.ui.windows.{module}.review_changes", lambda *a, **k: None)
    getattr(page, method)()
    assert (page._drafts, page._selected) == before


def test_store_partial_failure_retains_only_accepted_fields(app, product, tmp_path, monkeypatch):
    page, key = store(product, tmp_path / "drafts.json")
    monkeypatch.setattr("yumekai_importer.ui.windows.store_review_window.review_changes",
                        lambda *a, **k: {key: {"description": "Propuesta"}})
    # Missing credentials prevent sending; confirmed discard must still be final.
    page._api = Mock(side_effect=ValueError("Sin conexión"))
    page._save_proposals()
    assert page._drafts[key]["changes"] == {"description": "Propuesta"}
    assert not page._selected
    page._action_worker = SimpleNamespace(
        entries=[{"id": 21, "changes": {"description": "Propuesta"}}],
        result={"saved": [], "failed": [{"id": 21, "message": "Ficha modificada", "status_code": 409}]},
        error=None, deleteLater=lambda: None)
    page._finish_save_store()
    assert page._drafts[key]["changes"] == {"description": "Propuesta"}
    assert page._drafts[key]["save_error"] == "Ficha modificada"
    assert page._draft_backup.load()["drafts"][key]["changes"] == {"description": "Propuesta"}


def test_pending_partial_confirmation_sends_only_accepted_fields(app, product, tmp_path, monkeypatch):
    page, key = pending(product, tmp_path / "drafts.json")
    monkeypatch.setattr("yumekai_importer.ui.windows.pending_review_window.review_changes",
                        lambda *a, **k: {key: {"description": "Propuesta"}})
    page._start_action = Mock()
    page._retry_drafts()
    action, entries = page._start_action.call_args.args
    assert action == "save"
    assert entries[0]["changes"] == {"description": "Propuesta"}
    assert not page._selected


def test_supplier_results_open_store_review_immediately(app, product, tmp_path, monkeypatch):
    page, key = store(product, tmp_path / "drafts.json")
    page._drafts.clear()
    monkeypatch.setattr("yumekai_importer.ui.windows.store_review_window.sd_review_changes",
                        lambda *a, **k: ({"description": "Propuesta"}, "Actualiza sinopsis"))
    page._save_proposals = Mock()
    page._sd_worker = SimpleNamespace(products={key: product}, stock_only=False,
        results={key: SimpleNamespace(status="found", url="")}, error=None, deleteLater=lambda: None)
    page._finish_sd()
    page._save_proposals.assert_called_once_with(keys=[key])


def test_supplier_results_open_pending_review_immediately(app, product, tmp_path, monkeypatch):
    page, key = pending(product, tmp_path / "drafts.json")
    monkeypatch.setattr("yumekai_importer.ui.windows.pending_review_window.sd_review_changes",
                        lambda *a, **k: ({"description": "Propuesta"}, "Actualiza sinopsis"))
    page._retry_drafts = Mock()
    page._sd_worker = SimpleNamespace(products={key: product}, stock_only=False,
        results={key: SimpleNamespace(status="found", url="", isbn=key)}, error=None, deleteLater=lambda: None)
    page._finish_sd_recheck()
    page._retry_drafts.assert_called_once_with(keys=[key])


@pytest.mark.parametrize("factory", [pending, store])
def test_ui_blocks_incompatible_editorials(app, product, tmp_path, factory):
    page, _ = factory({**product, "publisher": "Norma"}, tmp_path / "drafts.json")
    action = page._sd_button if factory is pending else page._full_action
    assert not action.isEnabled()
    page._recheck_sd()
    assert page._sd_worker is None
    assert "Norma" in page._feedback.text()


def test_review_click_and_keyboard_highlight_whole_row(app, product):
    dialog = ChangeReviewDialog({"a": {"product": product, "changes": {"description": "Nuevo", "author": "Otro"}}})
    dialog.show()
    app.processEvents()
    table = dialog.table
    QTest.mouseClick(table.viewport(), Qt.MouseButton.LeftButton, pos=table.visualItemRect(table.item(0, 3)).center())
    assert {index.column() for index in table.selectedIndexes()} == set(range(table.columnCount()))
    QTest.keyClick(table, Qt.Key.Key_Down)
    assert {index.row() for index in table.selectedIndexes()} == {1}
    assert len(table.selectedIndexes()) == table.columnCount()
    # Clicking a checkbox changes the decision while keeping the row identifiable.
    QTest.mouseClick(table.viewport(), Qt.MouseButton.LeftButton,
                     pos=table.visualItemRect(table.item(0, 0)).topLeft() + QPoint(20, 14))
    assert len(table.selectedIndexes()) == table.columnCount()
    dialog.reject()


def test_frozen_title_and_scrolled_cell_share_row_selection(app, product, tmp_path):
    page, _ = pending(product, tmp_path / "drafts.json")
    table = page._tables["pending_review"]
    assert table.selectionBehavior() == QAbstractItemView.SelectionBehavior.SelectRows
    assert table.selectionModel() is table._frozen_view.selectionModel()
    table.selectRow(0)
    assert len(table.selectedIndexes()) == table.columnCount()
    assert len(table._frozen_view.selectionModel().selectedRows()) == 1


def test_home_has_distinct_review_and_store_destinations(app, monkeypatch):
    monkeypatch.setattr(PendingReviewWindow, "showEvent", lambda *a: None)
    monkeypatch.setattr(StoreReviewWindow, "showEvent", lambda *a: None)
    window = CatalogWindow()
    assert window._review_page is not window._inventory_page
    window._home_page.buttons[1].click()
    assert window._pages.currentWidget() is window._review_page
    window._show_page(window._home_page)
    window._home_page.buttons[2].click()
    assert window._pages.currentWidget() is window._inventory_page


def test_returning_to_store_does_not_reload(app, monkeypatch):
    page = StoreReviewWindow()
    page._loaded = True
    page._load_inventory = Mock()
    from PySide6.QtGui import QShowEvent
    page.showEvent(QShowEvent())
    page._load_inventory.assert_not_called()


def test_initial_store_load_preserves_previous_recovery_copy(app, product, tmp_path):
    path = tmp_path / "drafts.json"
    backup = ReviewDraftBackup(path)
    backup.save({"21": {**product, "review_status": "in_store"}},
                {"21": {"changes": {"description": "Anterior"}, "ready_to_upload": False}}, {})
    page = StoreReviewWindow(draft_backup=backup)
    page._worker = SimpleNamespace(products=[{**product, "review_status": "in_store"}], sync_result=None,
                                   error=None, discard_drafts=False, options={}, status="publish", elapsed=1.0, deleteLater=lambda: None)
    page._finish_load_store()
    assert backup.load()["drafts"]["21"]["changes"] == {"description": "Anterior"}


def test_leaving_pending_without_recovering_does_not_erase_previous_copy(app, product, tmp_path):
    path = tmp_path / "drafts.json"
    backup = ReviewDraftBackup(path)
    key = product['isbn']
    backup.save({key: product}, {key: {"changes": {"description": "Anterior"}, "ready_to_upload": False}}, {})
    page = PendingReviewWindow(draft_backup=backup)
    assert page.can_leave()
    assert backup.exists()


def test_store_table_keeps_shop_classification_when_draft_contains_old_type(app, product, tmp_path):
    page, key = store({**product, 'title': 'TOWER OF GOD 01', 'work_type': 'Manhwa', 'categories': ['Manhwa']},
                      tmp_path / 'drafts.json')
    page._drafts[key]['changes']['work_type'] = 'Manga'
    page._fill_table()
    assert page._current_products()[0]['work_type'] == 'Manhwa'
    assert page._drafts[key]['changes']['work_type'] == 'Manga'
    column = next(index for index, (field, *_rest) in enumerate(page.columns) if field == 'work_type')
    assert page._table.item(0, column).text() == 'Manhwa'
