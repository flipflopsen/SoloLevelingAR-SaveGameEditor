"""Compact contextual controls for a save-table view."""

from __future__ import annotations

from collections.abc import Iterable

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QHBoxLayout,
    QLineEdit,
    QMenu,
    QPushButton,
    QStyle,
    QToolButton,
    QWidget,
)


class TableToolbar(QWidget):
    """Expose dense table controls without owning save or database behavior."""

    table_selected = Signal(str)
    search_changed = Signal(str)
    modified_only_changed = Signal(bool)
    reload_requested = Signal()
    save_requested = Signal()
    export_requested = Signal()
    undo_requested = Signal()
    redo_requested = Signal()
    inspector_toggled = Signal(bool)
    column_visibility_changed = Signal(int, bool)

    def __init__(self, views: Iterable[tuple[str, str]]) -> None:
        super().__init__()
        self.setObjectName("toolbar")
        layout = QHBoxLayout(self)
        layout.setContentsMargins(8, 7, 8, 7)
        layout.setSpacing(6)

        self._table_selector = QComboBox()
        for label, view in views:
            self._table_selector.addItem(label, view)
        self._table_selector.currentIndexChanged.connect(self._emit_table_selected)
        layout.addWidget(self._table_selector)

        self._modified_only = QCheckBox("Modified only")
        self._modified_only.toggled.connect(self.modified_only_changed)
        layout.addWidget(self._modified_only)

        self._reload_button = self._tool_button("Reload", QStyle.StandardPixmap.SP_BrowserReload)
        self._reload_button.clicked.connect(self.reload_requested)
        layout.addWidget(self._reload_button)

        self._undo_button = self._tool_button("Undo", QStyle.StandardPixmap.SP_ArrowBack)
        self._undo_button.setEnabled(False)
        self._undo_button.clicked.connect(self.undo_requested)
        layout.addWidget(self._undo_button)
        self._redo_button = self._tool_button("Redo", QStyle.StandardPixmap.SP_ArrowForward)
        self._redo_button.setEnabled(False)
        self._redo_button.clicked.connect(self.redo_requested)
        layout.addWidget(self._redo_button)

        self._search = QLineEdit()
        self._search.setPlaceholderText("Search current table...")
        self._search.setClearButtonEnabled(True)
        self._search.textChanged.connect(self.search_changed)
        layout.addWidget(self._search, 1)

        self._columns_button = self._tool_button(
            "Columns", QStyle.StandardPixmap.SP_FileDialogDetailedView
        )
        self._columns_menu = QMenu(self)
        self._columns_button.setMenu(self._columns_menu)
        self._columns_button.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        layout.addWidget(self._columns_button)

        self._inspector_button = self._tool_button(
            "Inspector", QStyle.StandardPixmap.SP_FileDialogInfoView
        )
        self._inspector_button.setCheckable(True)
        self._inspector_button.toggled.connect(self.inspector_toggled)
        layout.addWidget(self._inspector_button)

        export_button = self._tool_button("Export", QStyle.StandardPixmap.SP_DialogSaveButton)
        export_button.clicked.connect(self.export_requested)
        layout.addWidget(export_button)

        add_row_button = QPushButton("Add row")
        add_row_button.setToolTip("Adding rows is unavailable for verified save mappings.")
        add_row_button.setEnabled(False)
        layout.addWidget(add_row_button)

        self._save_button = QPushButton("Save changes")
        self._save_button.setObjectName("primary")
        self._save_button.setIcon(
            self.style().standardIcon(QStyle.StandardPixmap.SP_DialogSaveButton)
        )
        self._save_button.setEnabled(False)
        self._save_button.clicked.connect(self.save_requested)
        layout.addWidget(self._save_button)

    def _tool_button(self, text: str, icon: QStyle.StandardPixmap) -> QToolButton:
        button = QToolButton()
        button.setObjectName("toolbarButton")
        button.setText(text)
        button.setIcon(self.style().standardIcon(icon))
        button.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        return button

    def _emit_table_selected(self, index: int) -> None:
        view = self._table_selector.itemData(index)
        if isinstance(view, str):
            self.table_selected.emit(view)

    def set_current_view(self, view: str) -> None:
        index = self._table_selector.findData(view)
        if index >= 0:
            self._table_selector.blockSignals(True)
            self._table_selector.setCurrentIndex(index)
            self._table_selector.blockSignals(False)

    def set_ready(self, ready: bool) -> None:
        self._reload_button.setEnabled(ready)

    def set_has_modifications(self, has_modifications: bool) -> None:
        self._save_button.setEnabled(has_modifications)

    def set_history_state(self, can_undo: bool, can_redo: bool) -> None:
        self._undo_button.setEnabled(can_undo)
        self._redo_button.setEnabled(can_redo)

    def set_columns(self, columns: list[tuple[str, int]]) -> None:
        self._columns_menu.clear()
        for column, (name, _width) in enumerate(columns):
            action = self._columns_menu.addAction(name)
            action.setCheckable(True)
            action.setChecked(True)
            action.toggled.connect(
                lambda visible, selected_column=column: self.column_visibility_changed.emit(
                    selected_column, visible
                )
            )
