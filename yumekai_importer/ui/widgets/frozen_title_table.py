from PySide6.QtCore import QModelIndex, QRect, Qt
from PySide6.QtGui import QFontMetrics
from PySide6.QtWidgets import QAbstractItemView, QHeaderView, QTableView, QTableWidget, QStyledItemDelegate


class FrozenTitleTable(QTableWidget):
    def __init__(self, rows: int, columns: int) -> None:
        super().__init__(rows, columns)
        self._frozen_columns = 1

        frozen = QTableView(self)
        self._frozen_view = frozen
        frozen.setObjectName("frozenTitleView")
        frozen.setModel(self.model())
        frozen.setSelectionModel(self.selectionModel())
        frozen.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        frozen.verticalHeader().hide()
        frozen.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Fixed)
        frozen.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        frozen.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        frozen.setWordWrap(True)
        frozen.setTextElideMode(Qt.TextElideMode.ElideNone)

        pixel_scroll = QAbstractItemView.ScrollMode.ScrollPerPixel
        self.setHorizontalScrollMode(pixel_scroll)
        self.setVerticalScrollMode(pixel_scroll)
        frozen.setVerticalScrollMode(pixel_scroll)
        self.viewport().stackUnder(frozen)
        frozen.setSelectionModel(self.selectionModel())
        frozen.doubleClicked.connect(self.doubleClicked.emit)

        self.horizontalHeader().sectionResized.connect(self._sync_width)
        self.verticalHeader().sectionResized.connect(self._sync_height)
        self.verticalScrollBar().valueChanged.connect(
            frozen.verticalScrollBar().setValue
        )
        frozen.verticalScrollBar().valueChanged.connect(
            self.verticalScrollBar().setValue
        )

    def pin_title(self, frozen_columns: int = 1) -> None:
        self._frozen_columns = frozen_columns
        frozen = self._frozen_view

        frozen.setSelectionMode(self.selectionMode())
        frozen.setSelectionBehavior(self.selectionBehavior())
        frozen.setEditTriggers(self.editTriggers())
        frozen.setAlternatingRowColors(self.alternatingRowColors())
        frozen.setShowGrid(self.showGrid())
        frozen.horizontalHeader().setDefaultAlignment(
            self.horizontalHeader().defaultAlignment()
        )
        frozen.verticalHeader().setDefaultSectionSize(
            self.verticalHeader().defaultSectionSize()
        )

        for column in range(self.columnCount()):
            pinned = column < self._frozen_columns
            frozen.setColumnHidden(column, not pinned)
            if pinned:
                frozen.setColumnWidth(column, self.columnWidth(column))

        self._update_frozen_geometry()
        frozen.show()

    def set_frozen_column_delegate(
        self, column: int, delegate_type: type[QStyledItemDelegate]
    ) -> None:
        self.setItemDelegateForColumn(column, delegate_type(self))
        frozen = self._frozen_view
        frozen.setItemDelegateForColumn(column, delegate_type(frozen))

    def fit_title_rows(self) -> None:
        title_column = self._frozen_columns - 1
        text_width = max(1, self.columnWidth(title_column) - 24)
        minimum_height = self.verticalHeader().defaultSectionSize()
        metrics = QFontMetrics(self.font())
        flags = Qt.TextFlag.TextWordWrap.value

        for row in range(self.rowCount()):
            item = self.item(row, title_column)
            if item is None:
                continue

            bounds = metrics.boundingRect(
                QRect(0, 0, text_width, 0), flags, item.text()
            )
            self.setRowHeight(row, max(minimum_height, bounds.height() + 8))

    def _sync_width(self, column: int, _old: int, width: int) -> None:
        if column < self._frozen_columns:
            self._frozen_view.setColumnWidth(column, width)
            self._update_frozen_geometry()
            if column == self._frozen_columns - 1:
                self.fit_title_rows()

    def _sync_height(self, row: int, _old: int, height: int) -> None:
        self._frozen_view.setRowHeight(row, height)

    def _frozen_width(self) -> int:
        return sum(
            self.columnWidth(column) for column in range(self._frozen_columns)
        )

    def _update_frozen_geometry(self) -> None:
        viewport = self.viewport().geometry()
        header_height = self.horizontalHeader().height()
        self._frozen_view.setGeometry(
            viewport.x(),
            viewport.y() - header_height,
            min(self._frozen_width(), viewport.width()),
            viewport.height() + header_height,
        )

    def updateGeometries(self) -> None:
        super().updateGeometries()
        if hasattr(self, "_frozen_view"):
            self._update_frozen_geometry()

    def scrollTo(
        self,
        index: QModelIndex,
        hint: QAbstractItemView.ScrollHint = QAbstractItemView.ScrollHint.EnsureVisible,
    ) -> None:
        scrollbar = self.horizontalScrollBar()
        previous = scrollbar.value()
        super().scrollTo(index, hint)

        if not index.isValid() or not hasattr(self, "_frozen_view"):
            return

        if index.column() < self._frozen_columns:
            scrollbar.setValue(previous)
            return

        overlap = self._frozen_width() - self.visualRect(index).left()
        if overlap > 0:
            scrollbar.setValue(scrollbar.value() - overlap)