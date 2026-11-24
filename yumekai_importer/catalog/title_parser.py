"""Conservative title parsing; explicit edition data takes precedence over guesses."""
import re
from dataclasses import dataclass

_EDITION_LABEL = (
    r'edici[oó]n\s+(?:especial|limitada|(?:de\s+)?coleccionista)'
    r'|(?:tomo|n[uú]mero)\s+[uú]nico'
)
_EDITION_SUFFIX = re.compile(
    rf'\s*(?:[-–—]\s*)?\(\s*(?:{_EDITION_LABEL})\s*\)$'
    rf'|\s+(?:[-–—]\s*)?(?:{_EDITION_LABEL})$', re.IGNORECASE,
)
_MARKER = r'(?:vol(?:umen)?\.?|tomo|n[uú]m(?:ero)?\.?|n\.?\s*[º°o]?|#)'
_NUMBERS = re.compile(
    rf'(?P<marker>{_MARKER})?\s*(?P<first>[0-9]{{1,4}})'
    rf'(?:\s*(?P<separator>al?|y|&|[-–—])\s*(?:{_MARKER})?\s*(?P<last>[0-9]{{1,4}}))?',
    re.IGNORECASE,
)
_PARENTHETICAL = re.compile(r'(?P<series>.+?)\s*\(\s*(?P<numbers>[^()]*)\s*\)$')
_EXPLICIT = re.compile(
    rf'(?P<series>.+?)\s+(?P<numbers>(?:pack\s+|box\s*set\s+)?{_MARKER}\s*'
    rf'[0-9]{{1,4}}(?:\s*(?:al?|y|&|[-–—])\s*(?:{_MARKER})?\s*[0-9]{{1,4}})?)'
    r'(?:\s+[-–—]\s+.+)?$', re.IGNORECASE,
)
_PACK = re.compile(r'(?P<series>.+?)\s+(?:pack|box\s*set)\s+(?P<numbers>.+)$', re.IGNORECASE)
_BARE = re.compile(
    r'(?P<series>.+?)\s+(?P<numbers>[0-9]{1,3}(?:\s*(?:al?|y|&|[-–—])\s*[0-9]{1,3})?)'
    r'(?:\s+[-–—]\s+.+)?$', re.IGNORECASE,
)
_TITLE_NUMBER_CONTEXT = re.compile(
    r'\b(?:el|la|los|las|un|una|de|del|al|en|por|para|con|sin|entre|hasta|desde|antes|despu[eé]s)\s*$',
    re.IGNORECASE,
)
_PROMO_PREFIX = re.compile(r'^(?:pack\s+|box\s*set\s+|2\s*x\s*1\s+)', re.IGNORECASE)

# Verified edition whose supplier title omits the volume. ISBN and title must both match.
# https://www.fnac.es/a10418450/Mamita-10-cosas-que-quiero-hacer-antes-de-los-40-1
_VERIFIED_EDITIONS = {
    '9788411508100': ('10 COSAS QUE QUIERO HACER ANTES DE LOS 40', '1'),
}


@dataclass(frozen=True)
class TitleInference:
    series: str
    volume: str | None
    reliable: bool
    reason: str


def _without_edition(text):
    while True:
        stripped = _EDITION_SUFFIX.sub('', text).strip()
        if not stripped or stripped == text:
            return text
        text = stripped


def _key(text):
    return ' '.join(text.casefold().split())


def _numbered(series, numbers, *, explicit):
    match = _NUMBERS.fullmatch(numbers.strip())
    if match is None:
        return None
    first = int(match['first'])
    last = int(match['last']) if match['last'] else None
    if last is not None and (last < first or (match['separator'].casefold() in {'y', '&'} and last != first + 1)):
        return TitleInference(series, None, False, 'Pack con numeración no consecutiva o invertida: revisa los tomos.')
    if not explicit and not match['marker'] and len(match['first']) == 4:
        return None
    volume = f'{first}-{last}' if last is not None else str(first)
    collection = _without_edition(series.strip().rstrip(' ,;:–—-')).strip()
    if last is not None:
        collection = _PROMO_PREFIX.sub('', collection).strip()
    return TitleInference(collection, volume, True,
                          'Rango de tomos indicado.' if last is not None else
                          'Numeración explícita reconocida.' if explicit else 'Número final separado del título.')


def collection_context(titles) -> set[str]:
    """Recognize series from explicit markers or distinct sibling volume numbers."""
    titles = list(titles)
    full_titles = {_key(_without_edition(str(title).strip())) for title in titles}
    known = set()
    siblings = {}
    for title in titles:
        clean = _without_edition(str(title).strip())
        explicit = _EXPLICIT.fullmatch(clean) or _PACK.fullmatch(clean)
        if explicit:
            known.add(_key(_without_edition(explicit['series'].strip())))
        match = _BARE.fullmatch(clean)
        if match and not _TITLE_NUMBER_CONTEXT.search(match['series']):
            base = _key(_without_edition(match['series'].strip()))
            siblings.setdefault(base, set()).add(match['numbers'])
    known.update(base for base, numbers in siblings.items() if len(numbers) > 1 or base in full_titles)
    return known


def analyze_title(title: str, isbn: str | None = None, *, known_series=()) -> TitleInference:
    original = str(title or '').strip()
    clean = _without_edition(original)
    normalized_isbn = re.sub(r'[\s-]+', '', str(isbn or ''))
    verified = _VERIFIED_EDITIONS.get(normalized_isbn)
    if verified and _key(clean) == _key(verified[0]):
        return TitleInference(clean, verified[1], True, 'Tomo comprobado para este ISBN; el título no lo incluye.')

    match = _PARENTHETICAL.fullmatch(clean)
    if match:
        numbers = _NUMBERS.fullmatch(match['numbers'].strip())
        if numbers:
            result = _numbered(match['series'], match['numbers'], explicit=bool(numbers['marker']))
            if result is not None:
                return result
    match = _EXPLICIT.fullmatch(clean)
    if match:
        numbers = re.sub(r'^(?:pack|box\s*set)\s+', '', match['numbers'], flags=re.IGNORECASE)
        result = _numbered(match['series'], numbers, explicit=True)
        if result is not None:
            return result
    match = _PACK.fullmatch(clean)
    if match:
        result = _numbered(match['series'], match['numbers'], explicit=True)
        if result is not None:
            return result
    if re.search(r'\b(?:tomo|n[uú]mero)\s+[uú]nico\b', original, re.IGNORECASE):
        return TitleInference(clean, '1', True, 'El título indica tomo único.')
    match = _BARE.fullmatch(clean)
    if match and not _TITLE_NUMBER_CONTEXT.search(match['series']):
        first = _NUMBERS.fullmatch(match['numbers'])
        padded = first is not None and len(first['first']) > 1 and first['first'].startswith('0')
        has_range = first is not None and first['last'] is not None
        supported = _key(_without_edition(match['series'].strip())) in {_key(name) for name in known_series}
        if not (padded or has_range or supported):
            return TitleInference(clean, None, False,
                'Número final sin marcador ni otros tomos que confirmen la colección: revisar.')
        result = _numbered(match['series'], match['numbers'], explicit=False)
        if result is not None:
            return result
    return TitleInference(clean, None, False, 'Sin número de tomo inequívoco: no se asigna 1 por defecto.')


def infer_series_and_volume(title: str, isbn: str | None = None) -> tuple[str, str | None]:
    result = analyze_title(title, isbn)
    return result.series, result.volume
