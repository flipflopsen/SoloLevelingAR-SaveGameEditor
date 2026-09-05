"""Persistent, namespaced user overrides for editor-resolved display names.

Overrides are editor metadata only. They never touch the encrypted save
database and must survive table refreshes, full save reloads, save
switching, settings updates, and application restarts (see TASK.md section
7). Storage is a small JSON file, written atomically, kept outside the
repository and outside the encrypted save file.
"""

from __future__ import annotations

import json
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .encryption import SaveEditorError


@dataclass(frozen=True, slots=True)
class MappingKey:
    """A namespace-scoped, collision-safe identity for one overridable entity.

    ``namespace`` keeps unrelated ID spaces (hunters, items, categories, ...)
    from accidentally sharing a name merely because their raw IDs collide.
    ``context`` distinguishes identities that need more than a bare raw ID,
    such as a category namespace scoped to its owning view.
    """

    namespace: str
    raw_id: int
    context: str | None = None

    def token(self) -> str:
        """Return a stable, JSON-key-safe serialization of this identity."""
        parts = [self.namespace, str(self.raw_id)]
        if self.context is not None:
            parts.append(self.context)
        return "\u241f".join(parts)  # unit-separator-like guard against collisions


def default_overrides_path() -> Path:
    """Return the platform-appropriate override-storage path, never a project path."""
    # Local import to avoid a hard dependency cycle; settings_store already
    # defines the correct convention for user-local, non-repository storage.
    from savegame_editor.config.settings_store import default_settings_path

    return default_settings_path().parent / "entity_overrides.json"


class EntityOverrideStore:
    """Load, query, and atomically persist user-defined display-name overrides."""

    def __init__(self, path: Path | None = None) -> None:
        self._path = path or default_overrides_path()
        self._overrides: dict[str, str] = {}
        self._loaded = False

    @property
    def path(self) -> Path:
        return self._path

    def load(self) -> None:
        """(Re)load overrides from disk, tolerating a missing file."""
        if not self._path.is_file():
            self._overrides = {}
            self._loaded = True
            return
        try:
            raw: Any = json.loads(self._path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as error:
            raise SaveEditorError(
                f"Could not read saved display-name overrides: {error}"
            ) from error
        if not isinstance(raw, dict) or not isinstance(raw.get("overrides"), dict):
            raise SaveEditorError("The display-name override file has an unexpected format.")
        self._overrides = {
            key: value for key, value in raw["overrides"].items() if isinstance(value, str)
        }
        self._loaded = True

    def _ensure_loaded(self) -> None:
        if not self._loaded:
            self.load()

    def get(self, key: MappingKey) -> str | None:
        """Return the user override for ``key``, or ``None`` if none is set.

        An empty/whitespace-only stored value is treated as "no override" so
        automatic resolution is restored, per the documented empty-override
        semantics (TASK.md section 7, item 8).
        """
        self._ensure_loaded()
        value = self._overrides.get(key.token())
        return value if value and value.strip() else None

    def set(self, key: MappingKey, value: str) -> None:
        """Persist ``value`` as the override for ``key``.

        Passing an empty or whitespace-only value clears the override and
        restores automatic name resolution.
        """
        self._ensure_loaded()
        token = key.token()
        stripped = value.strip()
        if stripped:
            self._overrides[token] = stripped
        else:
            self._overrides.pop(token, None)
        self._save_atomic()

    def clear(self, key: MappingKey) -> None:
        """Explicitly remove any override for ``key``."""
        self.set(key, "")

    def all_overrides(self) -> dict[str, str]:
        """Return a defensive copy of every stored override token/value pair."""
        self._ensure_loaded()
        return dict(self._overrides)

    def _save_atomic(self) -> None:
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            payload = {"format_version": 1, "overrides": self._overrides}
            with tempfile.NamedTemporaryFile(
                mode="w", encoding="utf-8", dir=self._path.parent, delete=False
            ) as temporary_file:
                json.dump(payload, temporary_file, indent=2, sort_keys=True)
                temporary_file.write("\n")
                temporary_path = Path(temporary_file.name)
            temporary_path.replace(self._path)
        except OSError as error:
            raise SaveEditorError(f"Could not save the display-name override: {error}") from error
