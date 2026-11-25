import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from contextlib import closing
from email.message import Message
from pathlib import Path
from tempfile import TemporaryDirectory
from threading import Event, Lock
from time import sleep
from unittest import TestCase, main
from unittest.mock import patch

from openpyxl import Workbook, load_workbook
from PySide6.QtWidgets import QApplication

from yumekai_importer.importers.import_result import ImportResult
from yumekai_importer.importers.issues_excel import export_import_issues
from yumekai_importer.importers.norma.excel import read_norma_excel
from yumekai_importer.importers.sd.excel import read_sd_excel
from yumekai_importer.importers.sd import stock
from yumekai_importer.importers.sd.details import SdDetails
from yumekai_importer.ui.workers import sd_stock_worker
from yumekai_importer.ui.windows.import_window import ImportWindow


def add(result, row, isbn="9780000000001", title="Manga 1", price=9, **extra):
    result.add_row(row, isbn_value=isbn, title_value=title, price_value=price,
                   author="Autor", publisher="Editorial", description="Sinopsis", **extra)


class ExportTests(TestCase):
    def test_rejected_rows_and_all_source_columns_survive_and_reimport(self):
        result = ImportResult()
        source = {"ISBN": "", "Titulo": "=Título literal", "PVP": "mal",
                  "Ref": "PNI.12", "Extra": "no perder", "Autor": "Ana"}
        add(result, 14, isbn="", title="=Título literal", price="mal", source_data=source)
        self.assertEqual(len(result.issues), 2)
        self.assertFalse(result.products)
        with TemporaryDirectory() as directory:
            path = Path(directory) / "incidencias.xlsx"
            self.assertEqual(export_import_issues(result, path), 1)
            with closing(load_workbook(path)) as book:
                sheet = book["Revisar"]
                self.assertEqual(sheet.max_row, 2)
                self.assertEqual(sheet["B2"].value, "=Título literal")
                self.assertEqual(sheet["B2"].data_type, "s")
                self.assertEqual(sheet["E2"].value, "no perder")
                self.assertIn("Descartada", sheet["H2"].value)
                sheet["A2"] = "9780000000001"
                sheet["C2"] = 9.95
                book.save(path)
            restored = read_sd_excel(path)
            self.assertEqual(len(restored.products), 1)
            self.assertEqual(restored.products[0].title, "=Título literal")
            self.assertEqual(restored.sd_references, {"9780000000001": "PNI.12"})

    def test_duplicate_rows_and_enriched_data_are_kept(self):
        result = ImportResult()
        add(result, 2, isbn="9788419914163", price=None)
        add(result, 3, isbn="9788419914163", price=None)
        result.products_by_row[2].pages = 200
        with TemporaryDirectory() as directory:
            path = Path(directory) / "incidencias.xlsx"
            self.assertEqual(export_import_issues(result, path), 2)
            with closing(load_workbook(path)) as book:
                self.assertEqual(book["Revisar"].max_row, 3)
                rows = list(book["Datos completados"].values)
                self.assertEqual(rows[1][rows[0].index("pages")], 200)
                self.assertEqual(book["Incidencias"].max_row, 4)

    def test_norma_export_can_be_corrected_and_reloaded(self):
        with TemporaryDirectory() as directory:
            source = Path(directory) / "norma.xlsx"
            book = Workbook()
            book.active.append(["ISBN", "TÍTULO", "AUTORÍA", "PVP", "SINOPSIS"])
            book.active.append(["mal", "Título", "Autor", 10, "Texto"])
            book.save(source)
            result = read_norma_excel(source)
            output = Path(directory) / "revision.xlsx"
            export_import_issues(result, output)
            with closing(load_workbook(output)) as book:
                book.active["A2"] = "9780000000002"
                book.save(output)
            self.assertEqual(len(read_norma_excel(output).products), 1)

    def test_failed_export_does_not_replace_existing_file(self):
        result = ImportResult()
        add(result, 2, isbn="")
        with TemporaryDirectory() as directory:
            path = Path(directory) / "existing.xlsx"
            path.write_bytes(b"original")
            with patch("openpyxl.workbook.workbook.Workbook.save", side_effect=OSError("disk")):
                with self.assertRaises(OSError):
                    export_import_issues(result, path)
            self.assertEqual(path.read_bytes(), b"original")
            self.assertEqual(list(Path(directory).iterdir()), [path])


class Response:
    url = "https://www.sddistribuciones.com/AvanzadaPlus.aspx"
    headers = Message()
    headers["Content-Type"] = "text/html; charset=utf-8"
    def __init__(self, content): self.content = content.encode()
    def __enter__(self): return self
    def __exit__(self, *args): pass
    def read(self, limit): return self.content[:limit]


def page(isbn, status="Stock: Sí"):
    return (f'<html><div class="fileproduct"><span class="dvISBN">{isbn}</span>'
            f'<span class="estado">{status}</span><div class="filetitle">'
            '<a href="/ficha.aspx?id=1">Ficha</a></div></div>'
            '<input type="hidden" name="__VIEWSTATE" value="v"/>'
            '<a id="lnkSiguienteInf" href="javascript:__doPostBack(\'next\',\'\')">Next</a></html>')


class StockTests(TestCase):
    def test_stops_after_finding_requested_isbns(self):
        urls = {}
        with patch.object(stock, "build_opener") as build:
            client = build.return_value
            client.open.return_value = Response(page("9780000000001"))
            result = stock.read_sd_stock({"9780000000001"}, detail_urls=urls)
            self.assertEqual(client.open.call_count, 1)
        self.assertEqual(result, {"9780000000001": True})
        self.assertTrue(urls["9780000000001"].startswith("https://www.sddistribuciones.com/"))

    def test_network_error_keeps_previous_pages(self):
        refs = {"9780000000001": "PNI.1", "9780000000002": "PNI.2"}
        with patch.object(stock, "build_opener") as build, patch.object(stock, "sleep"):
            build.return_value.open.side_effect = [Response(page("9780000000001")), OSError("offline")]
            result, errors = stock.read_sd_stock_batches(refs)
        self.assertEqual(result, {"9780000000001": True})
        self.assertIn("offline", errors[0])

    def test_cancel_during_stock_stops_before_next_page(self):
        stop = Event()
        with patch.object(stock, "build_opener") as build:
            build.return_value.open.return_value = Response(page("9780000000001", "Stock: No"))
            result = stock.read_sd_stock(
                {"9780000000001", "9780000000002"}, stop_requested=stop,
                progress=lambda *_: stop.set(),
            )
            self.assertEqual(build.return_value.open.call_count, 1)
        self.assertEqual(result, {"9780000000001": False})

    def test_unknown_stock_is_not_marked_available(self):
        with patch.object(stock, "build_opener") as build:
            build.return_value.open.return_value = Response(page("9780000000001", "Próximamente"))
            self.assertEqual(stock.read_sd_stock({"9780000000001"}), {})


class WorkerTests(TestCase):
    def exercise(self, cancel=False):
        refs = {f"978{i:010}": f"PNI.{i}" for i in range(12)}
        worker = sd_stock_worker.SdStockWorker(refs, detail_isbns=set(refs))
        lock = Lock()
        active = peak = called = 0
        def batches(references, *, detail_urls, **kwargs):
            detail_urls.update({isbn: "url/" + isbn for isbn in references})
            return {isbn: True for isbn in references}, []
        def details(url, isbn):
            nonlocal active, peak, called
            with lock:
                active += 1
                peak = max(peak, active)
                called += 1
                if cancel and active == worker.DETAIL_WORKERS:
                    worker.stop_requested.set()
            sleep(0.03)
            with lock: active -= 1
            if not cancel and isbn == next(iter(refs)):
                raise ValueError("bad detail")
            return SdDetails("Manga", "Seinen", 200, "rústica", "Autor", "Texto")
        with patch.object(sd_stock_worker, "read_sd_stock_batches", batches), \
             patch.object(sd_stock_worker, "read_sd_details", details):
            worker.run()
        self.assertEqual(peak, 4)
        if cancel:
            self.assertEqual(called, 4)
            self.assertEqual(len(worker.details), 4)
        else:
            self.assertEqual(len(worker.details), 11)
            self.assertIn("bad detail", worker.error)
        self.assertEqual(len(worker.result), 12)

    def test_bounded_parallelism_and_partial_failure(self): self.exercise()
    def test_stop_keeps_inflight_results_without_starting_new_requests(self): self.exercise(True)


class WindowTests(TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_all_rejected_rows_can_be_exported_and_cancel_preserves_them(self):
        window = ImportWindow()
        result = ImportResult()
        add(result, 2, isbn="")
        window._show_result(result, "input.xlsx")
        self.assertTrue(window.export_issues_button.isEnabled())
        self.assertFalse(window.save_button.isEnabled())
        with patch.object(window, "_confirm_leave_issues", return_value=False):
            window._clear()
        self.assertIs(window._result, result)
        with TemporaryDirectory() as directory:
            path = str(Path(directory) / "review.xlsx")
            with patch("yumekai_importer.ui.windows.import_window.QFileDialog.getSaveFileName", return_value=(path, "")), \
                 patch("yumekai_importer.ui.windows.import_window.QMessageBox.information"):
                self.assertTrue(window._export_issues())
                self.assertTrue(window._issues_exported)
                self.assertTrue(Path(path).exists())
        window.close()
        window.deleteLater()


if __name__ == "__main__":
    main()
