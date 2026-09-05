"""Delegate that marks locally staged cells without adding per-cell widgets."""

from __future__ import annotations

from PySide6.QtCore import QModelIndex, QPersistentModelIndex
from PySide6.QtGui import QColor, QPainter
from PySide6.QtWidgets import QStyledItemDelegate, QStyleOptionViewItem

from savegame_editor.ui.theme import status_warning_color

from .save_table_model import SaveTableModel


class ModifiedCellDelegate(QStyledItemDelegate):
    """Paint a restrained warning marker for a staged cell."""

    def paint(
        self,
        painter: QPainter,
        option: QStyleOptionViewItem,
        index: QModelIndex | QPersistentModelIndex,
    ) -> None:
        super().paint(painter, option, index)
        if not index.data(SaveTableModel.modified_role):
            return
        painter.fillRect(
            option.rect.x(),
            option.rect.y(),
            3,
            option.rect.height(),
            QColor(status_warning_color()),
        )
