from threading import Event
from dataclasses import replace

from PySide6.QtCore import QThread, Signal

from yumekai_importer.importers.norma.lookup import NormaLookupCancelled, NormaLookupResult
from yumekai_importer.importers.norma.zonalibros import ZonaLibrosClient, ZonaLibrosError
from yumekai_importer.importers.mangaupdates import MangaUpdatesClient, MangaUpdatesCancelled, is_comic_title, metadata_key
from yumekai_importer.catalog.title_parser import analyze_title
from yumekai_importer.catalog.suppliers import supplier_block_reason
from yumekai_importer.storage.norma_credentials import save_norma_credentials
from yumekai_importer.diagnostics import logger


class NormaRecheckWorker(QThread):
    progress = Signal(int, int)

    def __init__(self, products: dict[str, dict], parent=None, *, credentials=None, remember_access=False, stock_only=False):
        super().__init__(parent)
        self.products = {key: dict(value) for key, value in products.items()}
        self.credentials = credentials
        self.remember_access = remember_access
        self.stock_only = stock_only
        self.stop_requested = Event()
        self.results = {}
        self.error = None
        self._metadata = None

    def _complete_classification(self, product, result):
        if self.stock_only or result.status != "found" or result.details is None:
            return result
        details = result.details
        current_type = str(product.get("work_type") or "").strip()
        effective_type = details.work_type or current_type
        if effective_type and effective_type not in {"Manga", "Manhwa", "Manhua"}:
            return result
        if details.work_type in {"Manhwa", "Manhua"}:
            return result
        if not is_comic_title(product.get("title")) or not is_comic_title(details.title):
            return result
        if details.classification_note.startswith("Novela o libro ilustrado:"):
            return result
        series = next((str(value).strip() for value in (details.series, product.get("series"))
            if value and metadata_key(value) not in {"n d", "nd", "numero unico", "numeros unicos"}), "")
        if not series:
            series = analyze_title(details.title or product.get("title") or "", result.isbn).series or ""
        author = details.author or product.get("author") or ""
        if not series or not author:
            return replace(result, details=replace(details, classification_note=(
                details.classification_note + " · MangaUpdates: faltan colección o autoría para confirmar una coincidencia.")))
        try:
            if self._metadata is None:
                self._metadata = MangaUpdatesClient(self.stop_requested, refresh=True)
            metadata = self._metadata.lookup(series, author)
            if metadata.status == "matched":
                work_type = details.work_type or metadata.work_type
                demographic = details.demographic or (metadata.demographic if work_type == "Manga" else None)
                note = metadata.message
                if details.demographic and metadata.demographic and details.demographic != metadata.demographic:
                    note += " · La demografía difiere de Norma; se conserva la de Norma para revisión."
                completed = replace(details, work_type=work_type, demographic=demographic,
                                    classification_note=note)
            else:
                note = " · ".join(part for part in (details.classification_note, metadata.message) if part)
                completed = replace(details, classification_note=note)
            logger.info("supplier.norma.metadata isbn=%s status=%s", result.isbn, metadata.status)
            return replace(result, details=completed)
        except MangaUpdatesCancelled:
            return result  # Keep the ZonaLibros fields already read before cancellation.
        except Exception:
            logger.exception("supplier.norma.metadata_failed isbn=%s", result.isbn)
            return replace(result, details=replace(details, classification_note=(
                details.classification_note + " · MangaUpdates no disponible; se conservan los datos de Norma.")))

    def run(self):
        client = None
        fatal = None
        try:
            blocked = supplier_block_reason(self.products, "norma")
            if blocked:
                self.error = blocked
                self.results = {key: NormaLookupResult(str(product.get("isbn") or ""), "blocked", message=blocked)
                                for key, product in self.products.items()}
                return
            self.progress.emit(0, len(self.products))
            if self.stop_requested.is_set() or not self.products:
                return
            logger.info("supplier.norma.start products=%s source=zonalibros stock_only=%s", len(self.products), self.stock_only)
            client = ZonaLibrosClient(self.stop_requested)
            client.login(self.credentials)
            if self.remember_access:
                try:
                    save_norma_credentials(self.credentials)
                except Exception:
                    self.error = "Acceso confirmado, pero no se pudo recordar en este equipo. La consulta continúa."
            for key, product in self.products.items():
                if self.stop_requested.is_set():
                    break
                isbn = str(product.get("isbn") or "")
                try:
                    result = client.lookup(isbn, stock_only=True) if self.stock_only else client.lookup(isbn)
                    self.results[key] = self._complete_classification(product, result)
                except NormaLookupCancelled:
                    break
                except ZonaLibrosError as error:
                    # Do not repeat a rejected login, a closed session, or server failure for every ISBN.
                    fatal = str(error)
                    self.error = fatal
                    break
                except Exception:
                    logger.error("supplier.norma.parse_error isbn=%s", isbn)
                    self.results[key] = NormaLookupResult(isbn, "error", message="No se pudo interpretar la ficha de ZonaLibros. Se conservan los datos anteriores.")
                self.progress.emit(len(self.results), len(self.products))
                logger.info("supplier.norma.result isbn=%s status=%s", isbn, self.results[key].status)
        except NormaLookupCancelled:
            pass
        except ZonaLibrosError as error:
            fatal = str(error)
            self.error = fatal
        except Exception:
            fatal = "No se pudo iniciar la consulta de Norma ZonaLibros. Revisa el acceso y vuelve a intentarlo."
            self.error = fatal
            logger.error("supplier.norma.failed")
        finally:
            if client is not None:
                client.close()
            if self._metadata is not None:
                try:
                    self._metadata.close()
                    if self._metadata.cache.warning:
                        logger.warning("supplier.norma.metadata_cache %s", self._metadata.cache.warning)
                except Exception:
                    logger.warning("supplier.norma.metadata_cache_failed")
            self.credentials = None
            for key, product in self.products.items():
                if key not in self.results:
                    self.results[key] = NormaLookupResult(str(product.get("isbn") or ""),
                        "error" if fatal else "cancelled", message=fatal or "Sin consultar: proceso detenido.")
            logger.info("supplier.norma.finished products=%s cancelled=%s", len(self.results), self.stop_requested.is_set())
