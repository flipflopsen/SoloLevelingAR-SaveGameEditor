"""Small JSON-backed local configuration store."""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Any

from .models import EditorSettings


class SettingsStoreError(RuntimeError):
    """Raised when local settings cannot be read or written safely."""


def default_settings_path() -> Path:
    """Return a platform-appropriate user configuration path, never a project path."""
    config_root = Path(os.environ.get("APPDATA", Path.home() / ".config"))
    return config_root / "SaveGameEditor" / "settings.json"


class SettingsStore:
    """Persists ``EditorSettings`` atomically at an injected local path."""

    def __init__(self, path: Path | None = None) -> None:
        self._path = path or default_settings_path()

    @property
    def path(self) -> Path:
        return self._path

    def load(self) -> EditorSettings:
        if not self._path.is_file():
            return EditorSettings()
        try:
            raw_data: Any = json.loads(self._path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as error:
            raise SettingsStoreError("Could not read local editor settings.") from error
        if not isinstance(raw_data, dict):
            raise SettingsStoreError("Local editor settings must contain a JSON object.")
        return EditorSettings.from_dict(raw_data)

    def save(self, settings: EditorSettings) -> None:
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            with tempfile.NamedTemporaryFile(
                mode="w", encoding="utf-8", dir=self._path.parent, delete=False
            ) as temporary_file:
                json.dump(settings.to_dict(), temporary_file, indent=2)
                temporary_file.write("\n")
                temporary_path = Path(temporary_file.name)
            temporary_path.replace(self._path)
        except OSError as error:
            raise SettingsStoreError("Could not write local editor settings.") from error
