"""Recheck filled fields, and keep stock-only reviews scoped through saving."""
from dataclasses import replace
from threading import Event
from types import SimpleNamespace
from unittest.mock import Mock

from lxml import html
import pytest
from PySide6.QtWidgets import QApplication

from yumekai_importer.catalog.norma_review import norma_review_changes
from yumekai_importer.catalog.sd_review import sd_review_changes
from yumekai_importer.importers.sd.details import SdDetails
from yumekai_importer.importers.sd.lookup import SdLookupResult
from yumekai_importer.importers.mangaupdates import MangaUpdatesClient
from yumekai_importer.importers.norma.lookup import NormaDetails, NormaEditionMismatch, NormaLookupResult
from yumekai_importer.importers.norma import zonalibros as portal
from yumekai_importer.storage.mangaupdates_cache import MangaUpdatesCache
from yumekai_importer.ui.workers import norma_recheck_worker as workers
from yumekai_importer.ui.windows.pending_review_window import PendingReviewWindow
from yumekai_importer.ui.windows.store_review_window import StoreReviewWindow
from yumekai_importer.tests.test_zonalibros import client_with_responses, markup, URL


ISBN = "9788467945850"


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


def product(**values):
    return {"isbn": ISBN, "title": "EJEMPLO 01", "publisher": "Norma", "series": "EJEMPLO",
            "author": "Autor anterior", "pages": 100, "description": "Sinopsis anterior.",
            "book_format": "Rústica", "retail_price": "9.00", "sale_price": "8.55",
            "work_type": "Manga", "demographic": "Seinen", "yumekai_status": "outofstock",
            "review_status": "pending_review", "updated_at": "2026-11-27 12:00:00", **values}


def norma(**values):
    return NormaLookupResult(ISBN, "found", NormaDetails(**{
        "title": "EJEMPLO 01", "author": "Autor nuevo", "pages": 224,
        "description": "Sinopsis nueva.", "book_format": "Tapa dura", "series": "EJEMPLO",
        "work_type": "Manga", "demographic": "Shonen", "retail_price": "12.00",
        "availability": "Stock: Sí", "yumekai_status": "yk_on_demand", **values}), URL)


def sd(**values):
    details = SdDetails(**{"work_type": "Manga", "demographic": "Shonen", "pages": 224,
        "sd_format": "Cartoné", "author": "Autor nuevo", "description": "Sinopsis nueva.",
        "retail_price": "12.00", "publisher": "Panini", **values})
    return SdLookupResult(ISBN, "found", True, details)


@pytest.mark.parametrize("source", ["sd", "norma"])
def test_full_recheck_proposes_changed_filled_fields_and_recalculates_discount(source):
    original = product(publisher="Panini" if source == "sd" else "Norma")
    compare, result = (sd_review_changes, sd()) if source == "sd" else (norma_review_changes, norma())
    changes, _ = compare(original, result)
    assert changes["author"] == "Autor nuevo" and changes["pages"] == 224
    assert changes["description"] == "Sinopsis nueva." and changes["book_format"] == "Tapa dura"
    assert changes["demographic"] == "Shonen" and changes["retail_price"] == "12.00"
    assert changes["sale_price"] == "11.40" and changes["yumekai_status"] == "yk_on_demand"
    assert original["pages"] == 100 and original["retail_price"] == "9.00"
    assert compare({**original, **changes}, result)[0] == {}


@pytest.mark.parametrize("source", ["sd", "norma"])
def test_stock_only_never_proposes_other_differences(source):
    compare, result = (sd_review_changes, sd()) if source == "sd" else (norma_review_changes, norma())
    assert compare(product(), result, stock_only=True)[0] == {"yumekai_status": "yk_on_demand"}
    assert compare(product(yumekai_status="yk_on_demand"), result, stock_only=True)[0] == {}


@pytest.mark.parametrize("source", ["sd", "norma"])
def test_empty_source_fields_cannot_erase_saved_fields(source):
    compare, result = (sd_review_changes, sd(author=None, description=None, pages=None, retail_price=None)) if source == "sd" else (
        norma_review_changes, norma(author=None, description=None, pages=None, retail_price=None))
    changes, _ = compare(product(), result)
    assert not {"author", "description", "pages", "retail_price", "sale_price"}.intersection(changes)


@pytest.mark.parametrize("source", ["sd", "norma"])
def test_price_comparison_ignores_display_precision_and_invalid_new_pvp(source):
    compare, make = (sd_review_changes, sd) if source == "sd" else (norma_review_changes, norma)
    for price in (None, "0", "texto", "-1"):
        changes, _ = compare(product(), make(retail_price=price))
        assert "retail_price" not in changes and "sale_price" not in changes
    changes, _ = compare(product(retail_price="12", sale_price="11,40"), make())
    assert "retail_price" not in changes and "sale_price" not in changes


def test_stock_lookup_skips_bibliographic_parsing_but_verifies_isbn(monkeypatch):
    client = client_with_responses((markup(), URL))
    client.authenticated = True
    full_parser = Mock(side_effect=AssertionError("Stock must not parse full details"))
    monkeypatch.setattr(portal, "parse_zonalibros_details", full_parser)
    result = client.lookup(ISBN, stock_only=True)
    assert result.status == "found" and result.details.yumekai_status == "yk_on_demand"
    assert result.details.pages is None and result.details.description is None and result.details.book_format is None
    full_parser.assert_not_called()
    with pytest.raises(NormaEditionMismatch):
        portal.parse_zonalibros_stock(html.fromstring(markup(isbn="9788467968705")), ISBN, URL)


def test_stock_worker_uses_one_session_and_never_starts_metadata(app, monkeypatch):
    client = Mock()
    client.lookup.side_effect = lambda isbn, **kwargs: replace(norma(), isbn=isbn)
    monkeypatch.setattr(workers, "ZonaLibrosClient", lambda stop: client)
    metadata = Mock(side_effect=AssertionError("Stock must not query MangaUpdates"))
    monkeypatch.setattr(workers, "MangaUpdatesClient", metadata)
    worker = workers.NormaRecheckWorker({ISBN: product(), "second": product(isbn="9788467968705")}, stock_only=True)
    worker.run()
    assert client.login.call_count == 1 and client.lookup.call_count == 2
    assert all(call.kwargs == {"stock_only": True} for call in client.lookup.call_args_list)
    assert all(result.status == "found" for result in worker.results.values())
    metadata.assert_not_called()
    client.close.assert_called_once()


def test_new_recheck_refreshes_even_unexpired_classification_cache(tmp_path):
    path = tmp_path / "metadata.json"
    def make(genre, *, refresh=False):
        client = MangaUpdatesClient(cache=MangaUpdatesCache(path), refresh=refresh)
        record = {"series_id": 1, "title": "Ejemplo", "type": "Manga", "associated": [],
            "authors": [{"name": "Autor nuevo"}], "genres": [{"genre": genre}],
            "url": "https://www.mangaupdates.com/series/example/ejemplo"}
        client._request = Mock(side_effect=lambda route, **kwargs: {"results": [{"record": record}]} if route.endswith("search") else record)
        return client
    first = make("Seinen")
    assert first.lookup("Ejemplo", "Autor nuevo").demographic == "Seinen"
    first.close()
    second = make("Shounen", refresh=True)
    result = second.lookup("Ejemplo", "Autor nuevo")
    assert result.demographic == "Shonen" and second._request.call_count == 2
    assert second.lookup("EJEMPLO", "nuevo Autor") == result
    assert second._request.call_count == 2  # Reuse the fresh classification between volumes of this batch.


def pending_page():
    page = PendingReviewWindow()
    page._products["pending_review"] = {ISBN: product()}
    page._selected = {ISBN}
    return page


def store_page():
    page = StoreReviewWindow()
    row = product(woocommerce_id=407, _store_revision="a" * 64,
                  publication_status="publish", review_status="in_store", product_type="simple")
    page._products = [row]
    page._selected = {"407"}
    return page


@pytest.mark.parametrize("store", [False, True])
def test_norma_stock_action_is_available_and_sd_is_separate(app, store):
    page = store_page() if store else pending_page()
    page._update_actions()
    action = page._norma_stock_action if store else page._norma_stock_button
    assert action.isEnabled()
    sd_action = page._stock_action if store else page._sd_stock_button
    assert not sd_action.isEnabled()
    page.close()


@pytest.mark.parametrize("store", [False, True])
def test_stock_mode_is_forwarded_to_worker_and_stop_controls(app, monkeypatch, store):
    page = store_page() if store else pending_page()
    page._norma_access = SimpleNamespace()
    worker = SimpleNamespace(progress=Mock(), finished=Mock(), start=Mock(), stop_requested=Event())
    factory = Mock(return_value=worker)
    module = "store_review_window" if store else "pending_review_window"
    monkeypatch.setattr(f"yumekai_importer.ui.windows.{module}.NormaRecheckWorker", factory)
    page._recheck_norma(stock_only=True)
    assert factory.call_args.kwargs["stock_only"] is True and page._busy
    worker.start.assert_called_once()
    page._stop_sd() if store else page._stop_supplier_check()
    assert worker.stop_requested.is_set()
    page._norma_worker = None
    page.close()


@pytest.mark.parametrize("store", [False, True])
def test_finishing_stock_recheck_reviews_only_stock_even_with_other_pending_edits(app, monkeypatch, store):
    page = store_page() if store else pending_page()
    key = "407" if store else ISBN
    row = page._products[0] if store else product()
    page._drafts = {key: {"changes": {"description": "Edición pendiente."}, "ready_to_upload": False}}
    page._norma_worker = SimpleNamespace(products={key: row}, results={key: norma()}, stock_only=True, error=None, deleteLater=Mock())
    module = "store_review_window" if store else "pending_review_window"
    observed = {}
    def review(rows, **kwargs):
        observed.update(rows)
        return {key: {"yumekai_status": "yk_on_demand"}}
    monkeypatch.setattr(f"yumekai_importer.ui.windows.{module}.review_changes", review)
    if store:
        save_worker = SimpleNamespace(finished=Mock(), start=Mock())
        factory = Mock(return_value=save_worker)
        monkeypatch.setattr(f"yumekai_importer.ui.windows.{module}.StoreSaveWorker", factory)
        page._api = Mock()
        page._finish_norma()
        entries = factory.call_args.args[1]
    else:
        page._start_action = Mock()
        page._finish_norma_recheck()
        entries = page._start_action.call_args.args[1]
    assert observed[key]["changes"] == {"yumekai_status": "yk_on_demand"}
    assert entries[0]["changes"] == {"yumekai_status": "yk_on_demand"}
    assert page._drafts[key]["changes"]["description"] == "Edición pendiente."
    page._action_worker = None
    page._drafts.clear()
    page.close()


def test_store_keeps_published_status_if_norma_cannot_confirm_an_equivalent(app):
    page = store_page()
    page._norma_worker = SimpleNamespace(products={"407": page._products[0]}, stock_only=True,
        results={"407": norma(availability="Stock: No · EN REIMPRESIÓN", yumekai_status=None)}, error=None, deleteLater=Mock())
    page._save_proposals = Mock()
    page._finish_norma()
    assert not page._drafts and page._products[0]["yumekai_status"] == "outofstock"
    assert "sin confirmar" in page._sd_results["407"]["note"]
    page._save_proposals.assert_not_called()
    page.close()


@pytest.mark.parametrize("store", [False, True])
def test_rejecting_stock_change_keeps_unrelated_drafts_without_sending_them(app, monkeypatch, store):
    page = store_page() if store else pending_page()
    key = "407" if store else ISBN
    page._drafts = {key: {"changes": {"description": "Edición pendiente.", "yumekai_status": "yk_on_demand"}, "ready_to_upload": False}}
    module = "store_review_window" if store else "pending_review_window"
    monkeypatch.setattr(f"yumekai_importer.ui.windows.{module}.review_changes", lambda *a, **k: {})
    page._api = Mock()
    if store:
        factory = Mock()
        monkeypatch.setattr(f"yumekai_importer.ui.windows.{module}.StoreSaveWorker", factory)
        page._save_proposals(keys=[key], fields={"yumekai_status"})
        factory.assert_not_called()
    else:
        page._start_action = Mock()
        page._retry_drafts(keys=[key], fields={"yumekai_status"})
        page._start_action.assert_not_called()
    assert page._drafts[key]["changes"] == {"description": "Edición pendiente."}
    page._api.assert_not_called()
    page._drafts.clear()
    page.close()


@pytest.mark.parametrize("store", [False, True])
def test_cancelled_access_never_starts_norma_worker(app, monkeypatch, store):
    page = store_page() if store else pending_page()
    module = "store_review_window" if store else "pending_review_window"
    monkeypatch.setattr(f"yumekai_importer.ui.windows.{module}.load_norma_credentials", lambda: None)
    monkeypatch.setattr(page, "_configure_norma_access", lambda: False)
    factory = Mock()
    monkeypatch.setattr(f"yumekai_importer.ui.windows.{module}.NormaRecheckWorker", factory)
    page._recheck_norma(stock_only=True)
    factory.assert_not_called()
    page.close()
