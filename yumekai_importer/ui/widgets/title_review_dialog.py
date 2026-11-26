"""Review only actual changes to title, collection and volume."""
import re

from PySide6.QtCore import QRegularExpression, QSignalBlocker, Qt
from PySide6.QtGui import QRegularExpressionValidator
from PySide6.QtWidgets import (
    QAbstractItemView,
    QLabel,
    QLineEdit,
    QStyledItemDelegate,
)

from yumekai_importer.catalog.review_fields import (
    VOLUME_INPUT,
    normalize_volume,
)
from yumekai_importer.catalog.title_parser import (
    analyze_title,
    clean_title,
    collection_context,
)
from yumekai_importer.ui.widgets.change_review_dialog import (
    ChangeReviewDialog,
)


def _comparable(field, value):
    text = "" if value is None else str(value).strip()

    if field == "volume" and re.fullmatch(VOLUME_INPUT, text):
        return "-".join(
            str(int(number)) for number in text.split("-")
        )

    return text


def _review_proposals(products, known_titles=()):
    context = collection_context([
        *known_titles,
        *(product.get("title") or "" for product in products.values()),
    ])
    rows, checks, reasons = {}, {}, {}

    for key, product in products.items():
        title = clean_title(str(product.get("title") or ""))
        proposal = analyze_title(
            title,
            str(product.get("isbn") or ""),
            known_series=context,
        )
        default = getattr(proposal, "default_volume", False)
        fields = {}

        # La limpieza del título es independiente de la inferencia del tomo.
        if title and (
            _comparable("title", title)
            != _comparable("title", product.get("title"))
        ):
            fields["title"] = title
            checks[key, "title"] = True
            reasons[key, "title"] = (
                "Se elimina la etiqueta COMIC del final."
            )

        if (proposal.reliable or default) and proposal.series:
            if (
                _comparable("series", proposal.series)
                != _comparable("series", product.get("series"))
            ):
                fields["series"] = proposal.series
                checks[key, "series"] = proposal.reliable
                reasons[key, "series"] = proposal.reason

        current_volume = _comparable(
            "volume", product.get("volume")
        )

        if (
            proposal.volume is not None
            and (proposal.reliable or default)
            and not (default and current_volume)
            and (
                _comparable("volume", proposal.volume)
                != current_volume
            )
        ):
            fields["volume"] = proposal.volume
            checks[key, "volume"] = True
            reasons[key, "volume"] = proposal.reason

        if fields:
            rows[key] = {
                "product": product,
                "changes": fields,
            }

    return rows, checks, reasons


class _ProposalDelegate(QStyledItemDelegate):
    def createEditor(self, parent, option, index):
        editor = QLineEdit(parent)
        _, field = index.model().index(
            index.row(), 0
        ).data(Qt.ItemDataRole.UserRole)

        if field == "volume":
            editor.setValidator(
                QRegularExpressionValidator(
                    QRegularExpression(VOLUME_INPUT),
                    editor,
                )
            )

        return editor


class TitleReviewDialog(ChangeReviewDialog):
    def __init__(self, products, parent=None, *, known_titles=()):
        rows, checks, reasons = _review_proposals(
            products, known_titles
        )
        super().__init__(rows, parent=parent)

        self.setWindowTitle("Revisar título, colección y tomo")
        heading = self.findChild(QLabel, "dialogTitle")
        if heading is not None:
            heading.setText(self.windowTitle())

        self.changes = {}
        self.message.setText(
            "Se muestran solo los campos con cambios. "
            "El tomo 1 por defecto se propone únicamente "
            "si el campo está vacío. "
            "Doble clic en Propuesto para editar; "
            "en Actual para leerlo completo. "
            "Al guardar, se descartan las propuestas desmarcadas. "
            "Cancelar conserva la revisión anterior."
        )

        self.table.setEditTriggers(
            QAbstractItemView.EditTrigger.DoubleClicked
        )
        self.table.setItemDelegateForColumn(
            4, _ProposalDelegate(self.table)
        )
        self.table.cellDoubleClicked.disconnect(self._show_value)
        self.table.cellDoubleClicked.connect(
            lambda row, column: self._show_value(row, column)
            if column == 3 else None
        )

        labels = {
            "title": "Título",
            "series": "Colección",
            "volume": "Tomo",
        }

        for row in range(self.table.rowCount()):
            key, field = self.table.item(row, 0).data(
                Qt.ItemDataRole.UserRole
            )

            self.table.item(row, 2).setText(labels[field])
            self.table.item(row, 0).setCheckState(
                Qt.CheckState.Checked
                if checks[key, field]
                else Qt.CheckState.Unchecked
            )

            for column in (1, 2, 3):
                item = self.table.item(row, column)
                item.setFlags(
                    item.flags() & ~Qt.ItemFlag.ItemIsEditable
                )

            item = self.table.item(row, 4)
            item.setFlags(
                item.flags() | Qt.ItemFlag.ItemIsEditable
            )
            item.setToolTip(reasons[key, field])

        self.error = QLabel()
        self.error.setObjectName("reviewValidationError")
        self.error.setWordWrap(True)
        self.error.setTextFormat(Qt.TextFormat.PlainText)
        self.error.hide()
        self.layout().insertWidget(
            self.layout().count() - 1, self.error
        )
        self.table.itemChanged.connect(self._item_changed)

    def _item_changed(self, item):
        if item.column() == 4:
            with QSignalBlocker(self.table):
                self.table.item(
                    item.row(), 0
                ).setCheckState(Qt.CheckState.Checked)

    def accept(self):
        try:
            for row in range(self.table.rowCount()):
                mark = self.table.item(row, 0)
                if mark.checkState() != Qt.CheckState.Checked:
                    continue

                key, field = mark.data(Qt.ItemDataRole.UserRole)
                text = self.table.item(row, 4).text().strip()

                if field == "volume":
                    value = normalize_volume(text)
                    if value is None:
                        raise ValueError(
                            "Indica un tomo o rango como 1-4. "
                            "Para descartarlo, desmarca la fila."
                        )

                elif field == "title":
                    if not text or len(text.encode("utf-8")) > 65535:
                        raise ValueError(
                            "El título está vacío o es demasiado largo."
                        )
                    value = text

                else:
                    if not text or len(text) > 255:
                        raise ValueError(
                            "La colección debe tener entre "
                            "1 y 255 caracteres."
                        )
                    value = text

                self._rows[key]["changes"][field] = value
                previous = self._rows[key]["product"].get(field)

                if (
                    _comparable(field, value)
                    == _comparable(field, previous)
                ):
                    mark.setCheckState(Qt.CheckState.Unchecked)

            super().accept()
            self.changes = self.accepted_changes

        except ValueError as error:
            self.error.setText(str(error))
            self.error.show()