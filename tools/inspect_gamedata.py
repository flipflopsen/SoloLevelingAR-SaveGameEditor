"""Inventory every ``GameData/*.byte`` file: hashes, signatures and parse status.

Read-only. Never writes into the GameData directory.

Usage::

    python tools/inspect_gamedata.py --game-data <dir> [--out analysis/gamedata_inventory.json]
    python tools/inspect_gamedata.py --game-data <dir> --self-test
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
import traceback
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import gamedata_codec as codec  # noqa: E402


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def inspect_file(path: Path, *, with_columns: bool = True) -> dict:
    raw = path.stat().st_size
    record: dict = {
        "name": path.name,
        "size": raw,
        "sha256": _sha256(path),
        "head_hex": path.open("rb").read(16).hex(),
        "size_mod_32": raw % 32,
    }
    try:
        plaintext = codec.decrypt_bytes_file(path.read_bytes())
    except Exception as exc:  # pragma: no cover - defensive
        record["status"] = "decrypt_error"
        record["error"] = f"{type(exc).__name__}: {exc}"
        return record
    record["plaintext_size"] = len(plaintext)
    try:
        columns, row_count, table_name = codec.parse_plaintext(plaintext, path.name)
    except Exception as exc:
        record["status"] = "parse_error"
        record["error"] = f"{type(exc).__name__}: {exc}"
        record["plaintext_head_hex"] = plaintext[:48].hex()
        record["plaintext_head_ascii"] = plaintext[:48].decode("latin1")
        return record
    record["status"] = "parsed"
    record["table_name"] = table_name
    record["row_count"] = row_count
    record["column_count"] = len(columns)
    if with_columns:
        types = codec.column_types(path)
        record["columns"] = [
            {"name": name, "type_byte": types.get(name), "sample": _sample(values)}
            for name, values in columns.items()
        ]
    return record


def _sample(values: list) -> list:
    out = []
    for value in values[:3]:
        if isinstance(value, str) and len(value) > 120:
            value = value[:120] + "..."
        out.append(value)
    return out


def self_test(game_data: Path) -> int:
    """Assert the numpy fast path equals the reference pure-Python decrypt."""
    small = sorted(game_data.glob("*.byte"), key=lambda p: p.stat().st_size)[:5]
    failures = 0
    for path in small:
        data = path.read_bytes()
        usable = len(data) - len(data) % codec.BLOCK_SIZE
        ref = bytearray()
        cipher = codec.Rijndael(codec.KEY)
        prev = codec.KEY
        for i in range(0, usable, codec.BLOCK_SIZE):
            block = data[i : i + codec.BLOCK_SIZE]
            dec = cipher.decrypt_block(block)
            ref.extend(x ^ y for x, y in zip(dec, prev, strict=False))
            prev = block
        fast = codec._cbc_decrypt_numpy(codec.KEY, codec.KEY, data[:usable])
        ok = fast is None or bytes(ref) == fast
        print(f"{'OK  ' if ok else 'FAIL'} {path.name} ({usable} bytes)")
        failures += 0 if ok else 1
    return failures


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--game-data", required=True, type=Path)
    parser.add_argument("--out", type=Path)
    parser.add_argument("--no-columns", action="store_true")
    parser.add_argument("--self-test", action="store_true")
    parser.add_argument("--max-size", type=int, default=0, help="skip files larger than N bytes")
    args = parser.parse_args(argv)

    if args.self_test:
        return self_test(args.game_data)

    files = sorted(args.game_data.glob("*.byte"))
    records = []
    for index, path in enumerate(files, 1):
        if args.max_size and path.stat().st_size > args.max_size:
            records.append(
                {"name": path.name, "size": path.stat().st_size, "status": "skipped_too_large"}
            )
            continue
        try:
            records.append(inspect_file(path, with_columns=not args.no_columns))
        except Exception:  # pragma: no cover - defensive
            records.append(
                {"name": path.name, "status": "inspector_crash", "error": traceback.format_exc()}
            )
        print(f"[{index}/{len(files)}] {path.name}: {records[-1].get('status')}", file=sys.stderr)

    summary: dict[str, int] = {}
    for record in records:
        summary[record.get("status", "?")] = summary.get(record.get("status", "?"), 0) + 1
    payload = {"game_data": str(args.game_data), "summary": summary, "files": records}
    text = json.dumps(payload, indent=2, ensure_ascii=False, default=str)
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(text, encoding="utf-8")
        print(json.dumps(summary, indent=2))
    else:
        print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
