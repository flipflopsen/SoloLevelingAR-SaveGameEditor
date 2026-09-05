"""Decode a GameData ``.byte`` table to JSON (or list/inspect available tables).

Read-only; never writes into the GameData directory.

Examples::

    python tools/decode_gamedata.py --game-data <dir> --list
    python tools/decode_gamedata.py --game-data <dir> --table ChHunt
    python tools/decode_gamedata.py --game-data <dir> --table It --out decoded/It.json
    python tools/decode_gamedata.py --game-data <dir> --table It --columns ID StringName
    python tools/decode_gamedata.py --game-data <dir> --table ItArti --localize StringName
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import gamedata_codec as codec  # noqa: E402


def load_translations(game_data: Path, language: str) -> dict[str, str]:
    columns, _row_count, _name = codec.parse_file(game_data / "TextData.byte")
    keys = columns["StringID"]
    values = columns.get(language) or columns.get("Value_eng") or columns["Value"]
    return dict(zip(keys, values, strict=False))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--game-data", required=True, type=Path)
    parser.add_argument("--table", help="file stem, e.g. ChHunt (without .byte)")
    parser.add_argument("--list", action="store_true", help="list available tables")
    parser.add_argument("--columns", nargs="*", help="restrict output to these columns")
    parser.add_argument("--rows", type=int, default=0, help="limit number of rows emitted")
    parser.add_argument(
        "--localize",
        nargs="*",
        metavar="COLUMN",
        help="also emit <COLUMN>_localized resolved through TextData.byte",
    )
    parser.add_argument("--language", default="Value_eng", help="TextData language column")
    parser.add_argument("--records", action="store_true", help="emit row dicts instead of columns")
    parser.add_argument("--out", type=Path)
    args = parser.parse_args(argv)

    if args.list:
        rows = []
        for path in sorted(args.game_data.glob("*.byte")):
            rows.append({"table": path.stem, "size": path.stat().st_size})
        print(json.dumps(rows, indent=2))
        return 0

    if not args.table:
        parser.error("--table or --list is required")

    path = args.game_data / f"{args.table}.byte"
    if not path.is_file():
        parser.error(f"no such table file: {path}")

    columns, row_count, table_name = codec.parse_file(path)
    types = codec.column_types(path)

    if args.columns:
        missing = [c for c in args.columns if c not in columns]
        if missing:
            parser.error(f"unknown column(s) {missing}; available: {list(columns)}")
        columns = {c: columns[c] for c in args.columns}

    if args.localize:
        translations = load_translations(args.game_data, args.language)
        for name in args.localize:
            values = columns.get(name)
            if values is None:
                parser.error(f"cannot localize unknown column {name!r}")
            columns[f"{name}_localized"] = [
                translations.get(v, v) if isinstance(v, str) else v for v in values
            ]

    limit = args.rows or row_count
    payload: dict = {
        "source": str(path),
        "table_name": table_name,
        "row_count": row_count,
        "emitted_rows": min(limit, row_count),
        "column_types": {k: types.get(k) for k in columns},
    }
    if args.records:
        names = list(columns)
        payload["records"] = [
            {n: columns[n][i] for n in names} for i in range(min(limit, row_count))
        ]
    else:
        payload["columns"] = {k: v[:limit] for k, v in columns.items()}

    text = json.dumps(payload, indent=2, ensure_ascii=False, default=str)
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(text, encoding="utf-8")
        print(f"wrote {args.out} ({len(text)} bytes, {payload['emitted_rows']} rows)")
    else:
        print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
