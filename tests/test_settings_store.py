from pathlib import Path

from savegame_editor.config import EditorSettings, SettingsStore


def test_settings_round_trip(tmp_path: Path) -> None:
    settings_path = tmp_path / "config" / "settings.json"
    expected = EditorSettings(
        default_game_data_path=Path("C:/Games/SL/GameData"),
        steam_id="76561198000000000",
        encrypted_db_path=Path("C:/Saves/LocalSave_1.db"),
        accent_theme="Sleek Green",
        custom_accent_color="#2F9EAA",
    )

    SettingsStore(settings_path).save(expected)

    assert SettingsStore(settings_path).load() == expected


def test_missing_settings_returns_defaults(tmp_path: Path) -> None:
    assert SettingsStore(tmp_path / "missing.json").load() == EditorSettings()
