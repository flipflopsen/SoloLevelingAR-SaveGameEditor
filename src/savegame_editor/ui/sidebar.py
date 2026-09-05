"""Fixed compact navigation for the local save editor."""

from __future__ import annotations

from collections.abc import Iterable

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QButtonGroup, QLabel, QStyle, QToolButton, QVBoxLayout, QWidget


class AppSidebar(QWidget):
    """Present editor views in a narrow technical navigation rail."""

    view_selected = Signal(str)
    settings_requested = Signal()

    def __init__(self, views: Iterable[tuple[str, str]], current_view: str) -> None:
        super().__init__()
        self.setObjectName("sidebar")
        self.setFixedWidth(148)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 16, 10, 14)
        layout.setSpacing(3)

        brand = QLabel("SAVEGAME\nEDITOR")
        brand.setObjectName("brand")
        layout.addWidget(brand)
        context = QLabel("LOCAL DATABASE")
        context.setObjectName("brandSubtle")
        layout.addWidget(context)
        layout.addSpacing(16)

        section = QLabel("TABLE VIEWS")
        section.setObjectName("brandSubtle")
        layout.addWidget(section)
        self._buttons = QButtonGroup(self)
        self._view_buttons: dict[str, QToolButton] = {}
        icons = (
            QStyle.StandardPixmap.SP_FileDialogDetailedView,
            QStyle.StandardPixmap.SP_FileDialogListView,
            QStyle.StandardPixmap.SP_DirIcon,
            QStyle.StandardPixmap.SP_DriveHDIcon,
        )
        for index, (label, view) in enumerate(views):
            button = QToolButton()
            button.setObjectName("navigation")
            button.setText(label)
            button.setIcon(self.style().standardIcon(icons[index % len(icons)]))
            button.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
            button.setCheckable(True)
            button.setChecked(view == current_view)
            button.clicked.connect(
                lambda checked=False, selected=view: self.view_selected.emit(selected)
            )
            self._buttons.addButton(button)
            self._view_buttons[view] = button
            layout.addWidget(button)
        layout.addStretch()

        self._settings_button = QToolButton()
        self._settings_button.setObjectName("navigation")
        self._settings_button.setText("Settings")
        self._settings_button.setIcon(
            self.style().standardIcon(QStyle.StandardPixmap.SP_FileDialogContentsView)
        )
        self._settings_button.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        self._settings_button.clicked.connect(self.settings_requested)
        layout.addWidget(self._settings_button)

    def select_view(self, view: str) -> None:
        """Restore checked navigation after dialogs or programmatic selection."""
        if button := self._view_buttons.get(view):
            button.setChecked(True)
