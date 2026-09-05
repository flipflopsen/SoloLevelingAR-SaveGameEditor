"""Persistent settings dialog with assisted local save selection."""

from __future__ import annotations

import asyncio
import re
from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QColorDialog,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from savegame_editor.config import EditorSettings
from savegame_editor.core.paths import derive_dll_directory
from savegame_editor.core.save_discovery import SaveCandidate, discover_save_databases
from savegame_editor.ui.theme import ACCENT_THEMES, resolve_accent_theme


class SettingsDialog(QDialog):
    """Edit local paths, credentials, and the selected discovered save."""

    settings_saved = Signal(object)

    def __init__(self, settings: EditorSettings, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Settings")
        self.setMinimumWidth(680)
        self._candidates: list[SaveCandidate] = []
        self._selected_database_path = settings.encrypted_db_path
        self._build_ui(settings)
        self._update_dll_path()
        self._rescan()

    def _build_ui(self, settings: EditorSettings) -> None:
        layout = QVBoxLayout(self)
        form = QFormLayout()
        form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.ExpandingFieldsGrow)

        self._game_data_input = QLineEdit(str(settings.default_game_data_path or ""))
        self._game_data_input.textChanged.connect(self._update_dll_path)
        form.addRow(
            "GameData directory", self._path_field(self._game_data_input, self._choose_game_data)
        )
        self._derived_dll_label = QLabel()
        self._derived_dll_label.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse
        )
        form.addRow("Derived SQLCipher directory", self._derived_dll_label)

        self._steam_id_input = QLineEdit(settings.steam_id)
        self._steam_id_input.setPlaceholderText("SteamID64 or an already-derived save key")
        form.addRow("Steam ID64 or save key", self._steam_id_input)

        self._candidate_combo = QComboBox()
        self._candidate_combo.setPlaceholderText("Select a discovered save database")
        self._candidate_combo.setEnabled(False)
        self._candidate_combo.currentIndexChanged.connect(self._choose_candidate)
        self._rescan_button = QPushButton("Rescan")
        self._rescan_button.clicked.connect(self._rescan)
        candidate_row = QWidget()
        candidate_layout = QHBoxLayout(candidate_row)
        candidate_layout.setContentsMargins(0, 0, 0, 0)
        candidate_layout.addWidget(self._candidate_combo, 1)
        candidate_layout.addWidget(self._rescan_button)
        form.addRow("Discovered local saves", candidate_row)

        appearance_label = QLabel("Appearance")
        appearance_label.setObjectName("viewTitle")
        form.addRow(appearance_label)
        self._accent_theme_combo = QComboBox()
        self._accent_theme_combo.addItems([theme.name for theme in ACCENT_THEMES])
        selected_theme = self._accent_theme_combo.findText(settings.accent_theme)
        self._accent_theme_combo.setCurrentIndex(max(selected_theme, 0))
        self._accent_theme_combo.currentTextChanged.connect(self._update_theme_preview)
        form.addRow("Accent theme", self._accent_theme_combo)
        self._custom_accent_input = QLineEdit(settings.custom_accent_color)
        self._custom_accent_input.setPlaceholderText("#RRGGBB (optional)")
        self._custom_accent_input.textChanged.connect(self._update_theme_preview)
        custom_color_row = QWidget()
        custom_color_layout = QHBoxLayout(custom_color_row)
        custom_color_layout.setContentsMargins(0, 0, 0, 0)
        custom_color_layout.addWidget(self._custom_accent_input, 1)
        color_picker_button = QPushButton("Pick color")
        color_picker_button.clicked.connect(self._choose_custom_accent)
        custom_color_layout.addWidget(color_picker_button)
        form.addRow("Custom accent", custom_color_row)
        self._theme_preview = QLabel()
        self._theme_preview.setFixedHeight(22)
        form.addRow("Accent preview", self._theme_preview)
        self._update_theme_preview(self._accent_theme_combo.currentText())
        layout.addLayout(form)

        self._feedback = QLabel()
        self._feedback.setWordWrap(True)
        layout.addWidget(self._feedback)
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self._save)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _path_field(self, line_edit: QLineEdit, chooser: object) -> QWidget:
        row = QWidget()
        layout = QHBoxLayout(row)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(line_edit, 1)
        browse_button = QPushButton("Browse")
        browse_button.clicked.connect(chooser)  # type: ignore[arg-type]
        layout.addWidget(browse_button)
        return row

    def _choose_game_data(self) -> None:
        selected = QFileDialog.getExistingDirectory(
            self, "Select GameData directory", self._game_data_input.text()
        )
        if selected:
            self._game_data_input.setText(selected)
            self._update_dll_path()

    def _update_dll_path(self) -> None:
        path = self._path_from_input(self._game_data_input)
        self._derived_dll_label.setText(
            str(derive_dll_directory(path)) if path else "Select GameData directory"
        )

    def _rescan(self) -> None:
        self._rescan_button.setEnabled(False)
        self._feedback.setText("Scanning local save slots...")
        asyncio.create_task(self._scan_candidates(self._steam_id_input.text().strip()))

    async def _scan_candidates(self, steam_id: str) -> None:
        candidates = await asyncio.to_thread(discover_save_databases, steam_id)
        self._candidates = candidates
        self._candidate_combo.blockSignals(True)
        self._candidate_combo.clear()
        selected_index = -1
        for index, candidate in enumerate(candidates):
            self._candidate_combo.addItem(candidate.display_name)
            if candidate.path == self._selected_database_path:
                selected_index = index
        self._candidate_combo.setCurrentIndex(selected_index)
        self._candidate_combo.blockSignals(False)
        self._candidate_combo.setEnabled(bool(candidates))
        if selected_index == -1:
            self._selected_database_path = None
        self._rescan_button.setEnabled(True)
        if candidates:
            self._feedback.setText(
                f"Found {len(candidates)} local save database(s). Select one to use it."
            )
        elif steam_id:
            self._feedback.setText(
                "No save databases found. Discovery requires a conventional 17-digit SteamID64."
            )
        else:
            self._feedback.setText("Enter a SteamID64 and rescan to find local save databases.")

    def _choose_candidate(self, index: int) -> None:
        if 0 <= index < len(self._candidates):
            self._selected_database_path = self._candidates[index].path

    def _update_theme_preview(self, theme_name: str) -> None:
        custom_color = self._custom_accent_input.text().strip()
        theme = resolve_accent_theme(theme_name, custom_color)
        valid = not custom_color or bool(re.fullmatch(r"#[0-9A-Fa-f]{6}", custom_color))
        self._custom_accent_input.setStyleSheet("" if valid else "border-color: #E7626C;")
        self._theme_preview.setStyleSheet(
            f"background: {theme.primary}; border: 1px solid {theme.indicator}; border-radius: 4px;"
        )

    def _choose_custom_accent(self) -> None:
        current_color = resolve_accent_theme(
            self._accent_theme_combo.currentText(), self._custom_accent_input.text()
        ).primary
        selected = QColorDialog.getColor(QColor(current_color), self, "Select accent color")
        if selected.isValid():
            self._custom_accent_input.setText(selected.name())

    def _save(self) -> None:
        game_data_path = self._path_from_input(self._game_data_input)
        if game_data_path and not game_data_path.is_dir():
            QMessageBox.warning(
                self, "Invalid GameData directory", "Choose an existing GameData directory."
            )
            return
        custom_accent_color = self._custom_accent_input.text().strip().upper()
        if custom_accent_color and not re.fullmatch(r"#[0-9A-F]{6}", custom_accent_color):
            QMessageBox.warning(
                self, "Invalid accent color", "Enter a hex color in the form #RRGGBB."
            )
            return
        settings = EditorSettings(
            default_game_data_path=game_data_path,
            steam_id=self._steam_id_input.text().strip(),
            encrypted_db_path=self._selected_database_path,
            accent_theme=self._accent_theme_combo.currentText(),
            custom_accent_color=custom_accent_color,
        )
        self.settings_saved.emit(settings)
        self.accept()

    @staticmethod
    def _path_from_input(line_edit: QLineEdit) -> Path | None:
        value = line_edit.text().strip().strip('"')
        return Path(value).expanduser() if value else None
