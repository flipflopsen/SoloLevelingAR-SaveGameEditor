"""The compact two-region PySide6 workspace for local save editing."""

from __future__ import annotations

import asyncio
import csv
import logging
from collections.abc import Coroutine
from concurrent.futures import Executor
from pathlib import Path

from PySide6.QtCore import QModelIndex, Qt
from PySide6.QtWidgets import (
    QAbstractItemView,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QMessageBox,
    QSplitter,
    QTableView,
    QVBoxLayout,
    QWidget,
)

from savegame_editor.config import EditorSettings, SettingsStore, SettingsStoreError
from savegame_editor.core.encryption import SaveEditorError
from savegame_editor.core.validation import connection_issues
from savegame_editor.services import MappingRef, SaveRow, SaveService, SaveTable

from .models import ModifiedCellDelegate, SaveTableModel, TableFilterProxy
from .row_inspector import RowInspector
from .settings_dialog import SettingsDialog
from .sidebar import AppSidebar
from .table_toolbar import TableToolbar
from .theme import application_stylesheet

LOGGER = logging.getLogger(__name__)
NAVIGATION = (
    ("Player Stats", "player"),
    ("Hunters", "hunters"),
    ("Inventory", "inventory"),
    ("Owned Items", "owned"),
    ("Cosmetics", "cosmetics"),
    ("Titles", "titles"),
    ("Achievements", "achievements"),
    ("Difficulty", "difficulty"),
)


class MainWindow(QMainWindow):
    """Coordinate the technical UI without placing filesystem or SQL logic in widgets."""

    def __init__(
        self,
        service: SaveService,
        settings_store: SettingsStore,
        settings: EditorSettings,
        executor: Executor,
    ) -> None:
        super().__init__()
        self._service = service
        self._settings_store = settings_store
        self._settings = settings
        self._executor = executor
        self._current_view = "player"
        self._current_columns: list[str] = []
        self._tasks: set[asyncio.Task[None]] = set()
        self.setWindowTitle("Solo Leveling Save Editor")
        self.resize(1320, 800)
        self.setMinimumSize(1000, 620)
        self._build_ui()
        self._apply_theme()
        self._update_connection_state(open_when_ready=False)

    def start(self) -> None:
        """Begin asynchronous save loading after qasync has started."""
        self._update_connection_state()

    def _build_ui(self) -> None:
        root = QWidget()
        root.setObjectName("root")
        self.setCentralWidget(root)
        root_layout = QHBoxLayout(root)
        root_layout.setContentsMargins(0, 0, 0, 0)
        root_layout.setSpacing(0)

        self._sidebar = AppSidebar(NAVIGATION, self._current_view)
        self._sidebar.view_selected.connect(self._select_view)
        self._sidebar.settings_requested.connect(self._show_settings)
        root_layout.addWidget(self._sidebar)

        workspace = QWidget()
        workspace.setObjectName("workspace")
        workspace_layout = QVBoxLayout(workspace)
        workspace_layout.setContentsMargins(16, 14, 16, 16)
        workspace_layout.setSpacing(10)
        root_layout.addWidget(workspace, 1)

        context_header = QWidget()
        context_header.setObjectName("contextHeader")
        header_layout = QVBoxLayout(context_header)
        header_layout.setContentsMargins(12, 10, 12, 10)
        header_layout.setSpacing(3)
        page_title = QLabel("Raw Tables")
        page_title.setObjectName("pageTitle")
        header_layout.addWidget(page_title)
        title_row = QHBoxLayout()
        self._view_title = QLabel("Player Stats")
        self._view_title.setObjectName("viewTitle")
        title_row.addWidget(self._view_title)
        self._record_count = QLabel("No rows loaded")
        self._record_count.setObjectName("detailLabel")
        title_row.addWidget(self._record_count)
        title_row.addStretch()
        self._state_label = QLabel()
        title_row.addWidget(self._state_label)
        header_layout.addLayout(title_row)
        self._path_status = QLabel()
        self._path_status.setObjectName("pathStatus")
        self._path_status.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        header_layout.addWidget(self._path_status)
        workspace_layout.addWidget(context_header)

        self._model = SaveTableModel(self)
        self._model.modifications_changed.connect(self._on_modifications_changed)
        self._model.mapping_edit_requested.connect(self._request_mapping_edit)
        self._filter_table = TableFilterProxy(self)
        self._filter_table.setSourceModel(self._model)
        self._toolbar = TableToolbar(NAVIGATION)
        self._toolbar.table_selected.connect(self._select_view)
        self._toolbar.search_changed.connect(self._filter_table.set_search_text)
        self._toolbar.modified_only_changed.connect(self._filter_table.set_modified_only)
        self._toolbar.reload_requested.connect(self._reload)
        self._toolbar.save_requested.connect(self._save_pending_edits)
        self._toolbar.undo_requested.connect(self._model.undo)
        self._toolbar.redo_requested.connect(self._model.redo)
        self._toolbar.inspector_toggled.connect(self._toggle_inspector)
        self._toolbar.column_visibility_changed.connect(self._set_column_visibility)
        self._toolbar.export_requested.connect(self._export_current_table)
        self._model.history_changed.connect(self._toolbar.set_history_state)
        workspace_layout.addWidget(self._toolbar)

        self._table = QTableView()
        self._table.setModel(self._filter_table)
        self._table.setItemDelegate(ModifiedCellDelegate(self._table))
        self._table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self._table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self._table.setEditTriggers(
            QAbstractItemView.EditTrigger.DoubleClicked
            | QAbstractItemView.EditTrigger.EditKeyPressed
        )
        self._table.setAlternatingRowColors(True)
        self._table.setSortingEnabled(True)
        self._table.verticalHeader().setVisible(False)
        self._table.horizontalHeader().setStretchLastSection(True)
        self._table.selectionModel().currentRowChanged.connect(self._show_selected_row)

        self._inspector = RowInspector()
        self._inspector.apply_requested.connect(self._apply_inspector_value)
        self._inspector.revert_field_requested.connect(self._model.revert_index)
        self._inspector.revert_row_requested.connect(self._model.revert_row)
        self._inspector.setVisible(False)
        self._splitter = QSplitter()
        self._splitter.addWidget(self._table)
        self._splitter.addWidget(self._inspector)
        self._splitter.setStretchFactor(0, 1)
        self._splitter.setSizes([960, 360])
        workspace_layout.addWidget(self._splitter, 1)

    def _apply_theme(self) -> None:
        self.setStyleSheet(
            application_stylesheet(self._settings.accent_theme, self._settings.custom_accent_color)
        )

    def _show_settings(self) -> None:
        dialog = SettingsDialog(self._settings, self)
        dialog.settings_saved.connect(self._save_settings)
        dialog.exec()
        self._sidebar.select_view(self._current_view)

    def _save_settings(self, settings: EditorSettings) -> None:
        try:
            self._settings_store.save(settings)
        except SettingsStoreError as error:
            QMessageBox.critical(self, "Settings not saved", str(error))
            return
        self._settings = settings
        self._apply_theme()
        self._launch(self._close_and_refresh())

    async def _close_and_refresh(self) -> None:
        await asyncio.get_running_loop().run_in_executor(self._executor, self._service.close)
        self._clear_loaded_view()
        self._update_connection_state()

    def _clear_loaded_view(self) -> None:
        """Clear all view-bound UI state so no stale rows/columns remain visible.

        Used both when explicitly closing a save and after a failed
        open/reload, so a failed load never leaves the previous view's rows
        displayed under a different (or "invalid") title/status.
        """
        self._model.set_table(SaveTable([], []))
        self._current_columns = []
        self._record_count.setText("No rows loaded")
        self._toolbar.set_columns([])

    def _update_connection_state(self, open_when_ready: bool = True) -> None:
        issues = connection_issues(self._settings)
        ready = not issues
        connected = ready and self._service.save_path is not None
        self._toolbar.set_ready(connected)
        if self._service.save_path:
            self._path_status.setText(f"Active save: {self._service.save_path.name}")
        elif issues:
            self._path_status.setText(issues[0])
        else:
            self._path_status.setText("Ready to open the selected local save.")
        self._set_state(
            "Loaded" if connected else "Configuration required", "ready" if connected else "error"
        )
        if open_when_ready and ready and self._service.save_path is None:
            self._launch(self._open_save())

    def _set_state(self, text: str, state: str) -> None:
        self._state_label.setText(text)
        self._state_label.setObjectName(
            {"ready": "statusReady", "warning": "statusWarning", "error": "statusError"}[state]
        )
        self._state_label.style().unpolish(self._state_label)
        self._state_label.style().polish(self._state_label)

    def _select_view(self, view: str) -> None:
        if view == self._current_view:
            return
        if not self._confirm_discard_pending():
            self._toolbar.set_current_view(self._current_view)
            self._sidebar.select_view(self._current_view)
            return
        self._current_view = view
        self._view_title.setText(next(label for label, name in NAVIGATION if name == view))
        self._toolbar.set_current_view(view)
        self._sidebar.select_view(view)
        if self._service.save_path:
            self._launch(self._load_view())

    def _reload(self) -> None:
        if self._service.save_path and self._confirm_discard_pending():
            self._launch(self._load_view())

    def _confirm_discard_pending(self) -> bool:
        if not self._model.pending_edits():
            return True
        return (
            QMessageBox.question(
                self,
                "Discard staged edits?",
                "Reloading or switching views will discard unsaved staged changes.",
            )
            == QMessageBox.StandardButton.Yes
        )

    async def _open_save(self) -> None:
        self._path_status.setText("Opening local encrypted save...")
        self._set_state("Loading", "warning")
        had_previous_save = self._service.save_path is not None
        try:
            warning = await asyncio.get_running_loop().run_in_executor(
                self._executor, self._service.open, self._settings
            )
        except SaveEditorError as error:
            if had_previous_save:
                # open() is all-or-nothing: the previous save is still fully
                # active. Report the new failure without implying the
                # editor is disconnected or showing stale/mismatched data.
                self._path_status.setText(
                    f"Could not switch save (still showing the previous save): {error}"
                )
                self._set_state("Loaded", "ready")
            else:
                self._clear_loaded_view()
                self._path_status.setText(str(error))
                self._set_state("Invalid", "error")
            return
        save_path = self._service.save_path
        self._path_status.setText(
            warning or f"Active save: {save_path.name if save_path else 'selected local save'}"
        )
        self._toolbar.set_ready(True)
        self._set_state("Loaded", "ready")
        await self._load_view()

    async def _load_view(self) -> None:
        self._set_state("Loading", "warning")
        try:
            table = await asyncio.get_running_loop().run_in_executor(
                self._executor, self._service.read_view, self._current_view
            )
        except SaveEditorError as error:
            # Never leave a previous view's rows/columns on screen under a
            # new title after a failed load; clear before reporting the error.
            self._clear_loaded_view()
            self._path_status.setText(str(error))
            self._set_state("Error", "error")
            return
        self._model.set_table(table)
        self._toolbar.set_columns(table.columns)
        self._current_columns = [name for name, _width in table.columns]
        self._record_count.setText(f"{len(table.rows):,} records")
        for index, (_name, width) in enumerate(table.columns):
            self._table.setColumnHidden(index, False)
            self._table.setColumnWidth(index, width)
        self._set_state("Loaded", "ready")

    def _on_modifications_changed(self, has_modifications: bool) -> None:
        self._toolbar.set_has_modifications(has_modifications)
        if has_modifications:
            self._set_state("Unsaved changes", "warning")
        elif self._service.save_path:
            self._set_state("Loaded", "ready")
        self._show_selected_row(self._table.currentIndex(), QModelIndex())

    def _set_column_visibility(self, column: int, visible: bool) -> None:
        self._table.setColumnHidden(column, not visible)

    def _toggle_inspector(self, visible: bool) -> None:
        self._inspector.setVisible(visible)
        if visible:
            self._splitter.setSizes([max(self.width() - 400, 650), 360])
            self._show_selected_row(self._table.currentIndex(), QModelIndex())

    def _show_selected_row(self, current: QModelIndex, _previous: QModelIndex) -> None:
        source_index = self._filter_table.mapToSource(current)
        row = self._model.row_for_index(source_index)
        value_column = self._model.value_column_for_row(row) if row else None
        value = (
            self._model.data(
                self._model.index(source_index.row(), value_column), self._model.raw_value_role
            )
            if row and value_column is not None
            else None
        )
        modified = bool(
            row
            and any(
                self._model.data(
                    self._model.index(source_index.row(), column), self._model.modified_role
                )
                for column in range(self._model.columnCount())
            )
        )
        self._inspector.set_row(
            self._view_title.text(),
            row,
            source_index,
            value_column,
            self._current_columns,
            modified,
            value,
        )

    def _apply_inspector_value(self, source_index: QModelIndex, value: str) -> None:
        self._model.setData(source_index, value)
        self._show_selected_row(self._table.currentIndex(), QModelIndex())

    def _request_mapping_edit(self, mapping: MappingRef, value: str) -> None:
        self._launch(self._apply_mapping_edit(mapping, value))

    async def _apply_mapping_edit(self, mapping: MappingRef, value: str) -> None:
        """Persist a display-name override, then fully reload the current view.

        Overrides are editor metadata only: they never touch the save file
        and take effect immediately, but the table is reloaded from the
        service so every displayed row (and any future reload or save
        switch) reflects the same, single source of truth.
        """
        try:
            await asyncio.get_running_loop().run_in_executor(
                self._executor, self._service.set_name_override, mapping, value
            )
        except SaveEditorError as error:
            QMessageBox.warning(self, "Display name not saved", str(error))
            return
        await self._load_view()

    def _save_pending_edits(self) -> None:
        edits = self._model.pending_edits()
        if not edits:
            return
        if (
            QMessageBox.question(
                self,
                "Save staged changes",
                f"Apply {len(edits)} change(s)? A full save backup will be created first.",
            )
            != QMessageBox.StandardButton.Yes
        ):
            return
        self._launch(self._apply_pending_edits(edits))

    async def _apply_pending_edits(self, edits: list[tuple[SaveRow, int]]) -> None:
        try:
            backup = await asyncio.get_running_loop().run_in_executor(
                self._executor, self._service.apply_edits, edits
            )
        except SaveEditorError as error:
            QMessageBox.warning(self, "Changes were not applied", str(error))
            return
        self._path_status.setText(f"Saved {len(edits)} change(s). Full backup: {backup.name}")
        await self._load_view()

    def _export_current_table(self) -> None:
        if self._filter_table.rowCount() == 0:
            return
        destination, _ = QFileDialog.getSaveFileName(
            self, "Export current table", f"{self._current_view}.csv", "CSV files (*.csv)"
        )
        if not destination:
            return
        try:
            with Path(destination).open("w", encoding="utf-8", newline="") as export_file:
                writer = csv.writer(export_file)
                writer.writerow(
                    [
                        self._filter_table.headerData(column, Qt.Orientation.Horizontal)
                        for column in range(self._filter_table.columnCount())
                    ]
                )
                for row in range(self._filter_table.rowCount()):
                    writer.writerow(
                        [
                            self._filter_table.index(row, column).data(
                                SaveTableModel.raw_value_role
                            )
                            for column in range(self._filter_table.columnCount())
                        ]
                    )
        except OSError as error:
            QMessageBox.warning(self, "Export failed", str(error))
            return
        self._path_status.setText(
            f"Exported {self._filter_table.rowCount():,} visible rows to {Path(destination).name}"
        )

    def _launch(self, coroutine: Coroutine[object, object, None]) -> None:
        task = asyncio.create_task(coroutine)
        self._tasks.add(task)
        task.add_done_callback(self._handle_task_result)

    def _handle_task_result(self, task: asyncio.Task[None]) -> None:
        self._tasks.discard(task)
        if task.cancelled():
            return
        try:
            task.result()
        except Exception:
            LOGGER.exception("Unexpected background editor task failed")
            self._path_status.setText(
                "An unexpected local operation failed. Check the editor log for details."
            )
            self._set_state("Error", "error")
