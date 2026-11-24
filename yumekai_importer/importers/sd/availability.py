"""SD availability and release-date rules, shared by imports and manual checks."""
from dataclasses import dataclass, replace
from datetime import date, datetime
import re
import unicodedata
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from lxml import html


def consultation_day() -> date:
    try:
        return datetime.now(ZoneInfo("Europe/Madrid")).date()
    except ZoneInfoNotFoundError:
        # Windows installations without IANA data use the store PC's local clock.
        return date.today()


def publication_date(value: object) -> date | None:
    text = str(value or "").strip()
    for pattern, order in ((r"\b(\d{1,2})[/-](\d{1,2})[/-](\d{4})\b", (2, 1, 0)),
                           (r"\b(\d{4})-(\d{2})-(\d{2})\b", (0, 1, 2))):
        match = re.search(pattern, text)
        if match:
            parts = [int(part) for part in match.groups()]
            try:
                return date(*(parts[index] for index in order))
            except ValueError:
                return None
    return None


def _fold(value: str) -> str:
    text = unicodedata.normalize("NFKD", value).casefold()
    return " ".join("".join(c for c in text if not unicodedata.combining(c)).split())


@dataclass(frozen=True)
class SdStockInfo:
    label: str = ""
    publication_date: date | None = None
    checked_on: date | None = None

    @property
    def kind(self) -> str | None:
        label = _fold(self.label)
        if re.fullmatch(r"stock\s*:\s*si", label) or label in {"en stock", "con stock"}:
            return "available"
        if re.fullmatch(r"stock\s*:\s*no", label) or label in {"sin stock", "sin existencias"}:
            return "unavailable"
        if label == "consultar disponibilidad":
            return "consult"
        return None

    @property
    def available(self) -> bool | None:
        return {"available": True, "unavailable": False}.get(self.kind)

    @property
    def yumekai_status(self) -> str | None:
        if self.kind == "available":
            return "yk_on_demand"
        if self.kind == "unavailable":
            return "outofstock"
        if self.kind == "consult" and self.publication_date is not None:
            return "onbackorder" if self.publication_date > (self.checked_on or consultation_day()) else "outofstock"
        return None

    @property
    def explanation(self) -> str:
        text = "SD: " + (self.label or "disponibilidad sin confirmar")
        if self.kind == "consult":
            if self.publication_date is None:
                return text + " · falta una fecha de publicación válida para decidir el estado"
            text += f" · publicación {self.publication_date:%d/%m/%Y} · consulta {(self.checked_on or consultation_day()):%d/%m/%Y}"
        names = {"yk_on_demand": "Bajo demanda", "outofstock": "Sin existencias", "onbackorder": "Se puede reservar"}
        return text + (" → " + names[self.yumekai_status] if self.yumekai_status else "")


def read_stock_info(page, *, checked_on: date | None = None) -> SdStockInfo:
    article = page.get_element_by_id("dvFichaArticuloFA", None)
    article = article if article is not None else page
    def field(name, scope=None):
        scope = article if scope is None else scope
        nodes = scope.xpath(
            './/*[@id=$name][not(ancestor::*[contains(concat(" ", normalize-space(@class), " "), " fileproduct ")])]',
            name=name,
        )
        return nodes[0] if nodes else None

    state = field("dvContainerEstadoFichaArticulo")
    label = " ".join(state.text_content().split()) if state is not None else ""
    if not label:
        hidden = field("HiddenEstadoArticulo")
        if hidden is not None and hidden.get("value"):
            label = " ".join(html.fromstring("<div>" + hidden.get("value") + "</div>").text_content().split())
    released = None
    # Publication tabs sit outside the main article on SD's real pages.
    # Use only their explicit IDs; ignore update dates and related-product cards.
    for name in ("txtPublicacion", "fechaPubLyE"):
        node = field(name, page)
        if node is not None:
            released = publication_date(node.text_content())
            if released is not None:
                break
    return SdStockInfo(label, released, checked_on or consultation_day())


def prefer_stock_info(primary: SdStockInfo, fallback: SdStockInfo | None) -> SdStockInfo:
    if primary.kind is None:
        return fallback or primary
    if primary.kind == "consult" and primary.publication_date is None and fallback is not None:
        return replace(primary, publication_date=fallback.publication_date)
    return primary
