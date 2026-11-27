"""Collection edits must respect scope, explicit field choices and pending drafts."""
from copy import deepcopy
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from PySide6.QtWidgets import QApplication, QDialog

from yumekai_importer.catalog.collection_edit import collection_changes, collection_products
from yumekai_importer.storage.review_draft_backup import ReviewDraftBackup
from yumekai_importer.ui.widgets.collection_edit_dialog import CollectionEditDialog
from yumekai_importer.ui.windows.pending_review_window import PendingReviewWindow


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


def product(isbn="one", **changes):
    return {"isbn": isbn, "title": f"EJEMPLO {isbn}", "series": "EJEMPLO", "publisher": "Norma",
            "volume": "1", "work_type": "Manga", "demographic": "Shonen", "book_format": "Rústica",
            "pages": 200, "description": f"Sinopsis {isbn}", "retail_price": "9.95", "sale_price": "9.45",
            "review_status": "pending_review", "yumekai_status": "instock", "_revision": "revision-1",
            **changes}


def test_collection_matching_keeps_other_editions_and_missing_series_separate():
    products = {str(i): product(str(i), series=series, publisher=publisher) for i, (series, publisher) in enumerate([
        ("EJEMPLO", "Norma"), (" ejemplo  ", "Panini"), ("Ejemplo integral", "Norma"),
        ("Ejemplo: integral", "Norma"), ("", "Norma"), (None, "Norma"),
    ])}
    assert set(collection_products(products, "Ejemplo")) == {"0", "1"}
    assert set(collection_products(products, "Ejemplo", "norma")) == {"0"}
    assert not collection_products(products, "")
    assert set(collection_products(products, "Ejemplo integral")) == {"2"}


def test_only_explicitly_chosen_fields_change_and_sources_are_untouched():
    products = {"one": product(), "two": product("two", pages="240")}
    before = deepcopy(products)
    assert collection_changes(products, {"pages": "240"}) == {"one": {"pages": 240}}
    assert products == before
    values = {"work_type": "Manga", "demographic": "Seinen", "book_format": "Tapa dura",
              "pages": "320", "description": "Sinopsis de la colección"}
    proposals = collection_changes(products, values)
    assert all(set(fields) == {"demographic", "book_format", "pages", "description"} for fields in proposals.values())
    assert all(fields["description"] == values["description"] for fields in proposals.values())


@pytest.mark.parametrize("value", ["", "abc", "0", "-1", "200.5", "4294967296"])
def test_invalid_page_counts_are_rejected(value):
    with pytest.raises(ValueError):
        collection_changes({"one": product()}, {"pages": value})


@pytest.mark.parametrize("values", [{}, {"isbn": "other"}, {"description": "  "}, {"work_type": "Libro"}])
def test_invalid_or_empty_batch_fields_are_rejected(values):
    with pytest.raises(ValueError):
        collection_changes({"one": product()}, values)


def test_demography_requires_manga_for_every_target():
    products = {"one": product(), "two": product("two", work_type="Manhwa")}
    with pytest.raises(ValueError, match="Manga"):
        collection_changes(products, {"demographic": "Seinen"})
    result = collection_changes(products, {"work_type": "Manga", "demographic": "Seinen"})
    assert result["two"] == {"work_type": "Manga", "demographic": "Seinen"}


def test_dialog_requires_explicit_fields_and_uses_common_values_only(app):
    products = {"one": product(), "two": product("two", pages=240)}
    dialog = CollectionEditDialog(products, initial_series="Ejemplo")
    assert dialog._table.rowCount() == 2
    assert not dialog._preview.isEnabled()
    assert dialog._editors["pages"].text() == ""
    assert dialog._editors["description"].toPlainText() == ""
    assert dialog._editors["book_format"].currentData() == "Rústica"
    dialog._checks["pages"].setChecked(True)
    dialog._editors["pages"].setText("320")
    dialog.accept()
    assert dialog.result() == QDialog.DialogCode.Accepted
    assert dialog.changes == {key: {"pages": 320} for key in products}
    dialog.deleteLater()


def test_publisher_scope_and_switching_collection_reset_field_selection(app):
    dialog = CollectionEditDialog({"one": product(), "two": product("two", publisher="Panini"),
                                  "other": product("other", series="OTRA")}, initial_series="Ejemplo")
    dialog._publisher.setCurrentIndex(dialog._publisher.findData("Norma"))
    assert set(dialog._targets()) == {"one"}
    dialog._checks["description"].setChecked(True)
    dialog._editors["description"].setPlainText("Texto común")
    dialog._collection.setCurrentIndex(dialog._collection.findData("otra"))
    assert set(dialog._targets()) == {"other"}
    assert not dialog._checks["description"].isChecked()
    assert not dialog._preview.isEnabled()
    dialog._collection.setEditText("No existe")
    assert not dialog._targets() and not dialog._preview.isEnabled()
    dialog.deleteLater()


def test_dialog_demography_follows_effective_type_and_noop_stays_open(app):
    dialog = CollectionEditDialog({"one": product(work_type="Manhwa")}, initial_series="Ejemplo")
    assert not dialog._checks["demographic"].isEnabled()
    dialog._checks["work_type"].setChecked(True)
    dialog._editors["work_type"].setCurrentIndex(dialog._editors["work_type"].findData("Manga"))
    assert dialog._checks["demographic"].isEnabled()
    dialog._checks["demographic"].setChecked(True)
    dialog._editors["work_type"].setCurrentIndex(dialog._editors["work_type"].findData("Manhua"))
    assert not dialog._checks["demographic"].isChecked()
    dialog.deleteLater()
    dialog = CollectionEditDialog({"one": product()}, initial_series="Ejemplo")
    dialog._checks["pages"].setChecked(True)
    dialog.accept()
    assert dialog.result() != QDialog.DialogCode.Accepted
    assert "No hay cambios" in dialog._error.text()
    dialog.deleteLater()


@pytest.fixture
def page(app, tmp_path):
    window = PendingReviewWindow(draft_backup=ReviewDraftBackup(tmp_path / "drafts.json"))
    window._products["pending_review"] = {"one": product(), "two": product("two")}
    window._products["ready_to_upload"] = {"ready": product("ready", review_status="ready_to_upload")}
    window._start_action = Mock()
    window._fill_tables()
    yield window
    window.deleteLater()


def fake_dialog(monkeypatch, proposals, *, accepted=True):
    constructor = Mock(return_value=SimpleNamespace(
        changes=proposals,
        exec=lambda: QDialog.DialogCode.Accepted if accepted else QDialog.DialogCode.Rejected,
        deleteLater=lambda: None,
    ))
    monkeypatch.setattr("yumekai_importer.ui.windows.pending_review_window.CollectionEditDialog", constructor)
    return constructor


def fake_review(monkeypatch, selected):
    review = Mock(return_value=selected)
    monkeypatch.setattr("yumekai_importer.ui.windows.pending_review_window.review_collection_changes", review)
    return review


def test_batch_includes_hidden_collection_members_but_only_the_active_tab(page, monkeypatch):
    page._search.setText("EJEMPLO one")
    page._apply_filter_rows()
    assert page._visible_keys() == ["one"]
    constructor = fake_dialog(monkeypatch, {"one": {"pages": 320}, "two": {"pages": 320}})
    fake_review(monkeypatch, {"one": {"pages": 320}, "two": {"pages": 320}})
    page._edit_collection()
    assert set(constructor.call_args.args[0]) == {"one", "two"}
    action, entries = page._start_action.call_args.args
    assert action == "save" and {entry["original_isbn"] for entry in entries} == {"one", "two"}
    assert all(not entry["ready_to_upload"] for entry in entries)
    assert "ready" not in page._drafts
    assert all(entry["expected_revision"] == "revision-1" for entry in entries)


@pytest.mark.parametrize("cancel_at", ["editor", "preview", "uncheck_all"])
def test_cancel_or_deselect_all_keeps_existing_drafts_unchanged(page, monkeypatch, cancel_at):
    page._drafts = {"one": {"changes": {"description": "Texto propio"}, "ready_to_upload": False}}
    before = deepcopy(page._drafts)
    fake_dialog(monkeypatch, {"one": {"pages": 320}}, accepted=cancel_at != "editor")
    fake_review(monkeypatch, None if cancel_at == "preview" else {})
    page._edit_collection()
    assert page._drafts == before
    page._start_action.assert_not_called()


def test_selected_batch_fields_do_not_submit_or_discard_other_pending_edits(page, monkeypatch):
    page._drafts = {"one": {"changes": {"description": "Texto propio", "pages": 220}, "ready_to_upload": False}}
    fake_dialog(monkeypatch, {"one": {"pages": 320, "description": "Texto por lote"}})
    fake_review(monkeypatch, {"one": {"pages": 320}})
    page._edit_collection()
    assert page._drafts["one"]["changes"] == {"description": "Texto propio", "pages": 320}
    entries = page._start_action.call_args.args[1]
    assert entries[0]["changes"] == {"pages": 320}
    backup = page._draft_backup.load()
    assert backup["drafts"]["one"]["changes"] == page._drafts["one"]["changes"]


def test_partial_preview_cannot_apply_demography_without_required_type_change(page, monkeypatch):
    page._products["pending_review"]["one"]["work_type"] = "Manhwa"
    fake_dialog(monkeypatch, {"one": {"work_type": "Manga", "demographic": "Seinen"}})
    fake_review(monkeypatch, {"one": {"demographic": "Seinen"}})
    page._edit_collection()
    assert not page._drafts
    page._start_action.assert_not_called()
    assert "Manga" in page._feedback.text()


def test_ready_batch_preserves_status_and_categories_follow_classification(page, monkeypatch):
    page._tabs.setCurrentWidget(page._tables["ready_to_upload"])
    constructor = fake_dialog(monkeypatch, {"ready": {"demographic": "Seinen"}})
    fake_review(monkeypatch, {"ready": {"demographic": "Seinen"}})
    page._edit_collection()
    assert set(constructor.call_args.args[0]) == {"ready"}
    entry = page._start_action.call_args.args[1][0]
    assert entry["ready_to_upload"]
    assert entry["expected_review_status"] == "ready_to_upload"
    assert page._current_product("ready")["categories"] == ["Manga", "Manga > Seinen"]


def test_save_failure_keeps_accepted_collection_changes_and_local_backup(page, monkeypatch):
    fake_dialog(monkeypatch, {"one": {"pages": 320}})
    fake_review(monkeypatch, {"one": {"pages": 320}})
    page._edit_collection()
    entry = page._start_action.call_args.args[1][0]
    page._action_worker = SimpleNamespace(action="save", result={"saved": [], "failed": []},
        error="Sin conexión", products=[entry], deleteLater=lambda: None)
    page._finish_action()
    assert page._drafts["one"]["changes"] == {"pages": 320}
    assert page._draft_backup.load()["drafts"]["one"]["changes"] == {"pages": 320}


def test_successful_batch_save_retains_unrelated_drafts_and_updates_revision(page, monkeypatch):
    page._drafts = {"one": {"changes": {"description": "Texto propio"}, "ready_to_upload": False}}
    fake_dialog(monkeypatch, {"one": {"pages": 320}, "two": {"pages": 320}})
    fake_review(monkeypatch, {"one": {"pages": 320}, "two": {"pages": 320}})
    page._edit_collection()
    entries = page._start_action.call_args.args[1]
    saved = [{"original_isbn": entry["original_isbn"], "product": {
        **page._products["pending_review"][entry["original_isbn"]], **entry["changes"], "_revision": "revision-2"
    }} for entry in entries]
    page._action_worker = SimpleNamespace(action="save", result={"saved": saved, "failed": []},
        error=None, products=entries, deleteLater=lambda: None)
    page._finish_action()
    assert page._products["pending_review"]["one"]["pages"] == 320
    assert page._products["pending_review"]["two"]["_revision"] == "revision-2"
    assert page._drafts == {"one": {"changes": {"description": "Texto propio"}, "ready_to_upload": False}}


def test_collection_edit_is_disabled_while_another_operation_is_running(page, monkeypatch):
    constructor = fake_dialog(monkeypatch, {})
    page._action_worker = object()
    page._update_actions()
    assert not page._collection_edit_action.isEnabled()
    page._edit_collection()
    constructor.assert_not_called()
    page._action_worker = None
