from unittest.mock import Mock
import pytest
from yumekai_importer.catalog.suppliers import supplier_for_publisher, supplier_block_reason
from yumekai_importer.ui.workers.sd_recheck_worker import SdRecheckWorker


@pytest.mark.parametrize("publisher,supplier", [
    ("Dolmen", "sd"), ("RBA", "sd"), ("Sekai", "sd"), ("Pika", "sd"),
    ("Kibook", "sd"), ("PANINI CÓMICS", "sd"), ("Editorial Ivrea", "sd"), ("Arechi Manga", "sd"),
    ("NORMA EDITORIAL", "norma"), ("Milky Way Ediciones", "milky_way"),
    ("Planeta Cómic", "planeta"), (None, None), ("", None), ("Editorial desconocida", None),
    ("Panini España S.A.", "sd"),
    ("Panini / Norma", None),
])
def test_publisher_routes(publisher, supplier):
    assert supplier_for_publisher(publisher) == supplier


def test_mixed_selection_is_blocked_before_network(app, product, monkeypatch):
    lookup = Mock(side_effect=AssertionError("No debe consultar SD"))
    monkeypatch.setattr("yumekai_importer.ui.workers.sd_recheck_worker.lookup_sd_isbn", lookup)
    worker = SdRecheckWorker({"panini": product, "norma": {**product, "publisher": "Norma"}})
    worker.run()
    assert "Norma" in worker.error
    assert all(row.status == "blocked" for row in worker.results.values())
    lookup.assert_not_called()


def test_blank_publisher_explains_block():
    assert "Sin editorial" in supplier_block_reason({"1": {"publisher": " "}}, "sd")
