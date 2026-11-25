"""Recover shortened distributor descriptions without replacing reviewed text."""
import html
import re
import unicodedata
from dataclasses import dataclass


@dataclass(frozen=True)
class DescriptionFormat:
    text: str | None
    changed: bool = False
    note: str = ""


def format_description(value: object) -> DescriptionFormat:
    """Reflow plain prose, leaving paragraph breaks and special layouts intact."""
    if value is None:
        return DescriptionFormat(None)
    original = str(value)
    if re.search(r"<\s*(?:[a-zA-Z][\w:-]*(?:\s|/?>)|!--)", original):
        return DescriptionFormat(original, note="Sinopsis con HTML: formato conservado para revisión manual.")
    normalized = original.replace("\r\n", "\n").replace("\r", "\n")
    # Lists, dialogue, indentation and split words need a human decision.
    lines = normalized.split("\n")
    if any(re.match(r"^\s*(?:[-*•▪–—]|\d+[.)])\s+", line) or line.startswith(("\t", "    "))
           for line in lines) or re.search(r"\w-\s*\n\s*\w", normalized):
        return DescriptionFormat(original, note="Sinopsis con lista, diálogo o palabra partida: revisar formato manualmente.")
    paragraphs = re.split(r"\n[\t ]*\n(?:[\t ]*\n)*", normalized.strip())
    text = "\n\n".join(re.sub(r"[\t ]+", " ", re.sub(r"[\t ]*\n[\t ]*", " ", p)).strip()
                       for p in paragraphs)
    return DescriptionFormat(text, text != original,
                             "Sinopsis: saltos de línea y espacios normalizados." if text != original else "")


def description_may_be_shortened(value: object) -> bool:
    # The supplied SD spreadsheets contain many cut strings of 250–254 characters.
    return value is not None and 250 <= len(str(value).strip()) <= 255


def can_complete_description(current: object, candidate: object) -> bool:
    if not description_may_be_shortened(current) or not candidate:
        return False

    def plain(value):
        return re.sub(r"\s+", " ", unicodedata.normalize("NFC", html.unescape(str(value)))).strip()

    old, full = plain(current), plain(candidate)
    prefix = old[:-3].rstrip() if old.endswith("...") else old.rstrip("…").rstrip()
    return len(full) > len(old) and full.startswith(prefix)
