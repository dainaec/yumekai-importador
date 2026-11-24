from dataclasses import dataclass
from decimal import Decimal, ROUND_HALF_UP
from enum import IntEnum, StrEnum


CENT = Decimal("0.01")
SALE_FACTOR = Decimal("0.95")

class YumekaiStatus(StrEnum):
    IN_STOCK = "instock"
    OUT_OF_STOCK = "outofstock"
    ON_DEMAND = "yk_on_demand"
    ON_BACKORDER = "onbackorder"


class ReviewStatus(StrEnum):
    PENDING_REVIEW = "pending_review"
    REVIEWED = "reviewed"


class PublicationStatus(IntEnum):
    DRAFT = -1
    PRIVATE = 0
    PUBLISHED = 1
    PENDING = 2

@dataclass
class Product:
    isbn: str
    title: str
    retail_price: Decimal | None = None
    sale_price: Decimal | None = None
    author: str | None = None
    description: str | None = None
    publisher: str | None = None
    series: str | None = None
    volume: str | None = None
    language: str | None = "Castellano"
    book_format: str | None = None
    pages: int | None = None
    work_type: str | None = None
    demographic: str | None = None
    categories: tuple[str, ...] = ()
    image_url: str | None = None
    sku: str | None = None
    yumekai_status: YumekaiStatus | None = None
    review_status: ReviewStatus = ReviewStatus.PENDING_REVIEW
    is_featured: bool = False
    woocommerce_id: int | None = None
    publication_status: PublicationStatus | None = None

    def __post_init__(self) -> None:
        if self.sale_price is None:
            self.set_retail_price(self.retail_price)

    def set_retail_price(self, price: Decimal | None) -> None:
        if price is None:
            self.retail_price = None
            self.sale_price = None
            return

        self.retail_price = price.quantize(CENT, rounding=ROUND_HALF_UP)
        self.sale_price = (self.retail_price * SALE_FACTOR).quantize(
            CENT, rounding=ROUND_HALF_UP
        )

    @property
    def is_manga(self) -> bool:
        return (self.work_type or "").strip().casefold() == "manga"