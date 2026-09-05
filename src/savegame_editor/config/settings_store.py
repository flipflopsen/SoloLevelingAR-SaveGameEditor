"""Small JSON-backed local configuration store."""

from __future__ import annotations

import sys
import json
import os
import tempfile
from pathlib import Path
from typing import Any

from .models import EditorSettings


class SettingsStoreError(RuntimeError):
    """Raised when local settings cannot be read or written safely."""


def default_settings_path() -> Path:
    """Return the default settings path.

    Packaged executable:
        <executable-directory>/settings.json

    Ordinary Python script:
        <script-directory>/config/settings.json
    """
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent / "settings.json"

    root_directory = Path(sys.argv[0]).resolve().parent
    return root_directory / "config" / "settings.json"


class SettingsStore:
    """Persists ``EditorSettings`` atomically at an injected local path."""

    def __init__(self, path: Path | None = None) -> None:
        self._path = Path(path) if path is not None else default_settings_path()

        if self._path.exists():
            if not self._path.is_file():
                raise ValueError(f"Settings path is not a file: {self._path}")
            return

        self._path.parent.mkdir(parents=True, exist_ok=True)

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
