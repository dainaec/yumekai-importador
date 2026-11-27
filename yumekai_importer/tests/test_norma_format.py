from PySide6.QtWidgets import QApplication, QDialog
from lxml import html
import pytest

from yumekai_importer.catalog.book_formats import normalize_sd_format, normalize_yumekai_format
from yumekai_importer.catalog.review_fields import BOOK_FORMATS
from yumekai_importer.catalog.norma_review import norma_review_changes
from yumekai_importer.importers.norma.lookup import NormaDetails, NormaLookupResult, parse_norma_details
from yumekai_importer.ui.widgets.product_review_dialog import ProductReviewDialog
from yumekai_importer.ui.windows.pending_review_window import PRODUCT_COLUMNS
from yumekai_importer.catalog.review_workflow import STOCK_LABELS


PLURAL = "Rústica con sobrecubiertas"
CANONICAL = "Rústica con sobrecubierta"
ISBN = "9788467968705"
ZONALIBROS_FORMATS = [
    ("RUS+SOBREC", CANONICAL),
    ("RUS+SOBREC.", CANONICAL),
    ("RUSTICA + SOBRECUB.", CANONICAL),
    ("RUSTICA CON SOBRECUB", CANONICAL),
    ("RUSTICA + 2 SOBRECUB", CANONICAL),
    ("RUSTICA CON SOLAPAS", "Rústica con solapas"),
    ("RUSTICA + SOLAPAS", "Rústica con solapas"),
    ("CARTONE", "Tapa dura"),
]


@pytest.mark.parametrize("value, expected", ZONALIBROS_FORMATS)
def test_zonalibros_formats_match_the_agreed_labels(value, expected):
    assert normalize_yumekai_format(value) == expected


@pytest.mark.parametrize("value, expected", ZONALIBROS_FORMATS)
def test_norma_review_uses_the_agreed_labels_and_compares_filled_formats(value, expected):
    result = NormaLookupResult(ISBN, "found", NormaDetails(book_format=value))
    changes, _ = norma_review_changes({"book_format": None, "retail_price": "9.00"}, result)
    assert changes["book_format"] == expected
    changes, _ = norma_review_changes({"book_format": "Box set", "retail_price": "9.00"}, result)
    assert changes["book_format"] == expected


def test_sd_formats_keep_their_existing_rules():
    assert normalize_sd_format("RUS+SOBREC") == "RUS+SOBREC"
    assert normalize_sd_format("Cartoné con sobrecubierta") == "Tapa dura"
    assert normalize_sd_format("Seinen / Drama") == "Rústica"
    assert normalize_sd_format(None) == "Rústica"


def test_solapas_is_available_in_the_format_selector(app):
    assert "Rústica con solapas" in BOOK_FORMATS
    dialog = ProductReviewDialog({"isbn": ISBN, "title": "Ejemplo 01", "book_format": "RUSTICA + SOLAPAS"},
                                 PRODUCT_COLUMNS, STOCK_LABELS)
    combo = dialog._editors["book_format"]
    assert combo.currentData() == "Rústica con solapas"
    assert combo.findData("RUSTICA + SOLAPAS") == -1
    dialog.accept()
    assert dialog.changes == {"book_format": "Rústica con solapas"}
    dialog.deleteLater()


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


@pytest.mark.parametrize("value", [PLURAL, "RUSTICA CON SOBRECUBIERTAS", "  Rústica con sobrecubiertas  ", CANONICAL])
def test_norma_plural_uses_yumekai_singular(value):
    assert normalize_yumekai_format(value) == CANONICAL


@pytest.mark.parametrize("value", [None, "Tapa dura", "Rústica", "Rústica con doble sobrecubierta", "Box set"])
def test_other_formats_are_preserved(value):
    assert normalize_yumekai_format(value) == value


def test_parser_returns_canonical_format():
    page = html.fromstring(f'''<html><meta charset="utf-8"><div id="mid-col"><h1>Ejemplo 01</h1>
        <div id="features"><div><label>ISBN</label>{ISBN}</div>
        <div><label>FORMATO</label>{PLURAL}</div></div></div></html>'''.encode())
    result = parse_norma_details(page, ISBN, "https://www.normaeditorial.com/ficha/manga/ejemplo")
    assert result.book_format == CANONICAL


@pytest.mark.parametrize("existing", [None, PLURAL])
def test_norma_recheck_proposes_canonical_format_for_new_and_existing_rows(existing):
    result = NormaLookupResult(ISBN, "found", NormaDetails(book_format=PLURAL))
    changes, _ = norma_review_changes({"book_format": existing, "retail_price": "9.00"}, result)
    assert changes["book_format"] == CANONICAL


def test_norma_recheck_proposes_a_different_confirmed_format():
    result = NormaLookupResult(ISBN, "found", NormaDetails(book_format=PLURAL))
    changes, _ = norma_review_changes({"book_format": "Tapa dura", "retail_price": "9.00"}, result)
    assert changes["book_format"] == "Rústica con sobrecubierta"


def test_editor_selects_singular_without_adding_plural_and_saves_the_correction(app):
    product = {"isbn": ISBN, "title": "Ejemplo 01", "book_format": PLURAL}
    dialog = ProductReviewDialog(product, PRODUCT_COLUMNS, STOCK_LABELS)
    combo = dialog._editors["book_format"]
    assert combo.currentData() == CANONICAL
    assert combo.findData(PLURAL) == -1
    assert dialog.changes == {} and product["book_format"] == PLURAL
    dialog.accept()
    assert dialog.result() == QDialog.DialogCode.Accepted
    assert dialog.changes == {"book_format": CANONICAL}
    dialog.deleteLater()


def test_cancelling_editor_does_not_save_the_correction(app):
    dialog = ProductReviewDialog({"isbn": ISBN, "title": "Ejemplo 01", "book_format": PLURAL},
                                 PRODUCT_COLUMNS, STOCK_LABELS)
    dialog.reject()
    assert dialog.changes == {}
    dialog.deleteLater()
