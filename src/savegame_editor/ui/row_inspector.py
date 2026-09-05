"""Resizable row-detail editor for values that need closer inspection."""

from __future__ import annotations

from typing import Any

from PySide6.QtCore import QModelIndex, Signal
from PySide6.QtWidgets import (
    QApplication,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from savegame_editor.services import SaveRow


class RowInspector(QWidget):
    """Show selected-row values and stage one scalar field at a time."""

    apply_requested = Signal(QModelIndex, str)
    revert_field_requested = Signal(QModelIndex)
    revert_row_requested = Signal(int)

    def __init__(self) -> None:
        super().__init__()
        self.setObjectName("inspector")
        self._index = QModelIndex()
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(8)

        title = QLabel("ROW INSPECTOR")
        title.setObjectName("viewTitle")
        layout.addWidget(title)
        self._row_key = QLabel("Select a row to inspect its values")
        self._row_key.setObjectName("detailLabel")
        self._row_key.setWordWrap(True)
        layout.addWidget(self._row_key)
        self._state = QLabel()
        self._state.setObjectName("detailLabel")
        layout.addWidget(self._state)

        form = QFormLayout()
        self._field_name = QLabel("-")
        self._field_name.setTextInteractionFlags(self._field_name.textInteractionFlags())
        form.addRow("Editable field", self._field_name)
        self._value_input = QLineEdit()
        self._value_input.setEnabled(False)
        form.addRow("Staged value", self._value_input)
        layout.addLayout(form)

        self._details = QTextEdit()
        self._details.setReadOnly(True)
        self._details.setPlaceholderText("Row data will appear here.")
        layout.addWidget(self._details, 1)

        actions = QHBoxLayout()
        self._apply = QPushButton("Apply")
        self._apply.setObjectName("primary")
        self._apply.clicked.connect(self._emit_apply)
        actions.addWidget(self._apply)
        copy = QPushButton("Copy value")
        copy.clicked.connect(self._copy_value)
        actions.addWidget(copy)
        layout.addLayout(actions)

        revert_actions = QHBoxLayout()
        self._revert_field = QPushButton("Revert field")
        self._revert_field.clicked.connect(self._emit_revert_field)
        revert_actions.addWidget(self._revert_field)
        self._revert_row = QPushButton("Revert row")
        self._revert_row.clicked.connect(self._emit_revert_row)
        revert_actions.addWidget(self._revert_row)
        layout.addLayout(revert_actions)
        self._set_actions_enabled(False)

    def set_row(
        self,
        table_name: str,
        row: SaveRow | None,
        index: QModelIndex,
        editable_column: int | None,
        column_names: list[str],
        modified: bool,
        value: Any = None,
    ) -> None:
        self._index = index
        if not row:
            self._row_key.setText("Select a row to inspect its values")
            self._state.clear()
            self._field_name.setText("-")
            self._value_input.clear()
            self._details.clear()
            self._set_actions_enabled(False)
            return
        key = row.values[0] if row.values else "Row"
        self._row_key.setText(f"Table: {table_name}\nKey: {key}")
        self._state.setText("Staged changes" if modified else "No staged changes")
        self._details.setPlainText(
            "\n".join(
                f"{name}: {item}" for name, item in zip(column_names, row.values, strict=True)
            )
        )
        if editable_column is None:
            self._field_name.setText("Read-only row")
            self._value_input.clear()
            self._set_actions_enabled(False)
            return
        self._field_name.setText(column_names[editable_column])
        self._value_input.setText("" if value is None else str(value))
        self._set_actions_enabled(True)

    def _set_actions_enabled(self, enabled: bool) -> None:
        self._value_input.setEnabled(enabled)
        self._apply.setEnabled(enabled)
        self._revert_field.setEnabled(enabled)
        self._revert_row.setEnabled(enabled)

    def _emit_apply(self) -> None:
        if self._index.isValid():
            self.apply_requested.emit(self._index, self._value_input.text())

    def _emit_revert_field(self) -> None:
        if self._index.isValid():
            self.revert_field_requested.emit(self._index)

    def _emit_revert_row(self) -> None:
        if self._index.isValid():
            self.revert_row_requested.emit(self._index.row())

    def _copy_value(self) -> None:
        QApplication.clipboard().setText(self._value_input.text())
