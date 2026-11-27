"""Supplier configuration for the shared Excel reader; no UI or web requests."""
from dataclasses import dataclass, field
import re
from typing import Callable, Mapping
from unicodedata import combining, normalize

from yumekai_importer.importers.import_result import ImportResult


HEADER_ALIASES = {
    "ISBN": ("ISBN", "EAN", "EAN 13", "EAN13"),
    "TITULO": ("TITULO", "TITLE", "NOMBRE"),
    "AUTOR": ("AUTOR", "AUTORIA", "AUTORES", "AUTHOR"),
    "PVP": ("PVP", "P V P", "PRECIO DE VENTA", "PRECIO VENTA", "PRECIO VENTA PUBLICO"),
    "EDITORIAL": ("EDITORIAL", "PUBLISHER"),
    "SINOPSIS": ("SINOPSIS", "DESCRIPCION", "DESCRIPTION"),
    "IMAGEN": ("IMAGEN", "PORTADA", "PORTADA URL", "URL IMAGEN", "IMAGEN URL"),
    "REF": ("REF", "REFERENCIA", "REFERENCE"),
    "DISTRIBUIDOR": ("DISTRIBUIDOR", "PROVEEDOR", "DISTRIBUTOR"),
    "ESTADO": ("ESTADO", "ESTADO YUMEKAI", "STOCK", "DISPONIBILIDAD"),
}
REQUIRED_FIELDS = frozenset({"ISBN", "TITULO", "PVP"})
FIELD_LABELS = {"ISBN": "ISBN", "TITULO": "Título", "PVP": "PVP"}


def text(value: object) -> str | None:
    return (str(value).strip() or None) if value is not None else None


def label(value: object) -> str:
    value = " ".join((text(value) or "").upper().split())
    return "".join(character for character in normalize("NFD", value) if not combining(character))


def header_key(value: object) -> str:
    return " ".join(re.sub(r"[^A-Z0-9]+", " ", label(value)).split())


def distributor_key(value: object) -> str:
    return re.sub(r"[^A-Z0-9]", "", label(value))


@dataclass(frozen=True)
class ExcelProfile:
    code: str
    name: str
    distributor_aliases: tuple[str, ...] = ()
    distributor_prefixes: tuple[str, ...] = ()
    column_aliases: Mapping[str, tuple[str, ...]] = field(default_factory=dict)
    required_fields: frozenset[str] = REQUIRED_FIELDS
    matches_headers: Callable[[tuple[str, ...]], bool] | None = None
    read_image: Callable[[object], tuple[str | None, str | None]] | None = None
    apply_row: Callable[[ImportResult, int, dict[str, object]], None] | None = None
    default_publisher: str | None = None
    strip_details: bool = True
    reference_field: str | None = None
    legacy_default: bool = False

    def header_fields(self) -> dict[str, str]:
        fields = {}
        for field_name, aliases in {**HEADER_ALIASES, **self.column_aliases}.items():
            for alias in (field_name, *aliases):
                key = header_key(alias)
                if key in fields and fields[key] != field_name:
                    raise ValueError(f"El perfil {self.name} asigna la columna {alias!r} a dos campos.")
                fields[key] = field_name
        return fields

    def matches_distributor(self, value: object) -> bool:
        key = distributor_key(value)
        return bool(key) and (key in {distributor_key(alias) for alias in self.distributor_aliases}
            or any(key.startswith(distributor_key(prefix)) for prefix in self.distributor_prefixes if distributor_key(prefix)))
