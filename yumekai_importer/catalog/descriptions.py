"""Recover shortened distributor descriptions without replacing reviewed text."""
import html
import re
import unicodedata


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
