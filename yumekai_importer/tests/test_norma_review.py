from dataclasses import replace
import json
from threading import Event
from types import SimpleNamespace
from unittest.mock import Mock

from lxml import html
import pytest
from PySide6.QtWidgets import QApplication

from yumekai_importer.catalog.norma_review import norma_review_changes
from yumekai_importer.importers.norma import lookup
from yumekai_importer.ui.windows.pending_review_window import PendingReviewWindow
from yumekai_importer.ui.workers.norma_recheck_worker import NormaRecheckWorker
from yumekai_importer.storage.review_draft_backup import ReviewDraftBackup


ISBN = "9788467945850"
OTHER = "9788467968705"
URL = "https://www.normaeditorial.com/ficha/manga/ejemplo/ejemplo-1"


def markup(isbn=ISBN, *, title="EJEMPLO 1", description="Descubre este manhwa de aventuras.",
           badge="Aventuras", section="MANGA"):
    # Original synthetic text: tests do not redistribute publisher descriptions.
    return f'''<html><head><meta charset="utf-8"><meta property="og:image" content="/upload/cover.jpg"></head>
    <body><nav>{section}</nav><div id="mid-col"><h1>{title}</h1>
    <div class="authors-list"><a>Autora A</a><a>Autor B</a></div>
    <div id="content"><p>{description}</p><button>Sigue leyendo</button></div>
    <a class="badge">{badge}</a><div id="features">
    <div><label>SERIE</label>EJEMPLO</div><div><label>ISBN</label>{isbn}</div>
    <div><label>FORMATO</label>Rústica con solapas</div><div><label>PÁGINAS</label>320 color</div>
    <div><label>PVP</label>14,95 €</div></div></div>
    <aside><div id="features"><div><label>ISBN</label>{OTHER}</div></div>
    <p>Recomendación: el manhua de otro autor.</p></aside></body></html>'''.encode()


def details(**kwargs):
    return lookup.parse_norma_details(html.fromstring(markup(**kwargs)), ISBN, URL)


def product(**kwargs):
    return {"isbn": ISBN, "title": "EJEMPLO 1", "publisher": "NORMA",
            "retail_price": "14.95", "sale_price": "14.20", "review_status": "pending_review",
            "yumekai_status": "outofstock", "updated_at": "2026-11-26 12:00:00", **kwargs}


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


def test_parses_own_fields_and_isolates_recommendations():
    value = details()
    assert value.author == "Autora A / Autor B"
    assert value.pages == 320 and value.retail_price == "14.95"
    assert value.series == "EJEMPLO" and value.volume == "1"
    assert value.work_type == "Manhwa"
    assert value.image_url == "https://www.normaeditorial.com/upload/cover.jpg"
    assert "Recomendación" not in value.description and "Sigue leyendo" not in value.description


def test_exact_isbn_is_required_in_main_product():
    with pytest.raises(lookup.NormaEditionMismatch):
        lookup.parse_norma_details(html.fromstring(markup(isbn=OTHER)), ISBN, URL)


@pytest.mark.parametrize("description,expected", [
    ("Una historia cotidiana.", None),
    ("Una historia completamente a color de un autor coreano.", None),
    ("Descubre este famoso manhua de aventuras.", "Manhua"),
    ("Conoce el manhwa que inspira esta historia.", "Manhwa"),
])
def test_type_needs_specific_evidence_not_manga_section(description, expected):
    assert details(description=description).work_type == expected


def test_novel_is_not_classified_as_the_comic_it_mentions():
    value = details(title="EJEMPLO 1 (NOVELA)", description="La novela que inspiró el famoso manhwa.")
    assert value.work_type is None
    assert "Novela" in value.classification_note


def test_compares_filled_fields_without_mutating_saved_product():
    original = product(work_type="Manhua", description="Texto revisado manualmente.", author="Mi autor",
                       book_format="Tapa dura", pages=99, series="Mi colección", volume="7")
    result = lookup.NormaLookupResult(ISBN, "found", details(), URL)
    changes, note = norma_review_changes(original, result)
    for field in ("work_type", "description", "author", "book_format", "pages", "series", "volume"):
        assert changes[field] == getattr(result.details, field)
    assert "yumekai_status" not in changes
    assert original["work_type"] == "Manhua" and original["pages"] == 99
    assert "retail_price" not in changes and "sale_price" not in changes


def test_empty_fields_are_proposed_and_zero_price_gets_five_percent_discount():
    result = lookup.NormaLookupResult(ISBN, "found", details(), URL)
    changes, _ = norma_review_changes(product(retail_price="0", sale_price="0"), result)
    assert changes["work_type"] == "Manhwa" and changes["volume"] == "1"
    assert changes["retail_price"] == "14.95" and changes["sale_price"] == "14.20"
    assert "yumekai_status" not in changes and "isbn" not in changes and "title" not in changes


@pytest.mark.parametrize("status", ["not_found", "error", "cancelled", "blocked"])
def test_failed_queries_never_change_any_field(status):
    assert norma_review_changes(product(), lookup.NormaLookupResult(ISBN, status))[0] == {}


def test_candidate_with_other_edition_is_rejected_before_matching_one(monkeypatch):
    first = URL + "-otra-edicion"
    client = Mock()
    client.search.return_value = [first, URL]
    client.fetch.side_effect = lambda url: (markup(isbn=OTHER if url == first else ISBN), url, "utf-8")
    monkeypatch.setattr(lookup, "_NormaClient", lambda stop: client)
    result = lookup.lookup_norma_isbn(ISBN, title="EJEMPLO 1")
    assert result.status == "found" and result.url == URL
    assert client.fetch.call_count == 2


def test_title_fallback_cannot_authorize_another_isbn(monkeypatch):
    client = Mock()
    client.search.side_effect = [[], [URL]]
    client.fetch.return_value = (markup(isbn=OTHER), URL, "utf-8")
    monkeypatch.setattr(lookup, "_NormaClient", lambda stop: client)
    result = lookup.lookup_norma_isbn(ISBN, title="EJEMPLO 1")
    assert result.status == "not_found" and result.details is None


def test_search_checks_response_shape_and_only_reads_official_product_urls(monkeypatch):
    client = lookup._NormaClient(Event())
    search = b'<input id="buscadorInput" data-token="public-session-token">'
    payload = {"album": [{"slug": "https://unrelated.example/ficha/other"},
                          {"slug": "/autor/not-a-book"}, {"slug": URL}]}
    fetch = Mock(side_effect=[(search, lookup.BASE_URL, "utf-8"),
                              (json.dumps(payload).encode(), lookup.BASE_URL, "utf-8")])
    monkeypatch.setattr(client, "fetch", fetch)
    assert client.search(ISBN) == [URL]
    assert fetch.call_args.kwargs["referer"] == lookup.BASE_URL


def test_cancellation_stops_before_network(monkeypatch):
    stop = Event()
    stop.set()
    factory = Mock()
    monkeypatch.setattr(lookup, "_NormaClient", factory)
    with pytest.raises(lookup.NormaLookupCancelled):
        lookup.lookup_norma_isbn(ISBN, stop)
    factory.assert_not_called()


def test_worker_blocks_non_norma_and_never_queries_network(app, monkeypatch):
    query = Mock()
    monkeypatch.setattr("yumekai_importer.ui.workers.norma_recheck_worker.ZonaLibrosClient", query)
    worker = NormaRecheckWorker({ISBN: product(publisher="Panini")})
    worker.run()
    assert worker.error and worker.results[ISBN].status == "blocked"
    query.assert_not_called()


def test_worker_reports_cancelled_results_for_every_unstarted_product(app, monkeypatch):
    worker = NormaRecheckWorker({ISBN: product(), OTHER: product(isbn=OTHER)})
    worker.stop_requested.set()
    worker.run()
    assert set(worker.results) == {ISBN, OTHER}
    assert all(result.status == "cancelled" for result in worker.results.values())


def test_norma_menu_routing_busy_state_and_stop_are_independent_of_sd(app):
    window = PendingReviewWindow()
    window._products["pending_review"] = {ISBN: product()}
    window._selected = {ISBN}
    window._update_actions()
    assert window._supplier_menus["norma"].menuAction().isEnabled()
    assert window._norma_button.isEnabled() and not window._sd_button.isEnabled()
    worker = SimpleNamespace(stop_requested=Event())
    window._norma_worker = worker
    window._update_actions()
    assert window._busy and window._stop_sd_button.isEnabled()
    window._stop_supplier_check()
    assert worker.stop_requested.is_set()
    window._norma_worker = None
    window._issues_exported = True
    window.close()


def test_norma_completion_uses_existing_field_review_and_preserves_draft_backup(app, tmp_path):
    window = PendingReviewWindow(draft_backup=ReviewDraftBackup(tmp_path / "recovery.json"))
    window._products["pending_review"] = {ISBN: product()}
    result = lookup.NormaLookupResult(ISBN, "found", details(), URL)
    window._norma_worker = SimpleNamespace(
        products={ISBN: product()}, results={ISBN: result}, error=None, deleteLater=Mock())
    window._retry_drafts = Mock()
    window._finish_norma_recheck()
    assert window._norma_worker is None and not window._busy
    assert window._drafts[ISBN]["changes"]["work_type"] == "Manhwa"
    assert "yumekai_status" not in window._drafts[ISBN]["changes"]
    window._retry_drafts.assert_called_once_with(keys=[ISBN])
    assert window._supplier_records("norma")[ISBN]["supplier"] == "norma"
    assert not window._supplier_records("sd")
    saved = window._draft_backup.load()
    assert saved["sd_results"][ISBN]["supplier"] == "norma"
    assert saved["drafts"][ISBN]["changes"]["work_type"] == "Manhwa"
    window._drafts.clear()
    window._draft_backup.clear()
    window.close()


def test_sd_selection_remains_enabled_for_sd_publishers(app):
    window = PendingReviewWindow()
    window._products["pending_review"] = {ISBN: product(publisher="Panini")}
    window._selected = {ISBN}
    window._update_actions()
    assert window._sd_button.isEnabled() and not window._norma_button.isEnabled()
    window.close()


def test_cancelling_norma_field_review_keeps_drafts_without_writing(app, monkeypatch):
    window = PendingReviewWindow()
    window._products["pending_review"] = {ISBN: product()}
    result = lookup.NormaLookupResult(ISBN, "found", details(), URL)
    window._norma_worker = SimpleNamespace(
        products={ISBN: product()}, results={ISBN: result}, error=None, deleteLater=Mock())
    review = Mock(return_value=None)
    monkeypatch.setattr("yumekai_importer.ui.windows.pending_review_window.review_changes", review)
    window._start_action = Mock()
    window._finish_norma_recheck()
    assert review.call_args.args[0][ISBN]["changes"]["work_type"] == "Manhwa"
    assert window._drafts[ISBN]["changes"]["pages"] == 320
    window._start_action.assert_not_called()
    window._drafts.clear()
    window.close()


def test_accepting_only_pages_excludes_other_norma_proposals_from_save(app, monkeypatch):
    window = PendingReviewWindow()
    window._products["pending_review"] = {ISBN: product()}
    result = lookup.NormaLookupResult(ISBN, "found", details(), URL)
    window._norma_worker = SimpleNamespace(
        products={ISBN: product()}, results={ISBN: result}, error=None, deleteLater=Mock())
    monkeypatch.setattr("yumekai_importer.ui.windows.pending_review_window.review_changes",
                        lambda *args, **kwargs: {ISBN: {"pages": 320}})
    window._start_action = Mock()
    window._finish_norma_recheck()
    action, entries = window._start_action.call_args.args
    assert action == "save" and entries[0]["changes"] == {"pages": 320}
    assert window._drafts[ISBN]["changes"] == {"pages": 320}
    window._drafts.clear()
    window.close()


def test_sd_completion_keeps_original_proposals_and_does_not_review_norma_drafts(app):
    from yumekai_importer.importers.sd.lookup import SdLookupResult
    from yumekai_importer.importers.sd.details import SdDetails
    from yumekai_importer.catalog.sd_review import sd_review_changes
    original = product(publisher="Panini")
    value = SdDetails("Manga", "Shonen", 192, "Cartoné", "Autor SD", "Sinopsis SD")
    result = SdLookupResult(ISBN, "found", True, value)
    expected, _ = sd_review_changes(original, result)
    window = PendingReviewWindow()
    window._products["pending_review"] = {ISBN: original}
    window._sd_results = {OTHER: {"supplier": "norma", "changed": True, "note": "Anterior"}}
    window._sd_worker = SimpleNamespace(products={ISBN: original}, results={ISBN: result},
                                       stock_only=False, error=None, deleteLater=Mock())
    window._retry_drafts = Mock()
    window._finish_sd_recheck()
    assert window._drafts[ISBN]["changes"] == expected
    assert window._supplier_records("norma")[OTHER]["note"] == "Anterior"
    window._retry_drafts.assert_called_once_with(keys=[ISBN])
    window._drafts.clear()
    window.close()
