"""Keep SD binding labels, with store defaults for taxonomy or missing values."""
import re
import unicodedata

from yumekai_importer.catalog.classification import ALIASES, DEMOGRAPHICS, classification_key


_CLASSIFICATION_KEYS = frozenset(classification_key(value) for value in (
    *ALIASES, *ALIASES.values(), *DEMOGRAPHICS,
    "Manga", "Manhwa", "Manhua", "Cómic", "Cómics", "Cómic / Manga",
    "Novela", "Novelas", "Guía", "Guías", "Terror", "Yuri", "Girls Love", "GL",
    "Shounen", "Shoujo",
))
_EMPTY_FORMAT_KEYS = {"", "n d", "n a", "s d", "sin datos", "sin formato", "por completar"}


def normalize_sd_format(value: str | None) -> str:
    text = (value or "").strip()
    folded = unicodedata.normalize("NFKD", text).casefold()
    folded = "".join(character for character in folded if not unicodedata.combining(character))
    if re.search(r"\bcartone(?:s)?\b", folded):
        return "Tapa dura"

    key = classification_key(text)
    if key == "rustica" or key in _EMPTY_FORMAT_KEYS or key in _CLASSIFICATION_KEYS:
        return "Rústica"
    # SD can put a whole category path here, such as SEINEN / DRAMA.
    first_label = re.split(r"[/,;|+]|\s+-\s+", text, maxsplit=1)[0]
    if classification_key(first_label) in _CLASSIFICATION_KEYS:
        return "Rústica"
    return text
