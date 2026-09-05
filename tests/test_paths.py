from pathlib import Path

from savegame_editor.core.paths import derive_dll_directory, save_root_for_steam_id


def test_derive_dll_directory_from_game_data() -> None:
    game_data = Path("C:/Games/SL/GameData")

    assert derive_dll_directory(game_data) == Path(
        "C:/Games/SL/Solo_Leveling_ARISE_OVERDRIVE_Data/Plugins/x86_64"
    )


def test_save_root_uses_supplied_home_directory() -> None:
    home = Path("C:/Users/Editor")

    assert save_root_for_steam_id("76561198000000000", home) == Path(
        "C:/Users/Editor/AppData/LocalLow/NetmarbleNeo/Solo_Leveling_ARISE_OVERDRIVE/76561198000000000"
    )
