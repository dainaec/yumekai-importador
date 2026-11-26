"""Yumekai's category labels and the supplier terms that map to them."""
import re
import unicodedata

ARTBOOK_CATEGORY = 'Artbooks, guías y novelas'
DEMOGRAPHICS = ('Shonen', 'Shōjo', 'Seinen', 'Josei', 'Kodomo', 'Yaoi / BL', 'Yuri', ARTBOOK_CATEGORY)


def classification_key(value):
    text = unicodedata.normalize('NFKD', str(value or '')).casefold()
    text = ''.join(char for char in text if not unicodedata.combining(char))
    return ' '.join(re.sub(r'[^a-z0-9]+', ' ', text).split())


ALIASES = {
    'shonen': 'Shonen', 'shojo': 'Shōjo', 'seinen': 'Seinen', 'josei': 'Josei', 'kodomo': 'Kodomo',
    'teen s love': 'Yaoi / BL', 'teens love': 'Yaoi / BL', 'teenslove': 'Yaoi / BL',
    'yaoi': 'Yaoi / BL', 'boys love': 'Yaoi / BL', 'boy s love': 'Yaoi / BL',
    'boyslove': 'Yaoi / BL', 'bl': 'Yaoi / BL', 'yaoi bl': 'Yaoi / BL',
    'spokon': 'Shonen', 'manga adulto': 'Seinen',
    'terror': 'Seinen',
    'yuri': 'Yuri',
    'novelas manga': ARTBOOK_CATEGORY, 'novela manga': ARTBOOK_CATEGORY,
    'artbooks': ARTBOOK_CATEGORY, 'artbook': ARTBOOK_CATEGORY,
    'artbooks guias y novelas': ARTBOOK_CATEGORY,
}


def canonical_demographic(value):
    text = str(value or '').strip()
    return ALIASES.get(classification_key(text), text) or None


def _sd_classification_fallback(labels):
    topics = set()
    for text in labels:
        if text:
            # Keep compound labels before splitting slashes and commas.
            topics.add(classification_key(text))
            topics.update(classification_key(part) for part in re.split(r'[/,;|]', text) if part.strip())
    mapped = {ALIASES[key] for key in topics if key in ALIASES}
    explicit_types = [label for key, label in (('manhwa', 'Manhwa'), ('manhua', 'Manhua')) if key in topics]
    work_type = explicit_types[0] if len(explicit_types) == 1 else None
    if not explicit_types and ('manga' in topics or mapped):
        work_type = 'Manga'
    if work_type != 'Manga':
        return work_type, None
    # Specific store categories take precedence over broad supplier headings.
    if ARTBOOK_CATEGORY in mapped:
        demographic = ARTBOOK_CATEGORY
    elif 'Yaoi / BL' in mapped:
        demographic = 'Yaoi / BL'
    else:
        specific = {ALIASES[key] for key in topics if key in ALIASES and key != 'manga adulto'}
        candidates = specific or mapped
        demographic = next(iter(candidates)) if len(candidates) == 1 else None
    return work_type, demographic

_SD_CSV_RULES = {
    ('MANGA', 'SHONEN', ''): ('Manga', 'Shonen'),
    ('MANGA', 'SEINEN', ''): ('Manga', 'Seinen'),
    ('MANGA', 'SEINEN', 'EROGURO'): ('Manga', 'Seinen'),
    ('MANGA', 'SHOJO', ''): ('Manga', 'Shojo'),
    ('MANGA', 'JOSEI', ''): ('Manga', 'Josei'),
    ('MANGA', 'KODOMO', ''): ('Manga', 'Kodomo'),
    ('MANGA', 'YAOI', ''): ('Manga', 'Yaoi / BL'),
    ('MANGA', 'YURI', ''): ('Manga', 'Yuri'),
    ('MANGA', 'HENTAI', ''): (None, None),
    ('MANGA', 'BOYS LOVE', ''): ('Manga', 'Yaoi / BL'),
    ('MANGA', 'SPOKON', ''): ('Manga', 'Shonen'),
    ('MANGA', 'TERROR', ''): ('Manga', 'Seinen'),
    ('MANGA', 'MANGA ADULTO', ''): ('Manga', 'Seinen'),
    ('MANGA', 'NOVELAS MANGA', ''): ('Manga', 'Artbooks, guías y novelas'),
    ('MANGA', 'MANHWA', ''): ('Manhwa', None),
    ('MANGA', 'ISEKAI', ''): (None, None),
    ('MANGA', 'TEEN’S LOVE', ''): ('Manga', 'Yaoi / BL'),
    ('MANGA', 'ECCHI', ''): (None, None),
    ('ART-BOOKS', 'ART-BOOKS COMIC', ''): ('Manga', 'Artbooks, guías y novelas'),
    ('ART-BOOKS', 'ART-BOOKS MANGA & ANIME', ''): ('Manga', 'Artbooks, guías y novelas'),
    ('ART-BOOKS', 'ART-BOOKS VIDEOJUEGOS', ''): ('Manga', 'Artbooks, guías y novelas'),
    ('ART-BOOKS', 'ART-BOOKS CINE & TV', ''): ('Manga', 'Artbooks, guías y novelas'),
    ('COMIC', 'ART-BOOKS', ''): ('Manga', 'Artbooks, guías y novelas'),
    ('LIBROS NO FICCIÓN', 'COMIC / MANGA', ''): ('Manga', 'Artbooks, guías y novelas'),
    ('LIBROS NO FICCIÓN', 'COMIC / MANGA', 'ENSAYO'): ('Manga', 'Artbooks, guías y novelas'),
    ('LIBROS NO FICCIÓN', 'APRENDE A DIBUJAR', ''): (None, None),
    ('LIBROS NO FICCIÓN', 'APRENDE A DIBUJAR', 'EDUCATIVO'): (None, None),
    ('LIBROS NO FICCIÓN', 'CINE, SERIES, TV, MÚSICA', ''): (None, None),
    ('LIBROS NO FICCIÓN', 'VIDEOJUEGOS', ''): (None, None),
    ('LIBROS NO FICCIÓN', 'DIDÁCTICO', ''): (None, None),
    ('LIBROS NO FICCIÓN', 'IDIOMAS', ''): (None, None),
    ('LIBROS NO FICCIÓN', 'HISTORÍA & CULTURA', ''): (None, None),
    ('LIBROS NO FICCIÓN', 'BIOGRAFÍAS', ''): (None, None),
    ('LIBROS NO FICCIÓN', 'VIAJES', ''): (None, None),
    ('LIBROS NO FICCIÓN', 'COCINA', ''): (None, None),
    ('LIBROS NO FICCIÓN', 'ARTE & ILUSTRACIONES', ''): ('Manga', 'Artbooks, guías y novelas'),
    ('LIBROS FICCIÓN', 'LIBRO ILUSTRADO', ''): ('Manga', 'Artbooks, guías y novelas'),
    ('LIBROS FICCIÓN', 'NOVELA LIGERA', ''): ('Manga', 'Artbooks, guías y novelas'),
    ('LIBROS FICCIÓN', 'NOVELA LIGERA', 'SEINEN'): ('Manga', 'Artbooks, guías y novelas'),
}

_SD_CSV_RULES = {
    tuple(classification_key(part) for part in key): value
    for key, value in _SD_CSV_RULES.items()
}


def sd_classification(labels):
    values = tuple(labels)
    key = tuple(
        classification_key(value)
        for value in (values + ("", "", ""))[:3]
    )

    if key in _SD_CSV_RULES:
        work_type, demographic = _SD_CSV_RULES[key]
        return work_type, canonical_demographic(demographic)

    return _sd_classification_fallback(values)
