import os
from pathlib import Path

from savegame_editor.core.paths import save_root_for_steam_id
from savegame_editor.core.save_discovery import discover_save_databases


def test_discovers_all_slots_in_slot_and_modified_order(tmp_path: Path) -> None:
    steam_id = "76561198000000000"
    root = save_root_for_steam_id(steam_id, tmp_path)
    first = root / "SaveFolder" / "Slot1" / "LocalSave_older.db"
    second = root / "SaveFolder" / "Slot1" / "LocalSave_newer.db"
    third = root / "SaveFolder" / "Slot3" / "LocalSave_slot3.db"
    for database_path in (first, second, third):
        database_path.parent.mkdir(parents=True, exist_ok=True)
        database_path.touch()
    os.utime(first, (100, 100))
    os.utime(second, (200, 200))
    os.utime(third, (300, 300))

    candidates = discover_save_databases(steam_id, tmp_path)

    assert [(candidate.slot, candidate.path.name) for candidate in candidates] == [
        (1, "LocalSave_newer.db"),
        (1, "LocalSave_older.db"),
        (3, "LocalSave_slot3.db"),
    ]


def test_non_steam_key_does_not_attempt_folder_discovery(tmp_path: Path) -> None:
    assert discover_save_databases("derived-key-value", tmp_path) == []
