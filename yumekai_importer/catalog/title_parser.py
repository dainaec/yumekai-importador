"""Title cleanup and collection/volume inference for importer review."""
import re
from dataclasses import dataclass


_EDITION_LABEL = (
    r"edici[oó]n\s+(?:especial|limitada|(?:de\s+)?coleccionista)"
    r"|(?:tomo|n[uú]mero)\s+[uú]nico"
)
_EDITION_SUFFIX = re.compile(
    rf"\s*(?:[-–—]\s*)?\(\s*(?:{_EDITION_LABEL})\s*\)$"
    rf"|\s+(?:[-–—]\s*)?(?:{_EDITION_LABEL})$",
    re.IGNORECASE,
)
_COMIC_SUFFIX = re.compile(
    r"(?:\s*\(\s*c[oó]mic(?:\s+manga)?\s*\)"
    r"|\s+c[oó]mic(?:\s+manga)?)\s*$",
    re.IGNORECASE,
)

_MARKER = r"(?:vol(?:umen)?\.?|tomo|n[uú]m(?:ero)?\.?|n\.?\s*[º°o]?|#)"
_NUMBERS = re.compile(
    rf"(?P<marker>{_MARKER})?\s*(?P<first>[0-9]{{1,4}})"
    rf"(?:\s*(?P<separator>al?|y|&|[-–—])\s*"
    rf"(?:{_MARKER})?\s*(?P<last>[0-9]{{1,4}}))?",
    re.IGNORECASE,
)
_NUMBER_IN_TITLE = re.compile(
    rf"(?<!\w){_NUMBERS.pattern}(?!\w)",
    re.IGNORECASE,
)

_TITLE_NUMBER_CONTEXT = re.compile(
    r"\b(?:el|la|los|las|un|una|de|del|al|en|por|para|con|sin|entre|"
    r"hasta|desde|antes|despu[eé]s|edici[oó]n|a[nñ]o)\s*$",
    re.IGNORECASE,
)
_EDITION_AFTER_NUMBER = re.compile(
    r"(?:edici[oó]n|novela|sobrecubierta|portada|con|incluye|integral|"
    r"kanzenban|deluxe|maximum|master\s+edition|baraja|p[oó]ster|"
    r"postales|acr[ií]lico|figura)\b",
    re.IGNORECASE,
)
_EXTRA_QUANTITY = re.compile(
    r"(?:postales|p[oó]sters?|figuras?|acr[ií]licos?|p[áa]ginas?|tarjetas?)\b",
    re.IGNORECASE,
)
_PACK_WORD = re.compile(
    r"\b(?:pack|box\s*set|estuche|cofre)\b",
    re.IGNORECASE,
)
_PACK_BEFORE_NUMBER = re.compile(
    r"\s+(?:pack|box\s*set)\s*$",
    re.IGNORECASE,
)
_PROMO_PREFIX = re.compile(
    r"^(?:pack\s+|box\s*set\s+|2\s*x\s*1\s+)",
    re.IGNORECASE,
)

_VERIFIED_EDITIONS = {
    "9788411508100": (
        "10 COSAS QUE QUIERO HACER ANTES DE LOS 40",
        "1",
    ),
}


@dataclass(frozen=True)
class TitleInference:
    series: str
    volume: str | None
    reliable: bool
    reason: str
    default_volume: bool = False


def clean_title(title: str) -> str:
    """Remove final COMIC labels, preserving the rest of the title."""
    text = str(title or "").strip()

    while True:
        stripped = _COMIC_SUFFIX.sub("", text)

        if stripped == text:
            return text

        stripped = stripped.rstrip(" \t,;:–—-")

        if not stripped:
            return text

        text = stripped


def _without_edition(text):
    while True:
        stripped = _EDITION_SUFFIX.sub("", text).strip()

        if not stripped or stripped == text:
            return text

        text = stripped


def _prepared(title):
    text = clean_title(title)

    while True:
        stripped = clean_title(_without_edition(text))

        if stripped == text:
            return text

        text = stripped


def _key(text):
    return " ".join(text.casefold().split())


def _numbered(series, numbers, *, explicit):
    match = _NUMBERS.fullmatch(numbers.strip())

    if match is None:
        return None

    first = int(match["first"])
    last = int(match["last"]) if match["last"] else None

    if last is not None and (
        last < first
        or (
            match["separator"].casefold() in {"y", "&"}
            and last != first + 1
        )
    ):
        return TitleInference(
            series,
            None,
            False,
            "Pack con numeración no consecutiva o invertida: revisa los tomos.",
        )

    if not explicit and not match["marker"] and len(match["first"]) == 4:
        return None

    volume = f"{first}-{last}" if last is not None else str(first)
    collection = _without_edition(
        series.strip().rstrip(" ,;:–—-")
    ).strip()

    if last is not None:
        collection = _PROMO_PREFIX.sub("", collection).strip()

    return TitleInference(
        collection,
        volume,
        True,
        "Numeración de tomo reconocida.",
    )

_PACK_CONTENT_RANGE = re.compile(
    rf"^(?P<before>.+?)\s*\(\s*"
    rf"(?P<numbers>(?:{_MARKER}\s*)?[0-9]{{1,4}}\s*[-–—]\s*"
    rf"(?:{_MARKER}\s*)?[0-9]{{1,4}})\s*\)"
    rf"(?P<after>.*)$",
    re.IGNORECASE,
)
_PACK_START = re.compile(
    r"^(?:pack|box\s*set|estuche|cofre)\s+",
    re.IGNORECASE,
)
_PACK_END = re.compile(
    rf"\s+(?:pack|box\s*set|estuche|cofre)"
    rf"(?:\s+(?:{_MARKER}\s*)?[0-9]{{1,4}})?$",
    re.IGNORECASE,
)
_PACK_INDEX = re.compile(
    rf"\s+(?P<marker>{_MARKER})?\s*(?P<number>[0-9]{{1,4}})$",
    re.IGNORECASE,
)

def _pack_with_range(text):
    match = _PACK_CONTENT_RANGE.fullmatch(text)
    if match is None:
        return None

    before = match["before"].strip()
    series = _PACK_START.sub("", before, count=1)

    if series == before:
        series = _PACK_END.sub("", before, count=1)

    if series == before:
        return None

    # Retirar el índice del pack: 01, 02, Nº 2...
    index = _PACK_INDEX.search(series)
    if index:
        number = index["number"]
        if index["marker"] or (
            len(number) > 1 and number.startswith("0")
        ):
            series = series[:index.start()].strip()

    if not series:
        return TitleInference(
            text,
            None,
            False,
            "No se pudo identificar la colección del pack.",
        )

    collection = f'{series} {match["after"].strip()}'.strip()
    return _numbered(
        collection,
        match["numbers"],
        explicit=True,
    )

def _candidates(text):
    for match in _NUMBER_IN_TITLE.finditer(text):
        before = text[:match.start()].strip()
        after = text[match.end():].strip()

        wrapped = before.endswith("(") and after.startswith(")")

        if wrapped:
            before = before[:-1].strip()
            after = after[1:].strip()

        pack = _PACK_BEFORE_NUMBER.search(before)

        if pack:
            before = before[:pack.start()].strip()

        explicit = bool(match["marker"]) or bool(pack)

        # Evitar cantidades dentro de descripciones de extras.
        if not explicit and before.rfind("(") > before.rfind(")"):
            if before[before.rfind("(") + 1:].strip():
                continue

        if not explicit and before.endswith("+"):
            continue

        if not explicit and _EXTRA_QUANTITY.match(after):
            continue

        if not before:
            continue

        # Evitar números que pertenecen al nombre o a una edición.
        if not explicit and _TITLE_NUMBER_CONTEXT.search(before):
            continue

        separator = "" if before.endswith("(") else " "
        series = (
            f"{before}{separator}{after}".strip()
            if after else before
        )

        result = _numbered(
            series,
            match.group(0),
            explicit=explicit,
        )

        if result is None:
            continue

        padded = (
            len(match["first"]) > 1
            and match["first"].startswith("0")
        )
        descriptor = after.lstrip(" \t([{*+,:;–—-")

        strong = (
            explicit
            or wrapped
            or padded
            or match["last"] is not None
            or bool(_EDITION_AFTER_NUMBER.match(descriptor))
        )

        yield result, strong


def collection_context(titles) -> set[str]:
    """Confirm series using explicit clues or different sibling volumes."""
    titles = [_prepared(str(title or "")) for title in titles]
    full_titles = {_key(title) for title in titles}
    known, siblings = set(), {}

    for title in titles:
        pack = _pack_with_range(title)
        if pack is not None:
            if pack.volume is not None:
                known.add(_key(pack.series))
            continue
        
        for result, strong in _candidates(title):
            if result.volume is None:
                continue

            base = _key(result.series)
            siblings.setdefault(base, set()).add(result.volume)

            if strong:
                known.add(base)

    known.update(
        base
        for base, volumes in siblings.items()
        if len(volumes) > 1 or base in full_titles
    )

    return known


def analyze_title(
    title: str,
    isbn: str | None = None,
    *,
    known_series=(),
) -> TitleInference:
    original = clean_title(title)
    clean = _prepared(original)

    if not clean:
        return TitleInference(
            "", None, False, "Falta el título."
        )

    normalized_isbn = re.sub(
        r"[\s-]+", "", str(isbn or "")
    )
    verified = _VERIFIED_EDITIONS.get(normalized_isbn)

    if verified and _key(clean) == _key(verified[0]):
        return TitleInference(
            clean,
            verified[1],
            True,
            "Tomo comprobado para este ISBN; el título no lo incluye.",
        )

    pack = _pack_with_range(clean)
    if pack is not None:
        return pack

    known = {_key(name) for name in known_series}
    candidates = list(_candidates(clean))

    supported = [
        result
        for result, strong in candidates
        if strong or _key(result.series) in known
    ]

    if len(supported) == 1:
        return supported[0]

    if len(supported) > 1:
        return TitleInference(
            clean,
            None,
            False,
            "Hay varios números que podrían ser el tomo: revisión necesaria.",
        )

    if re.search(
        r"\b(?:tomo|n[uú]mero)\s+[uú]nico\b",
        original,
        re.IGNORECASE,
    ):
        return TitleInference(
            clean, "1", True, "El título indica tomo único."
        )

    if candidates:
        return TitleInference(
            clean,
            None,
            False,
            "Numeración sin contexto suficiente para identificar el tomo.",
        )

    if _PACK_WORD.search(clean):
        return TitleInference(
            clean,
            None,
            False,
            "Pack o estuche sin numeración: revisa qué tomos contiene.",
        )

    return TitleInference(
        clean,
        "1",
        False,
        "Sin numeración: tomo 1 por defecto.",
        default_volume=True,
    )


def infer_series_and_volume(
    title: str,
    isbn: str | None = None,
) -> tuple[str, str | None]:
    result = analyze_title(title, isbn)
    return result.series, result.volume