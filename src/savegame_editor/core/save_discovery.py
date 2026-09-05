"""Deterministic discovery of locally installed encrypted save databases."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from .paths import save_root_for_steam_id


@dataclass(frozen=True, slots=True)
class SaveCandidate:
    """One discovered save database and the slot that contains it."""

    slot: int
    path: Path
    modified_timestamp: float
    modified_at: datetime

    @property
    def display_name(self) -> str:
        timestamp = self.modified_at.strftime("%Y-%m-%d %H:%M")
        return f"Slot {self.slot} - {self.path.name} - modified {timestamp}"


def discover_save_databases(
    steam_id: str, home_directory: Path | None = None
) -> list[SaveCandidate]:
    """Find ``LocalSave_*.db`` files in the three supported save slots."""
    if not steam_id.isdecimal() or len(steam_id) != 17:
        return []
    root = save_root_for_steam_id(steam_id, home_directory)
    candidates: list[SaveCandidate] = []
    for slot in range(1, 4):
        slot_directory = root / "SaveFolder" / f"Slot{slot}"
        try:
            database_paths = (
                path for path in slot_directory.glob("LocalSave_*.db") if path.is_file()
            )
            for database_path in database_paths:
                modified_timestamp = database_path.stat().st_mtime
                candidates.append(
                    SaveCandidate(
                        slot=slot,
                        path=database_path,
                        modified_timestamp=modified_timestamp,
                        modified_at=datetime.fromtimestamp(modified_timestamp),
                    )
                )
        except OSError:
            continue
    return sorted(
        candidates,
        key=lambda candidate: (
            candidate.slot,
            -candidate.modified_timestamp,
            str(candidate.path).casefold(),
        ),
    )
