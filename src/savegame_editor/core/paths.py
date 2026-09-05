"""Path conventions for the local game installation and save directory."""

from __future__ import annotations

import sys
from pathlib import Path

GAME_INSTALL_DIRECTORY = "Solo_Leveling_ARISE_OVERDRIVE_Data"
SQLCIPHER_PLUGIN_SUBDIRECTORY = Path("Plugins") / "x86_64"
SAVE_VENDOR_DIRECTORY = (
    Path("AppData") / "LocalLow" / "NetmarbleNeo" / "Solo_Leveling_ARISE_OVERDRIVE"
)


def application_root() -> Path:
    """Return the development root or the directory containing a frozen executable."""
    extracted_bundle = getattr(sys, "_MEIPASS", None)
    if extracted_bundle:
        return Path(extracted_bundle)
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parents[3]


def derive_dll_directory(game_data_path: Path) -> Path:
    """Derive the DLL location from a sibling ``GameData`` installation directory."""
    return game_data_path.parent / GAME_INSTALL_DIRECTORY / SQLCIPHER_PLUGIN_SUBDIRECTORY


def save_root_for_steam_id(steam_id: str, home_directory: Path | None = None) -> Path:
    """Return the game save root for a SteamID64 without embedding a username."""
    home = home_directory or Path.home()
    return home / SAVE_VENDOR_DIRECTORY / steam_id
