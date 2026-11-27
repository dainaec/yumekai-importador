from dataclasses import replace
import json
from threading import Event
from types import SimpleNamespace
from unittest.mock import Mock
from urllib.error import HTTPError

import pytest
from PySide6.QtWidgets import QApplication

from yumekai_importer.catalog.norma_review import norma_review_changes
from yumekai_importer.importers import mangaupdates as mu
from yumekai_importer.importers.norma.lookup import NormaDetails, NormaLookupResult
from yumekai_importer.storage.mangaupdates_cache import MangaUpdatesCache
from yumekai_importer.ui.workers import norma_recheck_worker as workers
from yumekai_importer.ui.windows.pending_review_window import PendingReviewWindow


ISBN = "9788467968705"
MU_URL = "https://www.mangaupdates.com/series/example/ejemplo"
ZONE_URL = "https://norma.zonalibros.com/Clientes/Libro.aspx?id=1"


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


def series(identifier=1, *, title="Ejemplo", author="AZUMA Kiyohiko", kind="Manga", genres=("Shounen",), aliases=()):
    return {"series_id": identifier, "title": title, "type": kind, "url": MU_URL,
            "associated": [{"title": item} for item in aliases],
            "authors": [{"name": author, "type": "Author"}],
            "genres": [{"genre": item} for item in genres]}


def client_for(tmp_path, records):
    client = mu.MangaUpdatesClient(cache=MangaUpdatesCache(tmp_path / "cache.json"))
    def request(path, **kwargs):
        if path == "/series/search":
            return {"results": [{"record": record, "hit_title": record["title"]} for record in records]}
        return next(record for record in records if str(record["series_id"]) == path.rsplit("/", 1)[1])
    client._request = Mock(side_effect=request)
    return client


def product(**changes):
    return {"isbn": ISBN, "title": "¡YOTSUBA! 01", "publisher": "NORMA", "series": "¡YOTSUBA!",
            "author": "Kiyohiko Azuma", "retail_price": "9.00", "sale_price": "8.55",
            "review_status": "pending_review", "yumekai_status": "outofstock", **changes}


def zone(**changes):
    return NormaLookupResult(ISBN, "found", NormaDetails(title="¡YOTSUBA! 01", author="Kiyohiko Azuma",
        series="¡YOTSUBA!", pages=224, description="Sinopsis de prueba.",
        book_format="Rústica con sobrecubierta", availability="Stock: Sí / Disponible para su envío",
        yumekai_status="yk_on_demand", **changes), ZONE_URL)


def metadata(**changes):
    return mu.MangaUpdatesResult("matched", work_type="Manga", demographic="Shonen", series_id=1,
        title="Yotsuba to!", url=MU_URL, message="MangaUpdates: coincidencia confirmada. " + MU_URL, **changes)


def metadata_stub(monkeypatch, value):
    client = SimpleNamespace(lookup=Mock(return_value=value), close=Mock(), cache=SimpleNamespace(warning=""))
    factory = Mock(return_value=client)
    monkeypatch.setattr(workers, "MangaUpdatesClient", factory)
    return client, factory


@pytest.mark.parametrize("query,author,record,expected", [
    ("¡Yotsuba!", "Kiyohiko Azuma", series(title="Yotsuba to!", aliases=("Yotsuba!",)), ("Manga", "Shonen")),
    ("Solo Leveling", "DUBU (REDICE STUDIO) / CHUGONG", series(title="Solo Leveling", author="Chugong", kind="Manhwa"), ("Manhwa", None)),
    ("Here U Are", "D. Jun", series(title="Here U Are", author="D. Jun", kind="Manhua", genres=("Shounen Ai",)), ("Manhua", None)),
])
def test_exact_alias_and_author_allow_each_comic_type(tmp_path, query, author, record, expected):
    result = client_for(tmp_path, [record]).lookup(query, author)
    assert result.status == "matched" and (result.work_type, result.demographic) == expected
    assert "MangaUpdates" in result.message and result.url in result.message


@pytest.mark.parametrize("query,author", [("Ejemplo", "Otra Autora"), ("Ejemplos", "Kiyohiko Azuma"), ("Ejemplo", "K. A.")])
def test_similar_title_wrong_author_or_initials_do_not_confirm(tmp_path, query, author):
    result = client_for(tmp_path, [series()]).lookup(query, author)
    assert result.status != "matched" and result.work_type is None and result.demographic is None


@pytest.mark.parametrize("title", ["Ejemplo (NOVELA)", "Ejemplo ARTBOOK", "Guía de Ejemplo", "El arte de Ejemplo"])
def test_novels_and_illustrated_books_are_never_classified_as_the_comic(tmp_path, title):
    client = client_for(tmp_path, [series()])
    assert client.lookup(title, "Kiyohiko Azuma").status == "unverified"
    client._request.assert_not_called()


def test_novel_record_with_same_author_and_title_is_rejected(tmp_path):
    client = client_for(tmp_path, [series(kind="Novel")])
    assert client.lookup("Ejemplo", "Kiyohiko Azuma").status == "not_found"
    assert client._request.call_count == 1


@pytest.mark.parametrize("genres,expected", [
    (("Comedy", "Horror", "Action"), None), (("Shounen",), "Shonen"), (("Shoujo",), "Shōjo"),
    (("Seinen",), "Seinen"), (("Josei",), "Josei"), (("Kodomo",), "Kodomo"),
    (("Shounen", "Seinen"), None), (("Shoujo", "Yaoi"), "Yaoi / BL"),
    (("Shounen Ai",), "Yaoi / BL"), (("Shoujo Ai", "Josei"), "Yuri"),
    (("Yaoi", "Yuri"), None), (("Lolicon", "Shotacon"), None),
])
def test_only_approved_unambiguous_demographics_are_used(genres, expected):
    assert mu._demographic(series(genres=genres)) == expected


@pytest.mark.parametrize("count", [2, 4])
def test_ambiguous_titles_never_propose_a_type_even_when_candidate_limit_is_reached(tmp_path, count):
    result = client_for(tmp_path, [series(index) for index in range(1, count + 1)]).lookup("Ejemplo", "Kiyohiko Azuma")
    assert result.status == "ambiguous" and result.work_type is None and result.demographic is None


def test_collection_cache_is_shared_between_volumes_and_later_runs(tmp_path):
    client = client_for(tmp_path, [series()])
    first = client.lookup("¡Ejemplo!", "Kiyohiko Azuma")
    assert first.status == "matched"
    calls = client._request.call_count
    assert client.lookup("EJEMPLO", "AZUMA Kiyohiko") == first
    assert client._request.call_count == calls
    client.close()
    other = mu.MangaUpdatesClient(cache=MangaUpdatesCache(tmp_path / "cache.json"))
    other._request = Mock(side_effect=AssertionError("A cached collection must not query the service"))
    assert other.lookup("Ejemplo", "Kiyohiko Azuma") == first
    other._request.assert_not_called()


def test_expired_cache_refreshes_metadata(tmp_path, monkeypatch):
    clock = Mock(return_value=1000)
    monkeypatch.setattr("yumekai_importer.storage.mangaupdates_cache.time.time", clock)
    client = client_for(tmp_path, [series()])
    client.lookup("Ejemplo", "Kiyohiko Azuma")
    client.close()
    clock.return_value = 1000 + 31 * mu.DAY
    other = client_for(tmp_path, [series(genres=("Seinen",))])
    assert other.lookup("Ejemplo", "Kiyohiko Azuma").demographic == "Seinen"
    assert other._request.call_count == 2


def test_corrupt_cache_entries_do_not_prevent_fresh_classification(tmp_path):
    path = tmp_path / "cache.json"
    path.write_text(json.dumps({"version": 1, "entries": {"bad": None, "bad2": {"saved_at": "bad"}}}))
    client = client_for(tmp_path, [series()])
    client.cache.MAX_ENTRIES = 1
    assert client.lookup("Ejemplo", "Kiyohiko Azuma").status == "matched"
    client.close()
    assert len(json.loads(path.read_text())["entries"]) == 1


def test_unwritable_cache_keeps_the_result(tmp_path):
    client = client_for(tmp_path, [series()])
    client.cache.path = tmp_path  # A directory cannot be replaced with a cache file.
    assert client.lookup("Ejemplo", "Kiyohiko Azuma").status == "matched"
    client.close()
    assert client.cache.warning and tmp_path.is_dir()


def test_http_rate_limit_disables_further_queries_for_this_batch(tmp_path):
    client = mu.MangaUpdatesClient(cache=MangaUpdatesCache(tmp_path / "cache.json"))
    client.opener = Mock()
    client.opener.open.side_effect = HTTPError(mu.API_URL + "/series/search", 429, "Rate limited", {}, None)
    assert client.lookup("Ejemplo", "Kiyohiko Azuma").status == "error"
    assert client.lookup("Otro título", "Otra Autora").status == "error"
    assert client.opener.open.call_count == 1


def test_cancellation_before_query_and_during_throttle_make_no_request(tmp_path):
    stop = Event()
    client = mu.MangaUpdatesClient(stop, cache=MangaUpdatesCache(tmp_path / "cache.json"))
    client.opener = Mock()
    stop.set()
    with pytest.raises(mu.MangaUpdatesCancelled):
        client.lookup("Ejemplo", "Kiyohiko Azuma")
    stop.clear()
    client.stop = Mock(is_set=Mock(return_value=False), wait=Mock(return_value=True))
    with pytest.raises(mu.MangaUpdatesCancelled):
        client._request("/series/1")
    client.opener.open.assert_not_called()


def test_requests_are_spaced_and_use_public_metadata_only(tmp_path, monkeypatch):
    client = mu.MangaUpdatesClient(cache=MangaUpdatesCache(tmp_path / "cache.json"))
    client._last_request = 10.0
    monkeypatch.setattr(mu.time, "monotonic", lambda: 10.25)
    client.stop = Mock(is_set=Mock(return_value=False), wait=Mock(return_value=False))
    response = Mock()
    response.geturl.return_value = mu.API_URL + "/series/search"
    response.read.return_value = b'{"results": []}'
    client.opener = Mock()
    client.opener.open.return_value.__enter__ = Mock(return_value=response)
    client.opener.open.return_value.__exit__ = Mock(return_value=False)
    client._request("/series/search", data={"search": "Ejemplo"})
    client.stop.wait.assert_called_once_with(0.75)
    request = client.opener.open.call_args.args[0]
    assert request.get_method() == "POST"
    assert json.loads(request.data) == {"search": "Ejemplo"}
    assert not request.has_header("Authorization") and not request.has_header("Cookie")


def test_worker_enrichment_preserves_edition_fields_and_uses_existing_review(app, monkeypatch):
    source = zone()
    client, _ = metadata_stub(monkeypatch, metadata())
    worker = workers.NormaRecheckWorker({ISBN: product()})
    enriched = worker._complete_classification(product(), source)
    assert replace(enriched.details, work_type=None, demographic=None, classification_note="") == source.details
    assert enriched.isbn == source.isbn and enriched.url == source.url
    changes, note = norma_review_changes(product(), enriched)
    assert changes["work_type"] == "Manga" and changes["demographic"] == "Shonen"
    assert changes["pages"] == 224 and changes["yumekai_status"] == "yk_on_demand"
    assert "MangaUpdates" in note and MU_URL in note
    client.lookup.assert_called_once_with("¡YOTSUBA!", "Kiyohiko Azuma")


@pytest.mark.parametrize("current", [
    {"work_type": "Manga", "demographic": "Seinen"}, {"work_type": "Manhwa"},
    {"work_type": "Manhua"}, {"work_type": "Artbooks, guías y novelas"},
])
def test_worker_rechecks_filled_classification_and_skips_illustrated_books(app, monkeypatch, current):
    _, factory = metadata_stub(monkeypatch, metadata())
    worker = workers.NormaRecheckWorker({ISBN: product(**current)})
    source = zone()
    enriched = worker._complete_classification(product(**current), source)
    if current["work_type"] == "Artbooks, guías y novelas":
        assert enriched is source
        factory.assert_not_called()
    else:
        assert enriched.details.work_type == "Manga" and enriched.details.demographic == "Shonen"
        factory.assert_called_once_with(worker.stop_requested, refresh=True)


@pytest.mark.parametrize("source", [zone(work_type="Manhwa"), zone(work_type="Manhua"),
    replace(zone(), details=replace(zone().details, title="YOTSUBA ARTBOOK")),
    zone(classification_note="Novela o libro ilustrado: revisar el tipo de obra manualmente.")])
def test_worker_preserves_explicit_norma_types_and_novel_detection(app, monkeypatch, source):
    _, factory = metadata_stub(monkeypatch, metadata())
    worker = workers.NormaRecheckWorker({ISBN: product()})
    assert worker._complete_classification(product(), source) is source
    factory.assert_not_called()


def test_worker_uses_title_parser_if_collection_is_missing(app, monkeypatch):
    client, _ = metadata_stub(monkeypatch, metadata())
    worker = workers.NormaRecheckWorker({ISBN: product(series=None)})
    source = replace(zone(), details=replace(zone().details, series=None))
    worker._complete_classification(product(series=None), source)
    assert mu.metadata_key(client.lookup.call_args.args[0]) == "yotsuba"


def test_worker_compares_saved_demographics_and_reports_source_disagreement(app, monkeypatch):
    metadata_stub(monkeypatch, metadata())
    worker = workers.NormaRecheckWorker({ISBN: product()})
    enriched = worker._complete_classification(product(), zone(demographic="Seinen"))
    changes, note = norma_review_changes(product(demographic="Josei"), enriched)
    assert changes["work_type"] == "Manga" and changes["demographic"] == "Seinen"
    assert enriched.details.demographic == "Seinen" and "difiere" in note


@pytest.mark.parametrize("kind", ["Manhwa", "Manhua"])
def test_non_manga_result_does_not_receive_demography(app, monkeypatch, kind):
    metadata_stub(monkeypatch, replace(metadata(), work_type=kind, demographic=None))
    worker = workers.NormaRecheckWorker({ISBN: product()})
    changes, _ = norma_review_changes(product(), worker._complete_classification(product(), zone()))
    assert changes["work_type"] == kind and "demographic" not in changes


@pytest.mark.parametrize("status", ["not_found", "ambiguous", "error"])
def test_unverified_metadata_keeps_all_norma_fields_and_reports_reason(app, monkeypatch, status):
    metadata_stub(monkeypatch, mu.MangaUpdatesResult(status, message="MangaUpdates: revisar manualmente."))
    worker = workers.NormaRecheckWorker({ISBN: product()})
    source = zone()
    enriched = worker._complete_classification(product(), source)
    assert replace(enriched.details, classification_note="") == source.details
    assert "MangaUpdates" in norma_review_changes(product(), enriched)[1]


def test_metadata_exception_cannot_stop_norma_batch_or_discard_fresh_stock(app, monkeypatch):
    client, factory = metadata_stub(monkeypatch, metadata())
    client.lookup.side_effect = RuntimeError("Unexpected metadata response")
    portal = Mock()
    portal.lookup.side_effect = lambda isbn: replace(zone(), isbn=isbn)
    monkeypatch.setattr(workers, "ZonaLibrosClient", lambda stop: portal)
    products = {ISBN: product(), "second": product(isbn="9788467980080")}
    worker = workers.NormaRecheckWorker(products, credentials=SimpleNamespace())
    worker.run()
    assert worker.error is None and portal.lookup.call_count == 2
    assert all(result.status == "found" and result.details.yumekai_status == "yk_on_demand" for result in worker.results.values())
    assert worker.credentials is None
    factory.assert_called_once()
    client.close.assert_called_once()
    portal.close.assert_called_once()


def test_cancelling_metadata_retains_completed_zone_result(app, monkeypatch):
    client, _ = metadata_stub(monkeypatch, metadata())
    worker = workers.NormaRecheckWorker({ISBN: product(), "second": product(isbn="9788467980080")})
    portal = Mock()
    portal.lookup.return_value = zone()
    monkeypatch.setattr(workers, "ZonaLibrosClient", lambda stop: portal)
    def cancel(*args):
        worker.stop_requested.set()
        raise mu.MangaUpdatesCancelled()
    client.lookup.side_effect = cancel
    worker.run()
    assert worker.results[ISBN] == zone() and worker.results["second"].status == "cancelled"
    assert portal.lookup.call_count == 1


def test_classification_uses_field_confirmation_before_save(app, monkeypatch):
    metadata_stub(monkeypatch, metadata())
    worker = workers.NormaRecheckWorker({ISBN: product()})
    enriched = worker._complete_classification(product(), zone())
    window = PendingReviewWindow()
    window._products["pending_review"] = {ISBN: product()}
    window._norma_worker = SimpleNamespace(products={ISBN: product()}, results={ISBN: enriched}, error=None, deleteLater=Mock())
    selected = {ISBN: {"work_type": "Manga", "demographic": "Shonen"}}
    monkeypatch.setattr("yumekai_importer.ui.windows.pending_review_window.review_changes", lambda *a, **k: selected)
    window._start_action = Mock()
    window._finish_norma_recheck()
    action, entries = window._start_action.call_args.args
    assert action == "save" and entries[0]["changes"] == selected[ISBN]
    assert "pages" not in entries[0]["changes"] and "yumekai_status" not in entries[0]["changes"]
    window._drafts.clear()
    window.close()
