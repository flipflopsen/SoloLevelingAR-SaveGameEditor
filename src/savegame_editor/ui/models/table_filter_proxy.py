"""Filtering and sorting proxy for the save-table workspace."""

from __future__ import annotations

from PySide6.QtCore import QModelIndex, QObject, QPersistentModelIndex, QSortFilterProxyModel, Qt

from .save_table_model import SaveTableModel


class TableFilterProxy(QSortFilterProxyModel):
    """Filter rows without materializing widgets or duplicating table data."""

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._search_text = ""
        self._modified_only = False
        self.setDynamicSortFilter(True)
        self.setSortCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)

    def set_search_text(self, text: str) -> None:
        self._search_text = text.casefold().strip()
        self.invalidateRowsFilter()

    def set_modified_only(self, enabled: bool) -> None:
        self._modified_only = enabled
        self.invalidateRowsFilter()

    def filterAcceptsRow(  # noqa: N802
        self, source_row: int, source_parent: QModelIndex | QPersistentModelIndex
    ) -> bool:
        model = self.sourceModel()
        if not isinstance(model, SaveTableModel):
            return True
        if self._modified_only and not any(
            model.data(model.index(source_row, column), SaveTableModel.modified_role)
            for column in range(model.columnCount())
        ):
            return False
        if not self._search_text:
            return True
        return any(
            self._search_text
            in str(
                model.data(model.index(source_row, column), SaveTableModel.raw_value_role)
            ).casefold()
            for column in range(model.columnCount())
        )

    def lessThan(  # noqa: N802
        self,
        left: QModelIndex | QPersistentModelIndex,
        right: QModelIndex | QPersistentModelIndex,
    ) -> bool:
        left_value = left.data(SaveTableModel.raw_value_role)
        right_value = right.data(SaveTableModel.raw_value_role)
        try:
            return left_value < right_value
        except TypeError:
            return str(left_value).casefold() < str(right_value).casefold()
