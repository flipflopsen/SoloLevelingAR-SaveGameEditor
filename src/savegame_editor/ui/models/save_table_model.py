"""Read-only Qt model for a service-provided save table."""

from __future__ import annotations

from typing import Any

from PySide6.QtCore import (
    QAbstractTableModel,
    QModelIndex,
    QObject,
    QPersistentModelIndex,
    Qt,
    Signal,
)
from PySide6.QtGui import QFont

from savegame_editor.services import SaveRow, SaveTable

ModelIndex = QModelIndex | QPersistentModelIndex


class SaveTableModel(QAbstractTableModel):
    """Adapt ``SaveTable`` rows for ``QTableView`` without embedding SQL in the UI."""

    modifications_changed = Signal(bool)
    history_changed = Signal(bool, bool)
    mapping_edit_requested = Signal(object, str)
    raw_value_role = Qt.ItemDataRole.UserRole + 1
    modified_role = Qt.ItemDataRole.UserRole + 2

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._table = SaveTable([], [])
        self._pending_values: dict[tuple[int, int], int] = {}
        self._history: list[tuple[tuple[int, int], int | None, int | None]] = []
        self._redo_history: list[tuple[tuple[int, int], int | None, int | None]] = []

    def set_table(self, table: SaveTable) -> None:
        self.beginResetModel()
        self._table = table
        self._pending_values.clear()
        self._history.clear()
        self._redo_history.clear()
        self.endResetModel()
        self.modifications_changed.emit(False)
        self.history_changed.emit(False, False)

    def row_for_index(self, index: QModelIndex) -> SaveRow | None:
        if not index.isValid() or index.row() >= len(self._table.rows):
            return None
        return self._table.rows[index.row()]

    def value_column_for_row(self, row: SaveRow) -> int | None:
        if not row.action:
            return None
        return len(row.values) - 1 if row.action in {"hunter_level", "inventory_count"} else 1

    def pending_edits(self) -> list[tuple[SaveRow, int]]:
        """Return staged scalar values for the service to commit."""
        return [
            (self._table.rows[row_index], value)
            for (row_index, _column), value in self._pending_values.items()
        ]

    def undo(self) -> None:
        """Restore the preceding staged value without touching the save file."""
        if not self._history:
            return
        key, old_pending, new_pending = self._history.pop()
        self._set_pending_value(key, old_pending)
        self._redo_history.append((key, old_pending, new_pending))
        self._emit_change(key)

    def redo(self) -> None:
        """Reapply a locally staged value without touching the save file."""
        if not self._redo_history:
            return
        key, old_pending, new_pending = self._redo_history.pop()
        self._set_pending_value(key, new_pending)
        self._history.append((key, old_pending, new_pending))
        self._emit_change(key)

    def revert_index(self, index: QModelIndex) -> None:
        key = (index.row(), index.column())
        if key not in self._pending_values:
            return
        del self._pending_values[key]
        self._history.clear()
        self._redo_history.clear()
        self._emit_change(key)

    def revert_row(self, row_index: int) -> None:
        keys = [key for key in self._pending_values if key[0] == row_index]
        if not keys:
            return
        for key in keys:
            del self._pending_values[key]
        self._history.clear()
        self._redo_history.clear()
        left = self.index(row_index, 0)
        right = self.index(row_index, self.columnCount() - 1)
        self.dataChanged.emit(left, right, [Qt.ItemDataRole.DisplayRole, self.modified_role])
        self.modifications_changed.emit(bool(self._pending_values))
        self.history_changed.emit(False, False)

    def rowCount(self, parent: ModelIndex = QModelIndex()) -> int:  # noqa: N802, B008
        return 0 if parent.isValid() else len(self._table.rows)

    def columnCount(self, parent: ModelIndex = QModelIndex()) -> int:  # noqa: N802, B008
        return 0 if parent.isValid() else len(self._table.columns)

    def data(self, index: ModelIndex, role: int = Qt.ItemDataRole.DisplayRole) -> Any:
        if not index.isValid():
            return None
        value = self._pending_values.get(
            (index.row(), index.column()), self._table.rows[index.row()].values[index.column()]
        )
        if role == Qt.ItemDataRole.DisplayRole:
            return "NULL" if value is None else str(value)
        if role == Qt.ItemDataRole.EditRole or role == self.raw_value_role:
            return value
        if role == self.modified_role:
            return (index.row(), index.column()) in self._pending_values
        if role == Qt.ItemDataRole.TextAlignmentRole and isinstance(value, (int, float)):
            return int(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        if role == Qt.ItemDataRole.FontRole:
            column_name = self._table.columns[index.column()][0].lower()
            if "id" in column_name or "storage" in column_name:
                font = QFont("Cascadia Mono")
                font.setPointSize(9)
                return font
            if value is None:
                font = QFont()
                font.setItalic(True)
                return font
            if role == Qt.ItemDataRole.ToolTipRole:
                row = self._table.rows[index.row()]
                if index.column() == self.value_column_for_row(row):
                    return (
                        "Enter an integer value. The mapped save rule is validated before saving."
                    )
        return None

    def flags(self, index: ModelIndex) -> Qt.ItemFlag:
        if not index.isValid():
            return Qt.ItemFlag.NoItemFlags
        flags = Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable
        row = self._table.rows[index.row()]
        if index.column() == self.value_column_for_row(row):
            return flags | Qt.ItemFlag.ItemIsEditable
        if row.mapping_for_column(index.column()) is not None:
            return flags | Qt.ItemFlag.ItemIsEditable
        return flags

    def setData(self, index: ModelIndex, value: Any, role: int = Qt.ItemDataRole.EditRole) -> bool:  # noqa: N802
        if role != Qt.ItemDataRole.EditRole or not index.isValid():
            return False
        row = self._table.rows[index.row()]
        if index.column() == self.value_column_for_row(row):
            try:
                numeric_value = int(value)
            except (TypeError, ValueError):
                return False
            original_value = row.values[index.column()]
            key = (index.row(), index.column())
            old_pending = self._pending_values.get(key)
            new_pending = None if numeric_value == original_value else numeric_value
            if old_pending == new_pending:
                return True
            self._set_pending_value(key, new_pending)
            self._history.append((key, old_pending, new_pending))
            self._redo_history.clear()
            self._emit_change(key)
            return True
        mapping = row.mapping_for_column(index.column())
        if mapping is not None:
            # Mapped display-name edits are editor metadata: they are persisted
            # immediately through the override store (never staged, never
            # written to the save file), so ownership is handed to whoever
            # connects to this signal rather than tracked as a pending edit.
            self.mapping_edit_requested.emit(mapping, str(value).strip())
            return True
        return False

    def _set_pending_value(self, key: tuple[int, int], value: int | None) -> None:
        if value is None:
            self._pending_values.pop(key, None)
        else:
            self._pending_values[key] = value

    def _emit_change(self, key: tuple[int, int]) -> None:
        index = self.index(*key)
        self.dataChanged.emit(index, index, [Qt.ItemDataRole.DisplayRole, self.modified_role])
        self.modifications_changed.emit(bool(self._pending_values))
        self.history_changed.emit(bool(self._history), bool(self._redo_history))

    def headerData(
        self,
        section: int,
        orientation: Qt.Orientation,
        role: int = Qt.ItemDataRole.DisplayRole,
    ) -> Any:  # noqa: N802
        if role == Qt.ItemDataRole.DisplayRole and orientation == Qt.Orientation.Horizontal:
            return self._table.columns[section][0]
        return None
