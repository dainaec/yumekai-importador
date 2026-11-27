"""Import contracts for the common reader, supplier rules and future profiles."""
from decimal import Decimal

from openpyxl import Workbook
import pytest

from yumekai_importer.catalog.product import YumekaiStatus
from yumekai_importer.importers.catalog_excel import read_catalog_excel, read_catalog_excel_with_supplier
from yumekai_importer.importers.excel_profile import ExcelProfile
from yumekai_importer.importers.excel_profiles import EXCEL_PROFILES
from yumekai_importer.importers.norma.excel import read_norma_excel
from yumekai_importer.importers.sd.excel import read_sd_excel
from yumekai_importer.ui.windows.import_window import _build_import_warnings


ISBN = "9788467945850"
OTHER = "9788467968705"


def workbook(tmp_path, rows, *, preamble=(), cover=False):
    book = Workbook()
    sheet = book.active
    if cover:
        sheet.append(["Portada del catálogo"])
        sheet = book.create_sheet("Catálogo")
    for row in (*preamble, *rows):
        sheet.append(row)
    path = tmp_path / "catalogo.xlsx"
    book.save(path)
    return path


def sd_file(tmp_path, *, status="SIN STOCK", image="portada 01.jpg", distributor="SD"):
    return workbook(tmp_path, [
        ["Distribuidor", "Titulo", "Autor", "Editorial", "ISBN", "Ref", "PVP", "Imagen", "Sinopsis", "Estado"],
        [distributor, "MI SERIE 01 (COMIC)", " Autor SD ", "Panini", ISBN, " REF-1 ", "14,95", image, " Sinopsis SD ", status],
        [distributor, "MI SERIE 02 (COMIC)", "Autor B", "Panini", OTHER, "REF-2", 10, None, "Otra sinopsis", status],
    ])


def norma_file(tmp_path, *, status="NORMAL/DISPONBLE", image="https://example.com/cover.jpg"):
    return workbook(tmp_path, [
        ["Distribuidor", "Título", "Autoría", "ISBN", "PVP", "Imagen", "Sinopsis", "Estado"],
        ["Norma Editorial", "MI SERIE 01 (COMIC)", " Autora Norma ", ISBN, "14,95", image, " Sinopsis Norma ", status],
    ])


def test_sd_keeps_its_price_title_reference_image_and_unchecked_availability(tmp_path):
    supplier, result = read_catalog_excel_with_supplier(sd_file(tmp_path))
    assert supplier == "sd" and not result.issues
    product = result.products[0]
    assert product.title == "MI SERIE 01" and product.series == "MI SERIE" and product.volume == "1"
    assert product.retail_price == Decimal("14.95") and product.sale_price == Decimal("14.20")
    assert product.author == " Autor SD " and product.description == " Sinopsis SD "
    assert product.yumekai_status is None
    assert product.image_url == "https://imagenes.zonalibros.com/img/58/portada%2001.jpg"
    assert result.sd_references[ISBN] == "REF-1"
    assert result.source_rows[2]["Estado"] == "SIN STOCK"
    assert result.products_by_row[2] is product


@pytest.mark.parametrize("status", ["HAY EXISTENCIAS", "DESCATALOGADO", "NORMAL/DISPONBLE", "Consultar disponibilidad"])
def test_norma_status_rules_are_never_applied_to_sd(tmp_path, status):
    result = read_catalog_excel(sd_file(tmp_path, status=status))
    assert all(product.yumekai_status is None for product in result.products)
    assert not result.issues


@pytest.mark.parametrize("image,expected", [(None, None), (".", None), ("- -", None),
    ("folder/cover.jpg", None), ("https://example.com/cover.jpg", None),
    ("portada.jpg", "https://imagenes.zonalibros.com/img/58/portada.jpg")])
def test_sd_image_rules_keep_their_previous_meaning(tmp_path, image, expected):
    assert read_catalog_excel(sd_file(tmp_path, image=image)).products[0].image_url == expected


@pytest.mark.parametrize("status,expected,issue", [
    ("NORMAL/DISPONBLE", YumekaiStatus.ON_DEMAND, False),
    ("AGOTADO", YumekaiStatus.OUT_OF_STOCK, False),
    ("EN REIMPRESIÓN / PDTE.", None, False),
    ("DESCATALOGADO", None, True), ("CANCELADO", None, True),
    ("SIN EXISTENCIAS INDEFINDAMENTE", None, True),
    ("SE PUEDE RESERVAR", YumekaiStatus.ON_BACKORDER, False),
    ("HAY EXISTENCIAS", YumekaiStatus.IN_STOCK, False),
    ("OTRO ESTADO", None, True), (None, None, True),
])
def test_norma_keeps_the_statuses_from_the_uploaded_project(tmp_path, status, expected, issue):
    supplier, result = read_catalog_excel_with_supplier(norma_file(tmp_path, status=status))
    assert supplier == "norma" and result.products[0].yumekai_status == expected
    assert any(value.field == "Estado" for value in result.issues) == issue
    assert result.products[0].publisher == "Norma Editorial"
    assert result.products[0].author == "Autora Norma"
    assert result.products[0].description == "Sinopsis Norma"


def test_all_norma_guardable_incidents_still_reach_the_save_review(tmp_path):
    result = read_catalog_excel(norma_file(tmp_path, status="DESCATALOGADO", image="imagen-sin-url.jpg"))
    candidates = {product.isbn: product for product in result.products}
    warnings = _build_import_warnings(result, candidates, include_import_issues=True)
    assert len(warnings) == 1
    text = " ".join(warnings[ISBN]["issues"])
    assert "DESCATALOGADO" in text and "imagen-sin-url.jpg" in text
    assert {issue.field for issue in result.issues} == {"Estado", "Imagen"}


def test_common_header_mapping_handles_order_accents_preamble_and_cover_sheet(tmp_path):
    path = workbook(tmp_path, [["Precio de venta", "Proveedor", "Nombre", "EAN-13", "Autoría"],
                              [9, "SD Distribuciones", "SERIE 01", ISBN, "Autora"]],
                    preamble=[["Listado de publicaciones"], []], cover=True)
    supplier, result = read_catalog_excel_with_supplier(path)
    assert supplier == "sd" and result.products[0].retail_price == Decimal("9.00")
    assert result.products_by_row[4].isbn == ISBN
    assert result.source_rows[4]["EAN-13"] == ISBN


def test_norma_legacy_headers_and_unlabelled_sd_remain_detectable(tmp_path):
    path = workbook(tmp_path, [["ISBN", "TÍTULO", "AUTORÍA", "PVP", "Estado"],
                              [ISBN, "SERIE 01", "Autora", 9, "AGOTADO"]])
    assert read_catalog_excel_with_supplier(path)[0] == "norma"
    path = workbook(tmp_path, [["ISBN", "Titulo", "Autor", "PVP"], [ISBN, "SERIE 01", "Autora", 9]])
    assert read_catalog_excel_with_supplier(path)[0] == "sd"
    assert read_catalog_excel_with_supplier(sd_file(tmp_path, distributor="DIRAC"))[0] == "sd"


def test_codes_prices_duplicates_and_original_rows_use_the_shared_validations(tmp_path):
    path = workbook(tmp_path, [["Distribuidor", "Titulo", "ISBN", "PVP"],
        ["SD", "SERIE 01", ISBN, 0], ["SD", "SERIE 02", ISBN, "no es precio"],
        ["SD", "OTRA OBRA", "CODIGO-X", None], ["SD", "SIN ISBN", None, 9]])
    result = read_catalog_excel(path)
    assert len(result.products) == 3
    assert {2, 3, 4, 5} == set(result.source_rows)
    assert {2, 3, 4} == set(result.products_by_row)
    assert any(issue.row == 3 and "también aparece en la fila 2" in issue.message for issue in result.issues)
    assert any(issue.row == 4 and issue.field == "ISBN" for issue in result.issues)
    assert any(issue.row == 5 and issue.field == "ISBN" for issue in result.issues)
    assert result.products[2].isbn == "CODIGO-X"


def test_mixed_suppliers_and_duplicate_canonical_columns_fail_before_loading(tmp_path):
    path = workbook(tmp_path, [["Distribuidor", "Titulo", "ISBN", "PVP"],
                              ["SD", "SERIE 01", ISBN, 9], ["Norma", "SERIE 02", OTHER, 9]])
    with pytest.raises(ValueError, match="SD y de Norma"):
        read_catalog_excel(path)
    path = workbook(tmp_path, [["ISBN", "EAN", "Titulo", "PVP"], [ISBN, OTHER, "SERIE 01", 9]])
    with pytest.raises(ValueError, match="mismo campo"):
        read_catalog_excel(path)


def test_supplier_entry_points_delegate_to_the_common_reader(tmp_path):
    assert read_sd_excel(sd_file(tmp_path)).products[0].isbn == ISBN
    assert read_norma_excel(norma_file(tmp_path)).products[0].yumekai_status == YumekaiStatus.ON_DEMAND
    with pytest.raises(ValueError, match="otro distribuidor"):
        read_sd_excel(norma_file(tmp_path))


def test_a_new_profile_can_add_its_own_columns_without_changing_the_engine(tmp_path, monkeypatch):
    example = ExcelProfile(code="example", name="Proveedor de ejemplo", distributor_aliases=("Ejemplo",),
        column_aliases={"ISBN": ("Código libro",), "TITULO": ("Nombre obra",), "PVP": ("Precio",)},
        default_publisher="Editorial de ejemplo")
    monkeypatch.setitem(EXCEL_PROFILES, "example", example)
    path = workbook(tmp_path, [["Proveedor", "Código libro", "Nombre obra", "Precio"],
                              ["Ejemplo", ISBN, "SERIE 01", "10,00"]])
    supplier, result = read_catalog_excel_with_supplier(path)
    assert supplier == "example" and result.products[0].retail_price == Decimal("10.00")
    assert result.products[0].publisher == "Editorial de ejemplo"


def test_another_profiles_price_alias_cannot_turn_sd_cost_into_pvp(tmp_path, monkeypatch):
    monkeypatch.setitem(EXCEL_PROFILES, "example", ExcelProfile(
        code="example", name="Ejemplo", distributor_aliases=("Ejemplo",), column_aliases={"PVP": ("Precio",)}))
    path = workbook(tmp_path, [["Distribuidor", "ISBN", "Titulo", "Precio"], ["SD", ISBN, "SERIE 01", 4]])
    with pytest.raises(ValueError, match="Faltan columnas"):
        read_catalog_excel(path)


def test_a_profile_can_be_selected_explicitly_without_replacing_a_declared_supplier(tmp_path):
    path = workbook(tmp_path, [["ISBN", "Titulo", "PVP", "Estado"], [ISBN, "SERIE 01", 9, "AGOTADO"]])
    supplier, result = read_catalog_excel_with_supplier(path, supplier="norma")
    assert supplier == "norma" and result.products[0].yumekai_status == YumekaiStatus.OUT_OF_STOCK
    with pytest.raises(ValueError, match="no registrado"):
        read_catalog_excel(path, supplier="missing")
