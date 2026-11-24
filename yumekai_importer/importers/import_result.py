from dataclasses import dataclass, field

from yumekai_importer.catalog.product import Product
from yumekai_importer.catalog.title_parser import analyze_title, collection_context, infer_series_and_volume
from yumekai_importer.importers.excel_values import normalize_isbn, parse_price


@dataclass(frozen=True)
class ImportIssue:
    row: int
    title: str
    field: str
    message: str


@dataclass
class ImportResult:
    products: list[Product] = field(default_factory=list)
    issues: list[ImportIssue] = field(default_factory=list)
    _isbn_rows: dict[str, int] = field(default_factory=dict, init=False, repr=False)
    sd_references: dict[str, str] = field(default_factory=dict)
    source_rows: dict[int, dict[str, object]] = field(default_factory=dict)
    products_by_row: dict[int, Product] = field(default_factory=dict)

    def finalize_title_inferences(self) -> None:
        known = collection_context(product.title for product in self.products)
        for product in self.products:
            result = analyze_title(product.title, product.isbn, known_series=known)
            product.series, product.volume = result.series, result.volume

    def add_row(
        self,
        row: int,
        *,
        isbn_value: object,
        title_value: object,
        price_value: object,
        author: str | None,
        publisher: str | None,
        description: str | None,
        sd_reference: str | None = None,
        image_url: str | None = None,
        source_data: dict[str, object] | None = None,
    ) -> None:
        # Keep the original row even when it cannot become a database product.
        self.source_rows[row] = dict(source_data) if source_data is not None else {
            "ISBN": isbn_value,
            "Titulo": title_value,
            "PVP": price_value,
            "Autor": author,
            "Editorial": publisher,
            "Sinopsis": description,
            "Ref": sd_reference,
            "Portada (URL)": image_url,
        }
        isbn = normalize_isbn(isbn_value)
        title = str(title_value or "").strip()

        if isbn is None:
            detail = "Falta el ISBN."
            if isbn_value is not None and str(isbn_value).strip():
                detail = f"ISBN no válido: {isbn_value!r}"
            self.issues.append(ImportIssue(row, title, "ISBN", detail))

        if not title:
            self.issues.append(ImportIssue(row, title, "Título", "Falta el título."))

        try:
            price = parse_price(price_value, row)
        except ValueError:
            price = None
            self.issues.append(
                ImportIssue(row, title, "PVP", f"PVP no válido: {price_value!r}")
            )
        else:
            if price is None:
                self.issues.append(ImportIssue(row, title, "PVP", "Falta el PVP."))

        if isbn is None or not title:
            return

        first_row = self._isbn_rows.setdefault(isbn, row)
        if first_row != row:
            self.issues.append(
                ImportIssue(row, title, "ISBN", f"{isbn} también aparece en la fila {first_row}.")
            )

        series, volume = infer_series_and_volume(title, isbn)

        self.products.append(
            Product(
                isbn=isbn,
                title=title,
                retail_price=price,
                author=author,
                publisher=publisher,
                description=description,
                image_url=image_url,
                series=series,
                volume=volume,
            )
        )
        self.products_by_row[row] = self.products[-1]
        
        if isinstance(sd_reference, str) and sd_reference.strip():
            self.sd_references[isbn] = sd_reference.strip()
