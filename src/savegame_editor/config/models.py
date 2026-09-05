"""Typed values stored in the local editor configuration."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any


def _optional_path(value: object) -> Path | None:
    if not isinstance(value, str) or not value.strip():
        return None
    return Path(value).expanduser()


@dataclass(frozen=True, slots=True)
class EditorSettings:
    """User-specific settings, persisted outside the repository."""

    default_game_data_path: Path | None = None
    steam_id: str = ""
    encrypted_db_path: Path | None = None
    accent_theme: str = "Sleek Purple"
    custom_accent_color: str = ""

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> EditorSettings:
        steam_id = data.get("steam_id", "")
        accent_theme = data.get("accent_theme", "Sleek Purple")
        custom_accent_color = data.get("custom_accent_color", "")
        return cls(
            default_game_data_path=_optional_path(data.get("default_game_data_path")),
            steam_id=steam_id.strip() if isinstance(steam_id, str) else "",
            encrypted_db_path=_optional_path(data.get("encrypted_db_path")),
            accent_theme=accent_theme if isinstance(accent_theme, str) else "Sleek Purple",
            custom_accent_color=custom_accent_color if isinstance(custom_accent_color, str) else "",
        )

    def to_dict(self) -> dict[str, str]:
        return {
            "default_game_data_path": str(self.default_game_data_path or ""),
            "steam_id": self.steam_id,
            "encrypted_db_path": str(self.encrypted_db_path or ""),
            "accent_theme": self.accent_theme,
            "custom_accent_color": self.custom_accent_color,
        }
