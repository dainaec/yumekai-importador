"""Group full matching titles without using the ISBN as a matching rule."""
from collections import defaultdict
from dataclasses import dataclass

from yumekai_importer.catalog.review_workflow import search_text


@dataclass(frozen=True)
class DuplicateTitleGroup:
    title_key: str
    keys: tuple[str, ...]


def duplicate_title_key(title: object) -> str:
    return " ".join(search_text(title).split())


def find_duplicate_titles(products: dict) -> tuple[DuplicateTitleGroup, ...]:
    grouped = defaultdict(list)
    for key, product in products.items():
        title_key = duplicate_title_key(product.get("title"))
        if title_key:
            grouped[title_key].append(key)
    return tuple(DuplicateTitleGroup(title, tuple(sorted(keys)))
                 for title, keys in sorted(grouped.items()) if len(keys) > 1)
