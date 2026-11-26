from html import escape

from PySide6.QtWidgets import (
    QAbstractItemView,
    QHeaderView,
    QTableWidget,
    QTableWidgetItem,
)

from PySide6.QtCore import QSignalBlocker, Qt

from yumekai_importer.ui.widgets.frozen_title_table import FrozenTitleTable



def make_table(
    headers: list[str],
    stretch_column: int | None,
    column_widths: dict[int, int] | None = None,
    *,
    freeze_title: bool = False,
    frozen_columns: int = 1,
) -> QTableWidget:
    table_type = FrozenTitleTable if freeze_title else QTableWidget
    table = table_type(0, len(headers))
    table.setHorizontalHeaderLabels(headers)
    table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
    table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
    table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
    table.setAlternatingRowColors(True)
    table.setShowGrid(False)
    table.verticalHeader().setDefaultSectionSize(38)
    table.verticalHeader().hide()

    header = table.horizontalHeader()
    header.setDefaultAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
    header.setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)

    for column, width in (column_widths or {}).items():
        header.setSectionResizeMode(column, QHeaderView.ResizeMode.Interactive)
        table.setColumnWidth(column, width)

    if stretch_column is not None:
        header.setSectionResizeMode(stretch_column, QHeaderView.ResizeMode.Stretch)

    if isinstance(table, FrozenTitleTable):
        table.pin_title(frozen_columns)
    return table

def set_rows(table: QTableWidget, rows: list[tuple[str, ...]]) -> None:
    table.setUpdatesEnabled(False)
    try:
        table.setRowCount(len(rows))
        for row, values in enumerate(rows):
            for column, value in enumerate(values):
                item = QTableWidgetItem(value)
                tooltip = escape(value).replace("\n", "<br>")
                item.setToolTip(f"<qt>{tooltip}</qt>")
                table.setItem(row, column, item)
    finally:
        table.setUpdatesEnabled(True)

def filter_table_rows(table, visible_keys, selected_keys):
    visible_keys = set(visible_keys)
    table.setUpdatesEnabled(False)

    try:
        with QSignalBlocker(table):
            table.clearSelection()

            for row in range(table.rowCount()):
                item = table.item(row, 0)
                if item is None:
                    continue

                key = item.data(Qt.ItemDataRole.UserRole)
                table.setRowHidden(row, key not in visible_keys)

                state = (
                    Qt.CheckState.Checked
                    if key in visible_keys and key in selected_keys
                    else Qt.CheckState.Unchecked
                )

                if item.checkState() != state:
                    item.setCheckState(state)
    finally:
        table.setUpdatesEnabled(True)

