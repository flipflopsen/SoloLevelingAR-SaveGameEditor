#!/usr/bin/env python3
"""Standalone local save-discovery tool.

Finds locally installed ``LocalSave_*.db`` files for a conventional
17-digit SteamID64 without touching or modifying them. This script is
fully self-contained (standard library only) and does not depend on the
rest of the SaveGameEditor package, so it can be copied and run on its
own.

Usage:
    python find_saves.py <steam_id64>
    python find_saves.py --steam-id 7656119XXXXXXXXXX --home C:\\Users\\Name
"""

from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

SAVE_VENDOR_DIRECTORY = (
    Path("AppData") / "LocalLow" / "NetmarbleNeo" / "Solo_Leveling_ARISE_OVERDRIVE"
)


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


def save_root_for_steam_id(steam_id: str, home_directory: Path | None = None) -> Path:
    """Return the game save root for a SteamID64 without embedding a username."""
    home = home_directory or Path.home()
    return home / SAVE_VENDOR_DIRECTORY / steam_id


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


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="List locally installed Solo Leveling: ARISE OVERDRIVE saves.",
    )
    parser.add_argument(
        "steam_id",
        nargs="?",
        help="17-digit SteamID64 (can also be passed with --steam-id).",
    )
    parser.add_argument("--steam-id", dest="steam_id_flag", help=argparse.SUPPRESS)
    parser.add_argument(
        "--home",
        type=Path,
        default=None,
        help="Override the home directory to search under (defaults to the current user).",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    steam_id = args.steam_id_flag or args.steam_id
    if not steam_id:
        parser.error("a SteamID64 is required (positional or --steam-id).")
    if not steam_id.isdecimal() or len(steam_id) != 17:
        print("error: Steam ID must be a 17-digit SteamID64.", file=sys.stderr)
        return 1

    candidates = discover_save_databases(steam_id, args.home)
    if not candidates:
        root = save_root_for_steam_id(steam_id, args.home)
        print(f"No saves found under: {root}")
        return 0

    for candidate in candidates:
        print(f"{candidate.display_name}\n  {candidate.path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
