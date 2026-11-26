import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtWidgets import QApplication
from yumekai_importer.ui.styles.theme import apply_light_theme


@pytest.fixture(scope="session")
def app():
    instance = QApplication.instance() or QApplication([])
    instance.setApplicationName("Yumekai Tests")
    apply_light_theme(instance)
    return instance


@pytest.fixture
def product():
    return {"isbn": "9788410517653", "title": "Producto de prueba", "publisher": "Panini",
            "author": "Autor", "series": "Serie", "volume": "1", "description": "Sinopsis actual",
            "retail_price": "10.00", "sale_price": "9.50", "pages": "200", "language": "Castellano",
            "book_format": "Rústica", "work_type": "Manga", "demographic": "Shonen",
            "yumekai_status": "outofstock", "review_status": "pending_review", "sku": None,
            "is_featured": 0, "image_url": "https://example.test/cover.jpg", "categories": ["Manga"],
            "updated_at": "2026-11-25 09:00:00", "_revision": "a" * 64,
            "publication_status": "publish", "product_type": "simple", "woocommerce_id": 21, "_store_revision": "b" * 64}
