"""Optional display-name resolution from locally installed game data."""

from __future__ import annotations

import marshal
import types
from pathlib import Path
from typing import Any


class CatalogResolver:
    """Resolve catalog identifiers without modifying the installed game data.

    Names are tracked both as a legacy merged lookup (``names``, kept for
    backward compatibility) and per source-file (``names_by_file``). The
    per-file lookup lets callers resolve an ID within a specific catalog
    namespace, avoiding accidental collisions between unrelated ID spaces
    that merely happen to share a numeric value.
    """

    def __init__(self, parser_path: Path) -> None:
        self._parser_path = parser_path
        self.names: dict[int, str] = {}
        self.names_by_file: dict[str, dict[int, str]] = {}
        # {level: cumulative TotalExp} from GameData/ChSJWLv.byte, empty if unavailable.
        self.level_curve: dict[int, int] = {}

    def load(self, game_data_directory: Path) -> None:
        if not self._parser_path.is_file():
            raise FileNotFoundError(f"Game-data parser not found: {self._parser_path}")
        if not game_data_directory.is_dir():
            raise NotADirectoryError(f"GameData directory not found: {game_data_directory}")
        module = types.ModuleType("embedded_gamedata")
        exec(marshal.loads(self._parser_path.read_bytes()[16:]), module.__dict__)
        text_columns, _ = module.parse_typed(str(game_data_directory / "TextData.byte"))
        translations = dict(
            zip(
                text_columns["StringID"],
                text_columns.get("Value_eng", text_columns["Value"]),
                strict=False,
            )
        )
        self._load_level_curve(module, game_data_directory)
        filenames = (
            "It",
            "ItArti",
            "ItemGS",
            "ItRelic",
            "CharCostume",
            "ItemTitle",
            "ItemProfile",
            "ItemEmoticon",
            "ChHunt",
            "ChShad",
            "Achi",
        )
        for filename in filenames:
            try:
                columns, _ = module.parse_typed(str(game_data_directory / f"{filename}.byte"))
            except (OSError, ValueError, KeyError):
                continue
            file_names: dict[int, str] = {}
            for index, item_id in enumerate(columns.get("ID", [])):
                if not isinstance(item_id, int):
                    continue
                for name_field in ("StringName", "Name", "StringTitle", "StringID"):
                    values = columns.get(name_field, [])
                    if index < len(values) and isinstance(values[index], str) and values[index]:
                        resolved = translations.get(values[index], values[index])
                        file_names.setdefault(item_id, resolved)
                        self.names.setdefault(item_id, resolved)
                        break
            self.names_by_file[filename] = file_names

    def name(self, item_id: Any) -> str:
        return self.names.get(item_id, f"ID {item_id}")

    def name_in(self, filenames: tuple[str, ...], item_id: Any) -> str | None:
        """Resolve ``item_id`` using only the given source catalogs, or ``None``."""
        if not isinstance(item_id, int):
            return None
        for filename in filenames:
            resolved = self.names_by_file.get(filename, {}).get(item_id)
            if resolved is not None:
                return resolved
        return None

    def _load_level_curve(self, module: types.ModuleType, game_data_directory: Path) -> None:
        """Load ``{level: cumulative TotalExp}`` from ``ChSJWLv.byte``.

        Uses ``parse_byte`` (not ``parse_typed``): the ``TotalExp`` field is
        misdecoded as near-zero denormal floats through the typed parser,
        while ``parse_byte`` returns the correct integers. Leaves the curve
        empty (never raises) if the file is missing or malformed, matching
        the legacy editor's own defensive posture of refusing to write a
        level it cannot pair with a verified XP total.
        """
        try:
            columns, _ = module.parse_byte(str(game_data_directory / "ChSJWLv.byte"))
            levels = columns["Level"]
            totals = columns["TotalExp"]
        except (OSError, ValueError, KeyError):
            return
        self.level_curve = {
            level: total
            for level, total in zip(levels, totals, strict=False)
            if isinstance(level, int) and isinstance(total, int)
        }
