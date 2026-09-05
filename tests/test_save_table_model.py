from PySide6.QtCore import Qt

from savegame_editor.services import SaveRow, SaveTable
from savegame_editor.ui.models import SaveTableModel


def test_staged_edit_can_be_undone_and_redone() -> None:
    model = SaveTableModel()
    row = SaveRow(("Gold", 100, "Storage", "Verified"), "gold")
    model.set_table(SaveTable([("Field", 100), ("Current value", 100)], [row]))
    value_index = model.index(0, 1)

    assert model.flags(value_index) & Qt.ItemFlag.ItemIsEditable
    assert model.setData(value_index, "250")
    assert model.pending_edits() == [(row, 250)]
    assert model.data(value_index, SaveTableModel.modified_role)

    model.undo()
    assert model.pending_edits() == []

    model.redo()
    assert model.pending_edits() == [(row, 250)]
