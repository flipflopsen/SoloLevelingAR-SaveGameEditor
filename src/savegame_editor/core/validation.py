"""Validation for the editor's evidence-scoped write operations."""

from __future__ import annotations

from savegame_editor.config.models import EditorSettings

from .encryption import SaveEditorError
from .paths import derive_dll_directory

LEVEL_ACTIONS = {"main_level", "hunter_level"}
STAT_ACTIONS = {"strength", "vitality", "agility", "intelligence", "perception"}


def validate_edit_value(action: str, value: int) -> None:
    """Validate a target integer before interpolating it into a verified SQL statement."""
    if action == "difficulty" and value not in {2, 3, 4}:
        raise SaveEditorError("Story difficulty must be 2 (Normal), 3 (Hard), or 4 (New Game+).")
    if action in LEVEL_ACTIONS and not 1 <= value <= 75:
        raise SaveEditorError("Level must be between 1 and 75.")
    if action in STAT_ACTIONS and value < 1:
        raise SaveEditorError("Displayed stat values must be at least 1.")
    if action not in LEVEL_ACTIONS | STAT_ACTIONS | {"difficulty"} and value < 0:
        raise SaveEditorError("Values must be non-negative whole numbers.")


def connection_issues(settings: EditorSettings) -> list[str]:
    """Return missing local prerequisites without revealing credential values."""
    issues: list[str] = []
    if not settings.default_game_data_path:
        issues.append("Select the GameData directory in Settings.")
    elif not settings.default_game_data_path.is_dir():
        issues.append("The configured GameData directory does not exist.")
    elif not (derive_dll_directory(settings.default_game_data_path) / "sqlcipher.dll").is_file():
        issues.append("The derived SQLCipher DLL directory does not contain sqlcipher.dll.")
    if not settings.steam_id:
        issues.append("Enter a SteamID64 or save key in Settings.")
    if not settings.encrypted_db_path:
        issues.append("Choose an encrypted save database in Settings.")
    elif not settings.encrypted_db_path.is_file():
        issues.append("The configured encrypted save database does not exist.")
    return issues
